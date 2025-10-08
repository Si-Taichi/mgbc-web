import threading
import time
import math
import traceback
import serial
from dash import Dash, dcc, html, Input, Output, dash_table
import plotly.graph_objects as go
from config import (NUM_BOARDS, MODE, PORT, BAUDRATE, DASHBOARD_UPDATE_INTERVAL,
                    API_ADDRESS, DASH_HOST, DASH_PORT, BOARD_NAMES, WSS_ADDRESS)

# -------------------------
# Shared data store
# -------------------------
class SharedDataStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.board_list = {}          # board_id -> data dict
        self.deployment_history = {}  # board_id -> {"main_deployed": bool, "second_deployed": bool}
        self.start_time = time.time()
        self.num_boards = NUM_BOARDS
        self.board_names = BOARD_NAMES.copy() if isinstance(BOARD_NAMES, dict) else {str(i): f"Board {i}" for i in range(NUM_BOARDS)}
        self.prediction_memory = {}
        self.api_status = "connecting"
        self.last_update = None

    def init_board_data(self):
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

    def elapsed_seconds(self):
        return time.time() - self.start_time

    def update_board_data(self, board_id, parsed_data):
        """Thread-safe update of board data from parsed CSV (dict)"""
        with self.lock:
            if board_id not in self.board_list:
                self.board_list[board_id] = self.init_board_data()
                print(f"✅ Initialized board {board_id} - {self.board_names.get(board_id, 'Unknown')}")
            if board_id not in self.deployment_history:
                self.deployment_history[board_id] = {"main_deployed": False, "second_deployed": False}

            phase = parsed_data.get("phase", "").upper()

            # Update deployment history flags
            if "MAIN" in phase and "DEPLOY" in phase:
                if not self.deployment_history[board_id]["main_deployed"]:
                    self.deployment_history[board_id]["main_deployed"] = True
                    print(f"🪂 {self.board_names.get(board_id, board_id)}: MAIN deployed")
                self.board_list[board_id]["main_deploy"] = True
                display_phase = "DESCENT"
            elif "SECOND" in phase and "DEPLOY" in phase:
                if not self.deployment_history[board_id]["second_deployed"]:
                    self.deployment_history[board_id]["second_deployed"] = True
                    print(f"🪂 {self.board_names.get(board_id, board_id)}: SECOND deployed")
                self.board_list[board_id]["second_deploy"] = True
                display_phase = "DESCENT"
            else:
                display_phase = phase

            # Append numeric fields
            self.board_list[board_id]["x"].append(parsed_data.get("accel_x", 0.0))
            self.board_list[board_id]["y"].append(parsed_data.get("accel_y", 0.0))
            self.board_list[board_id]["z"].append(parsed_data.get("accel_z", 0.0))
            self.board_list[board_id]["lat"].append(parsed_data.get("lat", 0.0))
            self.board_list[board_id]["lon"].append(parsed_data.get("lon", 0.0))
            self.board_list[board_id]["Tempurature"].append(parsed_data.get("temp", 0.0))
            self.board_list[board_id]["Pressure"].append(parsed_data.get("pressure", 0.0))
            self.board_list[board_id]["Humidity"].append(parsed_data.get("humidity", 0.0))
            self.board_list[board_id]["alt"].append(parsed_data.get("alt", 0.0))
            self.board_list[board_id]["phase"].append(display_phase)
            self.board_list[board_id]["time"].append(self.elapsed_seconds())

            self.api_status = "connected"
            self.last_update = time.strftime("%H:%M:%S")
            
            # Debug: Print data count every 50 updates
            data_count = len(self.board_list[board_id]["alt"])
            if data_count % 50 == 0:
                print(f"📊 Board {board_id}: {data_count} data points | Phase: {display_phase} | Alt: {parsed_data.get('alt', 0):.1f}m | Main: {self.board_list[board_id]['main_deploy']} | Second: {self.board_list[board_id]['second_deploy']}")

    def get_board_status(self, board_id):
        """Get board status without lock (caller should have lock)"""
        if board_id not in self.board_list or not self.board_list[board_id]["alt"]:
            return None
        b = self.board_list[board_id]
        return {
            "name": self.board_names.get(board_id, f"Board {board_id}"),
            "phase": b["phase"][-1] if b["phase"] else "UNKNOWN",
            "main_deployed": b["main_deploy"],
            "second_deployed": b["second_deploy"],
            "altitude": b["alt"][-1] if b["alt"] else 0.0,
            "last_seen": time.time()
        }

    def get_all_board_ids(self):
        with self.lock:
            return list(self.board_list.keys())

shared = SharedDataStore()

# -------------------------
# CSV parsing helper
# -------------------------
def parse_csv_string(csv_string):
    """Parse CSV string format: accel_x,accel_y,accel_z,lat,lon,temp,pressure,humidity,alt,phase"""
    try:
        parts = csv_string.strip().split(",")
        if not parts or parts[0].lower().startswith("accel"):
            return None
        if len(parts) < 10:
            return None
        return {
            "accel_x": float(parts[0]),
            "accel_y": float(parts[1]),
            "accel_z": float(parts[2]),
            "lat": float(parts[3]),
            "lon": float(parts[4]),
            "temp": float(parts[5]),
            "pressure": float(parts[6]),
            "humidity": float(parts[7]),
            "alt": float(parts[8]),
            "phase": parts[9].strip()
        }
    except Exception:
        return None

# -------------------------
# Serial fetcher (single thread shared by both dashboards)
# -------------------------
def serial_fetcher_thread(serial_port: str, baud: int):
    """Continuously read serial lines and update shared store."""
    print(f"📡 Serial fetcher starting on {serial_port} @ {baud}")
    try:
        ser = serial.Serial(serial_port, baud, timeout=1)
        print(f"✅ Serial connected: {serial_port} @ {baud}")
    except Exception as e:
        print(f"❌ Unable to open serial port {serial_port}: {e}")
        shared.api_status = "error"
        return

    msg_count = 0
    board_round_robin = 0
    while True:
        try:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode(errors="ignore").strip()
            if not line:
                continue

            msg_count += 1
            parsed = parse_csv_string(line)
            if not parsed:
                continue

            # Distribute messages in round-robin to board IDs 0..NUM_BOARDS-1
            board_id = str(board_round_robin % shared.num_boards)
            shared.update_board_data(board_id, parsed)
            board_round_robin = (board_round_robin + 1) % max(1, shared.num_boards)

            # Occasional log
            if msg_count % 20 == 0:
                print(f"🔥 Received {msg_count} lines. Latest board {board_id}: alt={parsed.get('alt'):.1f}, phase={parsed.get('phase')}")
        except Exception as e:
            print(f"⚠️ Serial reader error: {e}")
            shared.api_status = "error"
            time.sleep(1)

# -------------------------
# UI helpers (common)
# -------------------------
def latlon_to_xy(lat0, lon0, lat, lon):
    R = 6371000.0
    dlat = math.radians(lat - lat0)
    dlon = math.radians(lon - lon0)
    x = dlon * R * math.cos(math.radians((lat + lat0) / 2.0))
    y = dlat * R
    return x, y

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

def generate_board_options():
    """Generate board options dynamically"""
    options = []
    for i in range(shared.num_boards):
        board_name = shared.board_names.get(str(i), f"Board {i}")
        options.append({"label": board_name, "value": str(i)})
    return options

# =========================================================================
# GROUND CONTROL DASHBOARD (Port 8050)
# =========================================================================
app_ground = Dash(__name__, update_title=None, title="Ground Control Dashboard", 
                  routes_pathname_prefix='/ground/', requests_pathname_prefix='/ground/')

app_ground.layout = html.Div([
    html.Div([
        html.H1("Multi Ground Board Dashboard",
                style={"textAlign": "center", "color": "white", "marginBottom": "30px"}),
    ], className="card"),

    html.Div([
        html.P(id="mode-status-ground", children="", 
               style={"color": "lime", "textAlign": "center", "fontSize": "14px", "margin": "10px"}),
        html.P(id="board-count-display-ground", children="Loading board configuration...",
               style={"color": "cyan", "textAlign": "center", "fontSize": "12px", "margin": "5px"}),
    ]),
    
    # Control Panel Row
    html.Div([
        html.Div([
            html.Label("Select board to view", style={"color": "white"}),
            dcc.Dropdown(
                id="board-select-ground",
                options=[],
                value="0",
                clearable=False,
                style={"width": "200px"}
            )
        ], style={"padding": "20px", "flex": "1"}),

        html.Div([
            html.Label("Select BME Metric:", style={"color": "white"}),
            dcc.Dropdown(
                id="bme-dropdown-ground",
                options=[
                    {"label": "Temperature", "value": "Tempurature"},
                    {"label": "Pressure", "value": "Pressure"},
                    {"label": "Humidity", "value": "Humidity"}
                ],
                value="Tempurature", clearable=False,
                style={"width": "200px"}
            ),
        ], style={"padding": "20px", "flex": "1"}),

        html.Div([
            html.Label("Predicted Apogee (m):", style={"color": "white"}),
            dcc.Input(
                id="predicted-apogee-input-ground",
                type="number",
                value=1000,
                placeholder="Enter predicted apogee",
                style={"width": "150px", "margin": "5px"}
            ),
            html.Label("Board for prediction:", style={"marginTop": "10px", "color": "white"}),
            dcc.Dropdown(
                id="prediction-board-select-ground",
                options=[],
                value="0",
                clearable=False,
                style={"width": "150px"}
            ),
            html.Button("Save Prediction", id="save-prediction-btn-ground", 
                       style={"backgroundColor": "#4CAF50", "color": "white", "border": "none", 
                             "padding": "8px 16px", "marginTop": "10px", "borderRadius": "4px"}),
            html.Div(id="prediction-status-ground", style={"color": "lime", "fontSize": "12px", "marginTop": "5px"})
        ], style={"padding": "20px", "flex": "1"}),
    ], style={"display": "flex", "gap": "20px", "backgroundColor": "#1F2937", "borderRadius": "12px"}),

    # Status Board
    html.Div([
        html.H2("Flight Status Board", style={"textAlign": "center", "color": "white"}),
        dash_table.DataTable(
            id="status-board-ground",
            columns=[
                {"name": "Board", "id": "board"},
                {"name": "Phase", "id": "phase"},
                {"name": "Main Deploy", "id": "main_deploy"},
                {"name": "Second Deploy", "id": "second_deploy"},
                {"name": "Altitude (m)", "id": "current_alt"},
                {"name": "Max Alt (m)", "id": "max_alt"},
                {"name": "Predicted", "id": "predicted"},
                {"name": "Difference", "id": "apogee_diff"},
                {"name": "Distance (m)", "id": "distance"},
                {"name": "Score (22.5)", "id": "score"},
            ],
            style_table={"overflowX": "auto"},
            style_header={"backgroundColor": "#21262d", "color": "white", "fontWeight": "600"},
            style_cell={"backgroundColor": "#0d1117", "color": "white", "textAlign": "center", "padding": "10px"},
            style_data_conditional=[
                {'if': {'filter_query': '{phase} = DESCENT'}, 'backgroundColor': '#0e4b99', 'color': 'white'},
                {'if': {'filter_query': '{phase} = COASTING'}, 'backgroundColor': '#8B0000', 'color': 'yellow'},
                {'if': {'filter_query': '{phase} = RISING'}, 'backgroundColor': '#FF4500', 'color': 'white'},
                {'if': {'filter_query': '{main_deploy} = "✅ DEPLOYED"'}, 'color': 'lime'},
                {'if': {'filter_query': '{second_deploy} = "✅ DEPLOYED"'}, 'color': 'lime'}
            ]
        )
    ], style={"margin": "20px 0", "backgroundColor": "#1F2937", "padding": "20px", "borderRadius": "12px"}),

    # Row 1: BME + Accelerometer
    html.Div([
        dcc.Graph(id="2d-bmestats-ground", style={"height": "350px", "flex": "1"}),
        dcc.Graph(id="accelerometer-chart-ground", style={"height": "350px", "flex": "1"}),
    ], style={"display": "flex", "gap": "20px", "marginBottom": "20px"}),

    # Row 2: 3D Trajectory + Globe
    html.Div([
        dcc.Graph(id="3d-trajectory-ground", style={"height": "400px", "flex": "1"}),
        dcc.Graph(id="globe-latlon-ground", style={"height": "400px", "flex": "1"}),
    ], style={"display": "flex", "gap": "20px", "marginBottom": "20px"}),

    # Row 3: Altitude 
    html.Div([
        dcc.Graph(id="altitude-chart-ground", style={"height": "350px", "flex": "1"}),
    ], style={"display": "flex", "gap": "20px", "marginBottom": "20px"}),

    dcc.Interval(id="interval-ground", interval=DASHBOARD_UPDATE_INTERVAL, n_intervals=0)
], style={
    "minHeight": "100vh",
    "background": "linear-gradient(to bottom right, #111827, #1E3A8A, #111827)",
    "padding": "40px"
})

# Ground Dashboard Callbacks
@app_ground.callback(
    Output("prediction-status-ground", "children"),
    Input("save-prediction-btn-ground", "n_clicks"),
    Input("predicted-apogee-input-ground", "value"),
    Input("prediction-board-select-ground", "value"),
    prevent_initial_call=True
)
def save_prediction_ground(n_clicks, predicted_apogee, board_id):
    if n_clicks and predicted_apogee and board_id is not None:
        shared.prediction_memory[board_id] = predicted_apogee
        board_name = shared.board_names.get(board_id, f"Board {board_id}")
        return f"Saved prediction: {predicted_apogee}m for {board_name}"
    return ""

@app_ground.callback(
    Output("board-select-ground", "options"),
    Output("prediction-board-select-ground", "options"),
    Output("board-count-display-ground", "children"),
    Output("mode-status-ground", "children"),
    Input("interval-ground", "n_intervals")
)
def update_board_options_ground(n):
    options = generate_board_options()
    count_msg = f"System: {shared.num_boards} boards configured and active"
    mode_msg = f"📡 Serial Mode: Reading from {PORT} @ {BAUDRATE} baud"
    return options, options, count_msg, mode_msg

@app_ground.callback(
    Output("2d-bmestats-ground", "figure"),
    Output("accelerometer-chart-ground", "figure"),
    Output("altitude-chart-ground", "figure"),
    Output("3d-trajectory-ground", "figure"),
    Output("globe-latlon-ground", "figure"),
    Output("status-board-ground", "data"),
    Input("interval-ground", "n_intervals"),
    Input("board-select-ground", "value"),
    Input("bme-dropdown-ground", "value"),
    Input("predicted-apogee-input-ground", "value"),
    Input("prediction-board-select-ground", "value")
)
def ground_update_charts(n, selected_board, selected_metric, predicted_apogee, prediction_board):
    with shared.lock:
        if selected_board not in shared.board_list or len(shared.board_list[selected_board]["x"]) == 0:
            return go.Figure(), go.Figure(), go.Figure(), go.Figure(), go.Figure(), []
        
        board_data = shared.board_list[selected_board]

        # Status Board Data
        status_rows = []
        for bid, bdata in shared.board_list.items():
            if not bdata["alt"] or not bdata["phase"]:
                continue

            current_alt = bdata["alt"][-1]
            max_alt = max(bdata["alt"])
            current_phase = bdata["phase"][-1]
            
            main_deploy_status = "✅ DEPLOYED" if bdata["main_deploy"] else "⏳ Waiting"
            second_deploy_status = "✅ DEPLOYED" if bdata["second_deploy"] else "⏳ Waiting"
            
            stored_prediction = shared.prediction_memory.get(bid, None)
            predicted_display = f"{stored_prediction}m" if stored_prediction else "Not set"
            
            apogee_diff = "N/A"
            if stored_prediction:
                try:
                    diff = max_alt - float(stored_prediction)
                    apogee_diff = f"{diff:+.1f}m"
                except:
                    apogee_diff = "Error"
            
            distance_m = "N/A"
            if bdata["lat"] and bdata["lon"]:
                lat0, lon0 = bdata["lat"][0], bdata["lon"][0]
                lat_end, lon_end = bdata["lat"][-1], bdata["lon"][-1]
                dx, dy = latlon_to_xy(lat0, lon0, lat_end, lon_end)
                dist_val = math.sqrt(dx**2 + dy**2)
                distance_m = f"{dist_val:.1f}"

            apogee_score = 0
            distance_score = 0

            if stored_prediction:
                try:
                    ratio = (max_alt - float(stored_prediction)) / float(stored_prediction)
                    index_score_pct = 100 * (1 / (1 + (ratio ** 2)))
                    apogee_score = (index_score_pct / 100) * 15
                except:
                    pass

            if isinstance(distance_m, str) and distance_m != "N/A":
                try:
                    dist_val = float(distance_m)
                    if dist_val <= 500:
                        distance_score = ((1 - (dist_val / 500)) * 100 / 100) * 7.5
                except:
                    pass

            total_score = apogee_score + distance_score
            board_name = shared.board_names.get(bid, f"Board {bid}")
            status_rows.append({
                "board": board_name,
                "phase": current_phase,
                "main_deploy": main_deploy_status,
                "second_deploy": second_deploy_status,
                "current_alt": f"{current_alt:.1f}",
                "max_alt": f"{max_alt:.1f}",
                "predicted": predicted_display,
                "apogee_diff": apogee_diff,
                "distance": distance_m,
                "score": f"{total_score:.2f}/22.5"
            })

        # BME Chart
        fig2d = go.Figure(go.Scatter(
            y=board_data[selected_metric],
            x=board_data["time"],
            mode="lines+markers",
            line=dict(color="brown")
        ))
        unit = {"Tempurature": " (C)", "Pressure": " (Pa)", "Humidity": " (%)"}
        selected_board_name = shared.board_names.get(selected_board, f"Board {selected_board}")
        fig2d.update_layout(
            title=f"{selected_metric} Over Time ({selected_board_name})",
            xaxis_title="Time (seconds)",
            yaxis_title=selected_metric + unit.get(selected_metric, ""),
            plot_bgcolor="#102c55", paper_bgcolor="#102c55", font=dict(color="white")
        )

        # Accelerometer Chart
        fig_accel = go.Figure()
        fig_accel.add_trace(go.Scatter(y=board_data["x"], x=board_data["time"], mode="lines+markers", name="X-axis", line=dict(color="red")))
        fig_accel.add_trace(go.Scatter(y=board_data["y"], x=board_data["time"], mode="lines+markers", name="Y-axis", line=dict(color="green")))
        fig_accel.add_trace(go.Scatter(y=board_data["z"], x=board_data["time"], mode="lines+markers", name="Z-axis", line=dict(color="blue")))
        fig_accel.update_layout(
            title=f"Accelerometer Data ({selected_board_name})",
            xaxis_title="Time (seconds)",
            yaxis_title="Acceleration (g)",
            plot_bgcolor="#102c55", paper_bgcolor="#102c55", font=dict(color="white")
        )

        # Altitude Chart
        fig_alt = go.Figure()
        fig_alt.add_trace(go.Scatter(y=board_data["alt"], x=board_data["time"], mode="lines+markers", name="Altitude", line=dict(color="cyan", width=3)))
        fig_alt.update_layout(
            title=f"Altitude Over Time ({selected_board_name})",
            xaxis_title="Time (seconds)",
            yaxis_title="Altitude (m)",
            plot_bgcolor="#102c55", paper_bgcolor="#102c55", font=dict(color="white")
        )

        # 3D Trajectory
        if len(board_data["lat"]) > 1:
            lat0, lon0 = board_data["lat"][0], board_data["lon"][0]
            xs, ys, zs = [], [], []
            for la, lo, al in zip(board_data["lat"], board_data["lon"], board_data["alt"]):
                x, y = latlon_to_xy(lat0, lon0, la, lo)
                xs.append(x)
                ys.append(y)
                zs.append(al)
        else:
            xs, ys, zs = board_data["x"], board_data["y"], board_data["z"]

        fig3d = go.Figure(go.Scatter3d(x=xs, y=ys, z=zs, mode="lines+markers", name=selected_board_name, line=dict(color="blue"), marker=dict(size=4, color="red")))
        fig3d.update_layout(
            scene=dict(xaxis_title="East-West (m)", yaxis_title="North-South (m)", zaxis_title="Altitude (m)", aspectmode="auto", bgcolor="#102c55"),
            margin=dict(l=0, r=0, t=80, b=0),
            title=f"Rocket 3D Trajectory ({selected_board_name})",
            paper_bgcolor="#102c55",
            font=dict(color="white")
        )

        # Globe View
        figgeo = go.Figure()
        for bid, bdata in shared.board_list.items():
            if len(bdata["lat"]) > 1 and bid != selected_board:
                board_name = shared.board_names.get(bid, f"Board {bid}")
                figgeo.add_trace(go.Scattergeo(lon=bdata["lon"], lat=bdata["lat"], mode="lines+markers", name=board_name, line=dict(width=1), marker=dict(size=4), opacity=0.6))

        figgeo.add_trace(go.Scattergeo(lon=board_data["lon"], lat=board_data["lat"], mode="lines+markers", name=f"{selected_board_name} (selected)", line=dict(width=3), marker=dict(size=7)))
        
        if board_data["lat"] and board_data["lon"]:
            last_lat = board_data["lat"][-1]
            last_lon = board_data["lon"][-1]
            figgeo.update_geos(projection_type="orthographic", projection_rotation=dict(lat=last_lat, lon=last_lon), showland=True, landcolor="lightgray", showcountries=True, showocean=True, oceancolor="lightblue")
        
        figgeo.update_layout(title="Latitude Longitude Position", uirevision="stay", paper_bgcolor="#102c55", font=dict(color="white"))

        return fig2d, fig_accel, fig_alt, fig3d, figgeo, status_rows

# =========================================================================
# DEPLOYMENT DASHBOARD (Port 3000)
# =========================================================================
app_deploy = Dash(__name__, update_title=None, title='Deployment Status Monitor',
                  routes_pathname_prefix='/deploy/', requests_pathname_prefix='/deploy/')

app_deploy.layout = html.Div([
    html.Div([
        html.Div([
            html.Div([
                html.H1("Deployment Status Monitor", style={"fontSize": "36px", "fontWeight": "bold", "color": "white", "margin": "0"}),
                html.P("Real-time deployment tracking", style={"fontSize": "14px", "color": "#9CA3AF", "margin": "5px 0 0 0"})
            ])
        ], style={"display": "flex", "alignItems": "center"}),
        html.Div([
            html.Div([
                html.Div(id="api-status-indicator-deploy", style={"width": "12px", "height": "12px", "borderRadius": "50%", "backgroundColor": "#10B981"}),
                html.Span(id="api-status-text-deploy", children="Connecting...", style={"fontSize": "14px", "color": "#D1D5DB", "marginLeft": "8px"})
            ], style={"display": "flex", "alignItems": "center", "justifyContent": "flex-end", "marginBottom": "8px"}),
            html.P(id="last-update-text-deploy", children="Last update: --:--:--", style={"fontSize": "12px", "color": "#6B7280", "margin": "0", "textAlign": "right"})
        ], style={"textAlign": "right"})
    ], style={"backgroundColor": "#1F2937", "padding": "30px", "borderRadius": "12px", "marginBottom": "30px", "border": "1px solid #374151", "display": "flex", "justifyContent": "space-between", "alignItems": "center"}),
    
    html.Div([
        html.Label("Select Board:", style={"color": "white", "fontSize": "18px", "fontWeight": "600", "marginBottom": "10px", "display": "block"}),
        dcc.Dropdown(id="board-selector-deploy", options=[], value=None, placeholder="Select a board to view...", clearable=False, style={"width": "100%", "maxWidth": "400px"})
    ], style={"backgroundColor": "#1F2937", "padding": "20px 30px", "borderRadius": "12px", "marginBottom": "30px", "border": "1px solid #374151"}),
    
    html.Div(id="status-card-container-deploy", children=[]),
    
    html.Div([
        html.Div([
            html.P([html.Span("Data Source: ", style={"fontWeight": "600", "color": "white"}), html.Span(id="data-source-text-deploy", children="", style={"color": "#9CA3AF"})], style={"margin": "0", "fontSize": "14px"}),
            html.P([html.Span("Active Boards: ", style={"fontWeight": "600", "color": "white"}), html.Span(id="active-boards-count-deploy", children="0", style={"color": "#9CA3AF"})], style={"margin": "0", "fontSize": "14px"})
        ], style={"display": "flex", "justifyContent": "space-between"})
    ], style={"backgroundColor": "#1F2937", "padding": "20px", "borderRadius": "12px", "marginTop": "30px", "border": "1px solid #374151"}),
    
    dcc.Interval(id="interval-component-deploy", interval=1000, n_intervals=0)
], style={"minHeight": "100vh", "background": "linear-gradient(to bottom right, #111827, #1E3A8A, #111827)", "padding": "40px", "maxWidth": "1200px", "margin": "0 auto"})

# Deployment Dashboard Callbacks
@app_deploy.callback(
    Output("board-selector-deploy", "options"),
    Output("board-selector-deploy", "value"),
    Output("data-source-text-deploy", "children"),
    Input("interval-component-deploy", "n_intervals"),
    Input("board-selector-deploy", "value")
)
def update_board_options_deploy(n, current_value):
    options = generate_board_options()
    source_text = f"Serial Port {PORT} @ {BAUDRATE} baud"
    
    # Debug output every 10 intervals
    if n % 10 == 0:
        with shared.lock:
            print(f"🔍 Deploy Dashboard: Found {len(shared.board_list)} boards - IDs: {list(shared.board_list.keys())}")
            print(f"   Current selection: {current_value}, Available options: {[opt['value'] for opt in options]}")
    
    if current_value is None and options:
        return options, options[0]["value"], source_text
    
    if current_value in [opt["value"] for opt in options]:
        return options, current_value, source_text
    
    if options:
        return options, options[0]["value"], source_text
    
    return options, None, source_text

@app_deploy.callback(
    Output("status-card-container-deploy", "children"),
    Output("api-status-indicator-deploy", "style"),
    Output("api-status-text-deploy", "children"),
    Output("last-update-text-deploy", "children"),
    Output("active-boards-count-deploy", "children"),
    Input("interval-component-deploy", "n_intervals"),
    Input("board-selector-deploy", "value")
)
def update_dashboard_deploy(n, selected_board):
    with shared.lock:
        if shared.api_status == "connected":
            status_color = "#10B981"
            status_text = "Serial Connected"
        else:
            status_color = "#EF4444"
            status_text = "Serial Disconnected"
        
        status_indicator_style = {"width": "12px", "height": "12px", "borderRadius": "50%", "backgroundColor": status_color}
        update_text = f"Last update: {shared.last_update}" if shared.last_update else "Last update: --:--:--"
        active_count = str(len(shared.board_list))
        
        if not shared.board_list:
            if shared.api_status == "connected":
                card = html.Div([
                    html.Div("⚠️", style={"fontSize": "64px", "marginBottom": "20px"}),
                    html.H3("No Boards Detected", style={"fontSize": "24px", "fontWeight": "bold", "color": "white", "marginBottom": "10px"}),
                    html.P("Waiting for board connections...", style={"color": "#9CA3AF"})
                ], style={"textAlign": "center", "padding": "80px 20px", "color": "white"})
            else:
                card = html.Div([
                    html.Div("❌", style={"fontSize": "64px", "marginBottom": "20px"}),
                    html.H3("Connection Error", style={"fontSize": "24px", "fontWeight": "bold", "color": "white", "marginBottom": "10px"}),
                    html.P(f"Cannot connect to serial port {PORT}", style={"color": "#9CA3AF", "marginBottom": "5px"}),
                    html.P("Make sure the device is connected", style={"fontSize": "12px", "color": "#6B7280"})
                ], style={"textAlign": "center", "padding": "80px 20px", "color": "white"})
        elif selected_board is None:
            card = html.Div([
                html.Div("👆", style={"fontSize": "64px", "marginBottom": "20px"}),
                html.H3("Select a Board", style={"fontSize": "24px", "fontWeight": "bold", "color": "white", "marginBottom": "10px"}),
            ], style={"textAlign": "center", "padding": "80px 20px", "color": "white"})
        elif selected_board in shared.board_list:
            # Get status directly from board_list (we already have the lock)
            status = shared.get_board_status(selected_board)
            if status:
                card = create_status_card_deploy(selected_board, status)
            else:
                card = html.Div([
                    html.Div("⏳", style={"fontSize": "64px", "marginBottom": "20px"}),
                    html.H3("Loading Data...", style={"fontSize": "24px", "fontWeight": "bold", "color": "white", "marginBottom": "10px"}),
                    html.P("Waiting for sensor data", style={"color": "#9CA3AF"})
                ], style={"textAlign": "center", "padding": "80px 20px", "color": "white"})
        else:
            card = html.Div([
                html.Div("❓", style={"fontSize": "64px", "marginBottom": "20px"}),
                html.H3("Board Not Found", style={"fontSize": "24px", "fontWeight": "bold", "color": "white", "marginBottom": "10px"}),
                html.P(f"Board {selected_board} is not available", style={"color": "#9CA3AF"})
            ], style={"textAlign": "center", "padding": "80px 20px", "color": "white"})
        
        return card, status_indicator_style, status_text, update_text, active_count

def create_status_card_deploy(board_id, status):
    phase_color = get_phase_color(status["phase"])
    
    return html.Div([
        html.Div([
            html.Div([
                html.H2(status["name"], style={"fontSize": "32px", "fontWeight": "bold", "color": "white", "margin": "0"}),
                html.Span(status["phase"], style={"fontSize": "18px", "fontWeight": "600", "color": "white", "backgroundColor": "rgba(0,0,0,0.3)", "padding": "8px 20px", "borderRadius": "12px"})
            ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"})
        ], style={"backgroundColor": phase_color, "padding": "30px 40px"}),
        
        html.Div([
            html.Div([
                html.Div([
                    html.Div([
                        html.Span("✓" if status["main_deployed"] else "⏳", style={"fontSize": "64px", "color": "#4ADE80" if status["main_deployed"] else "#FBBF24"}),
                        html.Div([
                            html.P("Main Deployment", style={"color": "white", "fontWeight": "700", "margin": "0", "fontSize": "36px"}),
                            html.P("Primary deployment system", style={"color": "#9CA3AF", "margin": "5px 0 0 0", "fontSize": "18px"})
                        ], style={"marginLeft": "30px"})
                    ], style={"display": "flex", "alignItems": "center"}),
                    html.Span("DEPLOYED" if status["main_deployed"] else "STANDBY", style={"fontSize": "20px", "fontWeight": "700", "color": "white", "backgroundColor": "#16A34A" if status["main_deployed"] else "#CA8A04", "padding": "12px 30px", "borderRadius": "12px"})
                ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"})
            ], style={"backgroundColor": "#111827", "padding": "40px", "borderRadius": "12px", "border": "2px solid #374151", "marginBottom": "24px"}),
            
            html.Div([
                html.Div([
                    html.Div([
                        html.Span("✓" if status["second_deployed"] else "⏳", style={"fontSize": "64px", "color": "#4ADE80" if status["second_deployed"] else "#FBBF24"}),
                        html.Div([
                            html.P("Second Deployment", style={"color": "white", "fontWeight": "700", "margin": "0", "fontSize": "36px"}),
                            html.P("Secondary deployment system", style={"color": "#9CA3AF", "margin": "5px 0 0 0", "fontSize": "18px"})
                        ], style={"marginLeft": "30px"})
                    ], style={"display": "flex", "alignItems": "center"}),
                    html.Span("DEPLOYED" if status["second_deployed"] else "STANDBY", style={"fontSize": "20px", "fontWeight": "700", "color": "white", "backgroundColor": "#16A34A" if status["second_deployed"] else "#CA8A04", "padding": "12px 30px", "borderRadius": "12px"})
                ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"})
            ], style={"backgroundColor": "#111827", "padding": "40px", "borderRadius": "12px", "border": "2px solid #374151"})
        ], style={"padding": "40px"})
    ], style={"backgroundColor": "#1F2937", "borderRadius": "12px", "overflow": "hidden", "border": "1px solid #374151", "transition": "all 0.3s"})

# =========================================================================
# MAIN: Start serial fetcher and run both apps
# =========================================================================
if __name__ == "__main__":
    print("="*60)
    print("Starting Unified Dashboard System...")
    print("="*60)
    print(f"Mode: SERIAL")
    print(f"Serial Port: {PORT}")
    print(f"Baud Rate: {BAUDRATE}")
    print(f"Expected Boards: {NUM_BOARDS}")
    print(f"Ground Control Dashboard: http://localhost:8050/ground/")
    print(f"Deployment Dashboard: http://localhost:3000/deploy/")
    print("="*60)
    
    # Start single serial fetcher thread (shared by both dashboards)
    threading.Thread(target=serial_fetcher_thread, args=(PORT, BAUDRATE), daemon=True).start()
    
    # Run both Dash apps in separate threads
    def run_ground():
        app_ground.run(debug=False, host='localhost', port=8050, use_reloader=False)
    
    def run_deploy():
        app_deploy.run(debug=False, host='localhost', port=3000, use_reloader=False)
    
    # Start ground dashboard in background thread
    ground_thread = threading.Thread(target=run_ground, daemon=True)
    ground_thread.start()
    
    # Start deployment dashboard in main thread
    run_deploy()

