from dash import Dash, dcc, html, Input, Output, dash_table
import plotly.graph_objects as go
import requests
import threading
import time
import traceback
import math
import serial
import websockets
import asyncio
from config import NUM_BOARDS, MODE, PORT, BAUDRATE, DASHBOARD_UPDATE_INTERVAL, API_ADDRESS, DASH_HOST, DASH_PORT, BOARD_NAMES, WSS_ADDRESS

app = Dash(__name__, update_title=None, title='Unified Dashboard - Ground Control & Deployment')

def init_board_data():
    return {
        "x": [], "y": [], "z": [],
        "lat": [], "lon": [],
        "Tempurature": [], "Pressure": [], "Humidity": [],
        "alt": [],
        "phase": [],
        "time": [],
        "main_deploy": False,
        "second_deploy": False
    }

# Shared global variables
all_board = []
board_list = {}
board_statuses = {}
deployment_history = {}
start_time = time.time()
num_boards = NUM_BOARDS
board_names = BOARD_NAMES
prediction_memory = {}
api_status = "connecting"
last_update = None

def latlon_to_xy(lat0, lon0, lat, lon):
    """Convert lat/lon to local x,y in meters relative to lat0,lon0"""
    R = 6371000.0
    dlat = math.radians(lat - lat0)
    dlon = math.radians(lon - lon0)
    x = dlon * R * math.cos(math.radians((lat + lat0) / 2.0))
    y = dlat * R
    return x, y

def elapsed_seconds():
    return time.time() - start_time

def parse_csv_string(csv_string):
    """Parse CSV string with proper type conversion"""
    try:
        parts = csv_string.strip().split(",")
        if parts[0].lower() == "accel_x":
            return None
        if len(parts) != 10:
            return None
            
        try:
            x = float(parts[0].strip())
            y = float(parts[1].strip())
            z = float(parts[2].strip())
            lat = float(parts[3].strip())
            lon = float(parts[4].strip())
            temp = float(parts[5].strip())
            pressure = float(parts[6].strip())
            humidity = float(parts[7].strip())
            alt = float(parts[8].strip())
            phase = parts[9].strip()

            return {
                "LIS331DLH axis x": [x],
                "LIS331DLH axis y": [y],
                "LIS331DLH axis z": [z],
                "lc86g lat": [lat],
                "lc86g lon": [lon],
                "bme tempurature": [temp],
                "bme pressure": [pressure],
                "bme humidity": [humidity],
                "lc86g alt": [alt],
                "phase": [phase]
            }
        except ValueError:
            return None
    except Exception:
        return None

def update_board_data(board_id, v):
    """Update both board_list and board_statuses with parsed data"""
    global board_list, board_statuses, deployment_history, api_status, last_update
    
    if board_id not in board_list:
        board_list[board_id] = init_board_data()
    
    if board_id not in deployment_history:
        deployment_history[board_id] = {
            "main_deployed": False,
            "second_deployed": False
        }
    
    board_list[board_id]["x"].append(v["LIS331DLH axis x"][0])
    board_list[board_id]["y"].append(v["LIS331DLH axis y"][0])
    board_list[board_id]["z"].append(v["LIS331DLH axis z"][0])
    board_list[board_id]["lat"].append(v["lc86g lat"][0])
    board_list[board_id]["lon"].append(v["lc86g lon"][0])
    board_list[board_id]["Tempurature"].append(v["bme tempurature"][0])
    board_list[board_id]["Pressure"].append(v["bme pressure"][0])
    board_list[board_id]["Humidity"].append(v["bme humidity"][0])
    board_list[board_id]["alt"].append(v["lc86g alt"][0])
    
    phase_raw = v["phase"][0].upper()
    
    if "MAIN" in phase_raw and "DEPLOY" in phase_raw:
        board_list[board_id]["main_deploy"] = True
        deployment_history[board_id]["main_deployed"] = True
        display_phase = "DESCENT"
    elif "SECOND" in phase_raw and "DEPLOY" in phase_raw:
        board_list[board_id]["second_deploy"] = True
        deployment_history[board_id]["second_deployed"] = True
        display_phase = "DESCENT"
    else:
        display_phase = phase_raw
    
    board_list[board_id]["phase"].append(display_phase)
    board_list[board_id]["time"].append(elapsed_seconds())
    
    # Update deployment status
    board_statuses[board_id] = {
        "name": board_names.get(int(board_id), f"Board {board_id}"),
        "phase": display_phase,
        "main_deployed": deployment_history[board_id]["main_deployed"],
        "second_deployed": deployment_history[board_id]["second_deployed"],
        "altitude": v["lc86g alt"][0],
        "last_seen": time.time()
    }
    
    api_status = "connected"
    last_update = time.strftime("%H:%M:%S")

def data_fetcher_websocket():
    """Unified WebSocket data fetcher"""
    global all_board, board_list, num_boards, board_names, api_status

    ws_url = WSS_ADDRESS + "/gcs/all"
    print(f"🌐 Connecting to WebSocket at {ws_url}")
    print(f"📊 Expecting data from {NUM_BOARDS} boards")

    async def ws_listener():
        retry_count = 0
        max_retries = 5
        
        while retry_count < max_retries:
            try:
                print(f"🔄 Connection attempt {retry_count + 1}/{max_retries}")
                
                async with websockets.connect(
                    ws_url,
                    ping_interval=None,
                    open_timeout=None,
                    close_timeout=None,
                    max_size=10_000_000,
                    compression=None
                ) as ws:
                    print("✅ WebSocket connected. Listening for data...")
                    retry_count = 0
                    api_status = "connected"
                    
                    message_count = 0
                    
                    async for message in ws:
                        message_count += 1
                        
                        v = parse_csv_string(message)
                        if not v:
                            continue

                        board_id = str(message_count % NUM_BOARDS)
                        update_board_data(board_id, v)
                        
                        if message_count % (NUM_BOARDS * 20) == 0:
                            board_name = board_names.get(int(board_id), f"Board {board_id}")
                            print(f"📥 {board_name}: Alt={v['lc86g alt'][0]:.2f}m | Phase={v['phase'][0]}")

            except Exception as e:
                print(f"❌ WebSocket error: {type(e).__name__}: {e}")
                retry_count += 1
                api_status = "error"
                
            wait_time = min(5 * retry_count, 30)
            await asyncio.sleep(wait_time)

    def run_loop():
        asyncio.run(ws_listener())

    threading.Thread(target=run_loop, daemon=True).start()
    while True:
        time.sleep(60)

def data_fetcher_api():
    """Unified API data fetcher"""
    global all_board, board_list, num_boards, board_names, api_status
    
    print("📡 Data fetcher running in API mode...")
    
    while True:
        try:
            url = f"{API_ADDRESS}/gcs/all"
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                num_boards = len(data)
                
                all_board = []
                for board_id, csv_string in data.items():
                    v = parse_csv_string(csv_string)
                    if not v:
                        continue
                    all_board.append(v)
                    update_board_data(board_id, v)
            else:
                api_status = "error"
        except Exception as e:
            print(f"❌ API error: {repr(e)}")
            api_status = "error"
        
        time.sleep(1)

def data_fetcher_serial():
    """Unified Serial data fetcher"""
    global all_board, board_list, num_boards, board_names, api_status
    
    num_boards = 1
    board_names = {"0": "Serial Board"}
    
    print(f"📡 Connecting to serial port {PORT} @ {BAUDRATE} baud...")
    
    try:
        ser = serial.Serial(PORT, BAUDRATE, timeout=1)
        print(f"✅ Connected to serial port {PORT}")
    except Exception as e:
        print(f"❌ Could not open serial port: {e}")
        return

    line_count = 0
    
    while True:
        try:
            line = ser.readline().decode("utf-8", errors='ignore').strip()
            if not line:
                continue
            
            line_count += 1
            v = parse_csv_string(line)
            if not v:
                continue

            all_board = [v]
            update_board_data("0", v)
            
            if line_count % 10 == 0:
                print(f"📊 Received {line_count} data points")

        except Exception as e:
            print(f"❌ Serial error: {repr(e)}")
            time.sleep(1)

def data_fetcher_main():
    """Main data fetcher router"""
    if MODE == "serial":
        data_fetcher_serial()
    elif MODE == "websocket":
        data_fetcher_websocket()
    elif MODE == "api":
        data_fetcher_api()

def generate_board_options():
    """Generate board options"""
    options = []
    for i in range(num_boards):
        board_name = board_names.get(str(i), f"Board {i}")
        options.append({"label": board_name, "value": str(i)})
    return options

def get_phase_color(phase):
    """Get color based on flight phase"""
    if phase == "GROUND" or phase == "IDLE":
        return "#4B5563"
    elif phase == "RISING" or phase == "LAUNCH":
        return "#F97316"
    elif phase == "COASTING":
        return "#DC2626"
    elif "DEPLOY" in phase or phase == "DESCENT":
        return "#3B82F6"
    elif phase == "LANDED":
        return "#10B981"
    return "#6B7280"

def create_deployment_card(board_id, status):
    """Create deployment status card"""
    phase_color = get_phase_color(status["phase"])
    
    return html.Div([
        html.Div([
            html.Div([
                html.H2(status["name"], style={
                    "fontSize": "24px",
                    "fontWeight": "bold",
                    "color": "white",
                    "margin": "0"
                }),
                html.Span(status["phase"], style={
                    "fontSize": "14px",
                    "fontWeight": "600",
                    "color": "white",
                    "backgroundColor": "rgba(0,0,0,0.3)",
                    "padding": "6px 14px",
                    "borderRadius": "8px"
                })
            ], style={
                "display": "flex",
                "justifyContent": "space-between",
                "alignItems": "center"
            })
        ], style={
            "backgroundColor": phase_color,
            "padding": "20px"
        }),
        
        html.Div([
            html.Div([
                html.Span("✓" if status["main_deployed"] else "⏳", style={
                    "fontSize": "32px",
                    "color": "#4ADE80" if status["main_deployed"] else "#FBBF24",
                    "marginRight": "10px"
                }),
                html.Div([
                    html.P("Main Deployment", style={
                        "color": "white",
                        "fontWeight": "600",
                        "margin": "0",
                        "fontSize": "16px"
                    }),
                    html.Span(
                        "DEPLOYED" if status["main_deployed"] else "STANDBY",
                        style={
                            "fontSize": "12px",
                            "color": "#4ADE80" if status["main_deployed"] else "#FBBF24"
                        }
                    )
                ])
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "10px"}),
            
            html.Div([
                html.Span("✓" if status["second_deployed"] else "⏳", style={
                    "fontSize": "32px",
                    "color": "#4ADE80" if status["second_deployed"] else "#FBBF24",
                    "marginRight": "10px"
                }),
                html.Div([
                    html.P("Second Deployment", style={
                        "color": "white",
                        "fontWeight": "600",
                        "margin": "0",
                        "fontSize": "16px"
                    }),
                    html.Span(
                        "DEPLOYED" if status["second_deployed"] else "STANDBY",
                        style={
                            "fontSize": "12px",
                            "color": "#4ADE80" if status["second_deployed"] else "#FBBF24"
                        }
                    )
                ])
            ], style={"display": "flex", "alignItems": "center"})
        ], style={"padding": "20px"})
    ], style={
        "backgroundColor": "#1F2937",
        "borderRadius": "8px",
        "overflow": "hidden",
        "border": "1px solid #374151",
        "marginBottom": "10px"
    })

# App Layout with Tabs
app.layout = html.Div([
    html.Div([
        html.H1("🚀 Unified Flight Dashboard", style={
            "textAlign": "center",
            "color": "white",
            "margin": "0",
            "padding": "20px"
        }),
        html.Div([
            html.Span(id="connection-status", children="", style={
                "color": "lime",
                "fontSize": "14px",
                "marginRight": "20px"
            }),
            html.Span(id="board-count", children="", style={
                "color": "cyan",
                "fontSize": "14px"
            })
        ], style={"textAlign": "center", "marginBottom": "20px"})
    ], style={"backgroundColor": "#1F2937", "borderRadius": "12px", "marginBottom": "20px"}),
    
    dcc.Tabs(id="tabs", value='ground-control', children=[
        dcc.Tab(label='📊 Ground Control', value='ground-control', style={
            "backgroundColor": "#1F2937",
            "color": "white"
        }, selected_style={
            "backgroundColor": "#3B82F6",
            "color": "white",
            "fontWeight": "bold"
        }),
        dcc.Tab(label='🪂 Deployment Status', value='deployment', style={
            "backgroundColor": "#1F2937",
            "color": "white"
        }, selected_style={
            "backgroundColor": "#3B82F6",
            "color": "white",
            "fontWeight": "bold"
        }),
    ]),
    
    html.Div(id='tabs-content'),
    
    dcc.Interval(id="interval", interval=DASHBOARD_UPDATE_INTERVAL, n_intervals=0)
], style={
    "minHeight": "100vh",
    "background": "linear-gradient(to bottom right, #111827, #1E3A8A, #111827)",
    "padding": "20px"
})

@app.callback(
    Output("connection-status", "children"),
    Output("board-count", "children"),
    Input("interval", "n_intervals")
)
def update_header(n):
    if api_status == "connected":
        if MODE == "websocket":
            status_msg = f"🟢 WebSocket Connected to {WSS_ADDRESS}"
        elif MODE == "api":
            status_msg = f"🟢 API Connected to {API_ADDRESS}"
        else:
            status_msg = f"🟢 Serial Connected to {PORT}"
    else:
        status_msg = "🔴 Disconnected"
    
    count_msg = f"📡 {num_boards} Active Boards | ⏰ {last_update if last_update else '--:--:--'}"
    
    return status_msg, count_msg

@app.callback(
    Output('tabs-content', 'children'),
    Input('tabs', 'value'),
    Input('interval', 'n_intervals')
)
def render_content(tab, n):
    if tab == 'ground-control':
        return render_ground_control()
    elif tab == 'deployment':
        return render_deployment_status()

def render_ground_control():
    """Render Ground Control tab content"""
    options = generate_board_options()
    
    return html.Div([
        # Control Panel
        html.Div([
            html.Div([
                html.Label("Select Board:", style={"color": "white", "marginBottom": "5px"}),
                dcc.Dropdown(
                    id="board-select-gc",
                    options=options,
                    value="0" if options else None,
                    clearable=False,
                    style={"width": "200px"}
                )
            ], style={"padding": "10px"}),
            
            html.Div([
                html.Label("BME Metric:", style={"color": "white", "marginBottom": "5px"}),
                dcc.Dropdown(
                    id="bme-dropdown",
                    options=[
                        {"label": "Temperature", "value": "Tempurature"},
                        {"label": "Pressure", "value": "Pressure"},
                        {"label": "Humidity", "value": "Humidity"}
                    ],
                    value="Tempurature",
                    clearable=False,
                    style={"width": "200px"}
                )
            ], style={"padding": "10px"}),
        ], style={"display": "flex", "gap": "20px", "backgroundColor": "#1F2937", "borderRadius": "8px", "padding": "15px", "marginBottom": "20px"}),
        
        # Status Board
        html.Div([
            dash_table.DataTable(
                id="status-board-gc",
                columns=[
                    {"name": "Board", "id": "board"},
                    {"name": "Phase", "id": "phase"},
                    {"name": "Altitude (m)", "id": "current_alt"},
                    {"name": "Max Alt (m)", "id": "max_alt"},
                ],
                style_table={"overflowX": "auto"},
                style_header={"backgroundColor": "#21262d", "color": "white", "fontWeight": "600"},
                style_cell={"backgroundColor": "#0d1117", "color": "white", "textAlign": "center", "padding": "10px"}
            )
        ], style={"marginBottom": "20px"}),
        
        # Charts Row 1
        html.Div([
            dcc.Graph(id="bme-chart", style={"height": "300px", "flex": "1"}),
            dcc.Graph(id="accel-chart", style={"height": "300px", "flex": "1"}),
        ], style={"display": "flex", "gap": "15px", "marginBottom": "15px"}),
        
        # Charts Row 2
        html.Div([
            dcc.Graph(id="altitude-chart", style={"height": "300px", "flex": "1"}),
        ], style={"marginBottom": "15px"}),
    ])

def render_deployment_status():
    """Render Deployment Status tab content"""
    options = generate_board_options()
    
    deployment_cards = []
    for board_id in sorted(board_statuses.keys(), key=lambda x: int(x)):
        status = board_statuses[board_id]
        deployment_cards.append(create_deployment_card(board_id, status))
    
    if not deployment_cards:
        deployment_cards = [html.Div([
            html.P("⏳ Waiting for board data...", style={
                "color": "white",
                "textAlign": "center",
                "fontSize": "18px",
                "padding": "40px"
            })
        ])]
    
    return html.Div([
        html.Div([
            html.Label("Select Board for Details:", style={"color": "white", "marginBottom": "10px", "display": "block"}),
            dcc.Dropdown(
                id="board-select-dep",
                options=options,
                value=options[0]["value"] if options else None,
                clearable=False,
                style={"width": "300px"}
            )
        ], style={"backgroundColor": "#1F2937", "padding": "20px", "borderRadius": "8px", "marginBottom": "20px"}),
        
        html.Div([
            html.H3("All Boards Deployment Overview", style={"color": "white", "marginBottom": "15px"}),
            html.Div(deployment_cards, style={
                "display": "grid",
                "gridTemplateColumns": "repeat(auto-fill, minmax(300px, 1fr))",
                "gap": "15px"
            })
        ])
    ])

@app.callback(
    Output("status-board-gc", "data"),
    Output("bme-chart", "figure"),
    Output("accel-chart", "figure"),
    Output("altitude-chart", "figure"),
    Input("interval", "n_intervals"),
    Input("board-select-gc", "value"),
    Input("bme-dropdown", "value")
)
def update_ground_control(n, selected_board, selected_metric):
    # Status board data
    status_rows = []
    for bid, bdata in board_list.items():
        if not bdata["alt"] or not bdata["phase"]:
            continue
        board_name = board_names.get(bid, f"Board {bid}")
        status_rows.append({
            "board": board_name,
            "phase": bdata["phase"][-1] if bdata["phase"] else "N/A",
            "current_alt": f"{bdata['alt'][-1]:.1f}" if bdata["alt"] else "0",
            "max_alt": f"{max(bdata['alt']):.1f}" if bdata["alt"] else "0"
        })
    
    if not selected_board or selected_board not in board_list or len(board_list[selected_board]["x"]) == 0:
        return status_rows, go.Figure(), go.Figure(), go.Figure()
    
    board_data = board_list[selected_board]
    
    # BME Chart
    fig_bme = go.Figure(go.Scatter(
        y=board_data[selected_metric],
        x=board_data["time"],
        mode="lines+markers",
        line=dict(color="brown")
    ))
    unit = {"Tempurature": " (°C)", "Pressure": " (Pa)", "Humidity": " (%)"}
    fig_bme.update_layout(
        title=f"{selected_metric} Over Time",
        xaxis_title="Time (s)",
        yaxis_title=selected_metric + unit.get(selected_metric, ""),
        plot_bgcolor="#102c55",
        paper_bgcolor="#102c55",
        font=dict(color="white")
    )
    
    # Accelerometer Chart
    fig_accel = go.Figure()
    fig_accel.add_trace(go.Scatter(y=board_data["x"], x=board_data["time"], mode="lines", name="X", line=dict(color="red")))
    fig_accel.add_trace(go.Scatter(y=board_data["y"], x=board_data["time"], mode="lines", name="Y", line=dict(color="green")))
    fig_accel.add_trace(go.Scatter(y=board_data["z"], x=board_data["time"], mode="lines", name="Z", line=dict(color="blue")))
    fig_accel.update_layout(
        title="Accelerometer Data",
        xaxis_title="Time (s)",
        yaxis_title="Acceleration (g)",
        plot_bgcolor="#102c55",
        paper_bgcolor="#102c55",
        font=dict(color="white")
    )
    
    # Altitude Chart
    fig_alt = go.Figure(go.Scatter(
        y=board_data["alt"],
        x=board_data["time"],
        mode="lines+markers",
        line=dict(color="cyan", width=3)
    ))
    fig_alt.update_layout(
        title="Altitude Over Time",
        xaxis_title="Time (s)",
        yaxis_title="Altitude (m)",
        plot_bgcolor="#102c55",
        paper_bgcolor="#102c55",
        font=dict(color="white")
    )
    
    return status_rows, fig_bme, fig_accel, fig_alt

if __name__ == "__main__":
    print("="*60)
    print("🚀 Starting Unified Flight Dashboard")
    print("="*60)
    print(f"Mode: {MODE.upper()}")
    if MODE == "websocket":
        print(f"WebSocket: {WSS_ADDRESS}/gcs/all")
    elif MODE == "api":
        print(f"API: {API_ADDRESS}/gcs/all")
    else:
        print(f"Serial: {PORT} @ {BAUDRATE} baud")
    print(f"Dashboard: http://{DASH_HOST}:{DASH_PORT}")
    print("="*60)
    
    threading.Thread(target=data_fetcher_main, daemon=True).start()
    
    app.run(debug=True, host=DASH_HOST, port=DASH_PORT, use_reloader=False)