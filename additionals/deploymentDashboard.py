from dash import Dash, dcc, html, Input, Output
import requests
import threading
import time
import serial
import traceback
import websockets
import asyncio
from config import API_ADDRESS, DASH_HOST, DASH_PORT, BOARD_NAMES, NUM_BOARDS, MODE, PORT, BAUDRATE, WSS_ADDRESS

app = Dash(__name__, update_title=None, title='Deployment Status Monitor')

board_statuses = {}
deployment_history = {}
api_status = "connecting"
last_update = None
num_boards = NUM_BOARDS
board_names = BOARD_NAMES

def parse_csv_string(csv_string):
    """Parse CSV string from API, Serial, or WebSocket"""
    try:
        parts = csv_string.strip().split(",")
        
        if parts[0].lower() == "accel_x":
            return None
        
        if len(parts) != 10:
            return None
            
        return {
            "accel_x": float(parts[0]),
            "accel_y": float(parts[1]),
            "accel_z": float(parts[2]),
            "lat": float(parts[3]),
            "lon": float(parts[4]),
            "temp": float(parts[5]),
            "pressure": float(parts[6]),
            "humidity": float(parts[8]),
            "alt": float(parts[9]),
            "phase": parts[10].strip().upper()
        }
    except Exception as e:
        print(f"Parse error: {e}")
        return None

def fetch_deployment_status_websocket():
    """
    Async WebSocket mode - receives data from all boards using /gcs/all
    Matches the groundDashboard.py implementation
    """
    global board_statuses, api_status, last_update, deployment_history, num_boards, board_names

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
                    print("✅ WebSocket connected. Listening for deployment data...")
                    retry_count = 0
                    api_status = "connected"
                    
                    message_count = 0
                    
                    async for message in ws:
                        message_count += 1
                        
                        # Parse the CSV
                        parsed_data = parse_csv_string(message)
                        if not parsed_data:
                            print(f"⚠️ Invalid CSV received (message #{message_count}), skipping.")
                            continue

                        # CRITICAL: Determine which board this data is from
                        # The server publishes in order: board 0, 1, 2, ... n-1
                        board_id = str(message_count % NUM_BOARDS)
                        
                        phase = parsed_data["phase"]
                        
                        # Initialize deployment history for this board
                        if board_id not in deployment_history:
                            deployment_history[board_id] = {
                                "main_deployed": False,
                                "second_deployed": False
                            }
                            board_name = board_names.get(int(board_id), f"Board {board_id}")
                            print(f"✅ Tracking deployment for {board_name}")
                        
                        # Check for deployment events
                        if "MAIN" in phase and "DEPLOY" in phase:
                            if not deployment_history[board_id]["main_deployed"]:
                                deployment_history[board_id]["main_deployed"] = True
                                board_name = board_names.get(int(board_id), f"Board {board_id}")
                                print(f"🪂 {board_name}: Main parachute deployed!")
                        
                        if "SECOND" in phase and "DEPLOY" in phase:
                            if not deployment_history[board_id]["second_deployed"]:
                                deployment_history[board_id]["second_deployed"] = True
                                board_name = board_names.get(int(board_id), f"Board {board_id}")
                                print(f"🪂 {board_name}: Secondary parachute deployed!")
                        
                        # Update board status
                        board_statuses[board_id] = {
                            "name": board_names.get(int(board_id), f"Board {board_id}"),
                            "phase": phase,
                            "main_deployed": deployment_history[board_id]["main_deployed"],
                            "second_deployed": deployment_history[board_id]["second_deployed"],
                            "altitude": parsed_data["alt"],
                            "last_seen": time.time()
                        }
                        
                        api_status = "connected"
                        last_update = time.strftime("%H:%M:%S")
                        
                        # Log periodically
                        if message_count % (NUM_BOARDS * 20) == 0:
                            board_name = board_names.get(int(board_id), f"Board {board_id}")
                            print(
                                f"📥 {board_name}: "
                                f"Alt={parsed_data['alt']:.2f}m | "
                                f"Phase={phase} | "
                                f"Main={'✓' if deployment_history[board_id]['main_deployed'] else '✗'} | "
                                f"Second={'✓' if deployment_history[board_id]['second_deployed'] else '✗'}"
                            )

            except websockets.exceptions.InvalidStatusCode as e:
                print(f"❌ WebSocket connection rejected with status code: {e.status_code}")
                print(f"   Response headers: {e.headers}")
                retry_count += 1
                api_status = "error"
                if retry_count >= max_retries:
                    print("❌ Max retries reached. Please check:")
                    print("   1. Is the WebSocket server running?")
                    print("   2. Is the URL correct?")
                    print("   3. Try switching to 'api' or 'serial' mode in config.py")
                    return
                    
            except websockets.exceptions.InvalidURI as e:
                print(f"❌ Invalid WebSocket URI: {e}")
                print("   Check your WSS_ADDRESS in config.py")
                api_status = "error"
                return
                
            except Exception as e:
                print(f"❌ WebSocket connection error: {type(e).__name__}: {e}")
                retry_count += 1
                api_status = "error"
                
            wait_time = min(5 * retry_count, 30)
            print(f"⏳ Reconnecting in {wait_time} seconds...")
            await asyncio.sleep(wait_time)

    def run_loop():
        asyncio.run(ws_listener())

    print("🚀 Launching async WebSocket listener thread...")
    threading.Thread(target=run_loop, daemon=True).start()

    # Keep the main thread alive
    while True:
        time.sleep(60)

def fetch_deployment_status_api():
    """Fetch data from API and update board statuses"""
    global board_statuses, api_status, last_update, deployment_history, num_boards, board_names
    
    print("📡 Data fetcher running in API mode...")
    print(f"   Endpoint: {API_ADDRESS}/gcs/all")
    
    while True:
        try:
            response = requests.get(f"{API_ADDRESS}/gcs/all", timeout=5)
            if response.status_code == 200:
                data = response.json()
                new_statuses = {}
                
                # Update num_boards based on received data
                num_boards = len(data)
                
                for board_id, csv_string in data.items():
                    parsed_data = parse_csv_string(csv_string)
                    if parsed_data:
                        phase = parsed_data["phase"]
                        
                        if board_id not in deployment_history:
                            deployment_history[board_id] = {
                                "main_deployed": False,
                                "second_deployed": False
                            }
                        
                        if "MAIN" in phase and "DEPLOY" in phase:
                            if not deployment_history[board_id]["main_deployed"]:
                                deployment_history[board_id]["main_deployed"] = True
                                board_name = board_names.get(int(board_id), f"Board {board_id}")
                                print(f"🪂 {board_name}: Main parachute deployed!")
                        
                        if "SECOND" in phase and "DEPLOY" in phase:
                            if not deployment_history[board_id]["second_deployed"]:
                                deployment_history[board_id]["second_deployed"] = True
                                board_name = board_names.get(int(board_id), f"Board {board_id}")
                                print(f"🪂 {board_name}: Secondary parachute deployed!")
                        
                        new_statuses[board_id] = {
                            "name": board_names.get(int(board_id), f"Board {board_id}"),
                            "phase": phase,
                            "main_deployed": deployment_history[board_id]["main_deployed"],
                            "second_deployed": deployment_history[board_id]["second_deployed"],
                            "altitude": parsed_data["alt"],
                            "last_seen": time.time()
                        }
                
                board_statuses = new_statuses
                api_status = "connected"
                last_update = time.strftime("%H:%M:%S")
                
            else:
                api_status = "error"
                
        except Exception as e:
            print(f"Fetch error: {e}")
            api_status = "error"
        
        time.sleep(1)

def fetch_deployment_status_serial():
    """Fetch data from Serial port and update board statuses"""
    global board_statuses, api_status, last_update, deployment_history, num_boards, board_names
    
    num_boards = 1
    board_names = {0: "Serial Board"}
    
    print(f"📡 Attempting to connect to serial port {PORT} at {BAUDRATE} baud...")
    
    ser = None
    try:
        ser = serial.Serial(PORT, BAUDRATE, timeout=1)
        print(f"✅ Connected to serial port {PORT}")
    except serial.SerialException as e:
        print(f"❌ Could not open serial port {PORT}: {e}")
        return
    except Exception as e:
        print(f"❌ Unexpected error opening serial port: {e}")
        return

    print("📡 Serial data fetcher running...")
    
    line_count = 0
    error_count = 0
    
    while True:
        try:
            if not ser.is_open:
                print("⚠️ Serial port closed, attempting to reconnect...")
                try:
                    ser.open()
                    print("✅ Reconnected to serial port")
                except:
                    time.sleep(5)
                    continue
            
            line = ser.readline().decode("utf-8", errors='ignore').strip()
            
            if not line:
                continue
            
            line_count += 1
            
            if line_count <= 3:
                print(f"📥 Received line {line_count}: {line}")
            
            parsed_data = parse_csv_string(line)
            if not parsed_data:
                error_count += 1
                if error_count <= 5:
                    print(f"⚠️ Skipping invalid line {line_count}")
                continue

            error_count = 0
            
            board_id = "0"
            phase = parsed_data["phase"]
            
            if board_id not in deployment_history:
                deployment_history[board_id] = {
                    "main_deployed": False,
                    "second_deployed": False
                }
            
            if "MAIN" in phase and "DEPLOY" in phase:
                if not deployment_history[board_id]["main_deployed"]:
                    deployment_history[board_id]["main_deployed"] = True
                    print(f"🪂 Main parachute deployed!")
            
            if "SECOND" in phase and "DEPLOY" in phase:
                if not deployment_history[board_id]["second_deployed"]:
                    deployment_history[board_id]["second_deployed"] = True
                    print(f"🪂 Secondary parachute deployed!")
            
            board_statuses = {
                board_id: {
                    "name": board_names[int(board_id)],
                    "phase": phase,
                    "main_deployed": deployment_history[board_id]["main_deployed"],
                    "second_deployed": deployment_history[board_id]["second_deployed"],
                    "altitude": parsed_data["alt"],
                    "last_seen": time.time()
                }
            }
            
            api_status = "connected"
            last_update = time.strftime("%H:%M:%S")
            
            if line_count % 10 == 0:
                print(f"📊 Received {line_count} valid data points (Alt: {parsed_data['alt']:.1f}m, Phase: {phase})")

        except serial.SerialException as e:
            print(f"❌ Serial connection error: {e}")
            try:
                ser.close()
            except:
                pass
            time.sleep(5)
            try:
                ser = serial.Serial(PORT, BAUDRATE, timeout=1)
                print("✅ Reconnected to serial port")
            except Exception as reconnect_error:
                print(f"❌ Reconnection failed: {reconnect_error}")
                
        except UnicodeDecodeError as e:
            error_count += 1
            if error_count <= 3:
                print(f"⚠️ Unicode decode error: {e}")
            continue
            
        except Exception as e:
            print(f"❌ Serial fetcher error: {repr(e)}")
            traceback.print_exc()
            time.sleep(1)

def fetch_deployment_status():
    """Main fetcher that routes to appropriate mode"""
    if MODE == "serial":
        fetch_deployment_status_serial()
    elif MODE == "websocket":
        print("📡 Data fetcher running in WebSocket mode...")
        fetch_deployment_status_websocket()
    elif MODE == "api":
        fetch_deployment_status_api()
    else:
        print(f"⚠️ Unknown mode: {MODE}")

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
    """Generate dropdown options for board selection"""
    options = []
    for board_id in board_statuses.keys():
        name = board_statuses[board_id]["name"]
        options.append({"label": name, "value": board_id})
    return options

# App Layout
app.layout = html.Div([
    html.Div([
        html.Div([
            html.Div([
                html.Div([
                    html.H1("Deployment Status Monitor", style={
                        "fontSize": "36px",
                        "fontWeight": "bold",
                        "color": "white",
                        "margin": "0"
                    }),
                    html.P("Real-time deployment tracking", style={
                        "fontSize": "14px",
                        "color": "#9CA3AF",
                        "margin": "5px 0 0 0"
                    })
                ])
            ], style={
                "display": "flex",
                "alignItems": "center"
            }),
            html.Div([
                html.Div([
                    html.Div(id="api-status-indicator", style={
                        "width": "12px",
                        "height": "12px",
                        "borderRadius": "50%",
                        "backgroundColor": "#10B981"
                    }),
                    html.Span(id="api-status-text", children="Connecting...", style={
                        "fontSize": "14px",
                        "color": "#D1D5DB",
                        "marginLeft": "8px"
                    })
                ], style={
                    "display": "flex",
                    "alignItems": "center",
                    "justifyContent": "flex-end",
                    "marginBottom": "8px"
                }),
                html.P(id="last-update-text", children="Last update: --:--:--", style={
                    "fontSize": "12px",
                    "color": "#6B7280",
                    "margin": "0",
                    "textAlign": "right"
                })
            ], style={"textAlign": "right"})
        ], style={
            "display": "flex",
            "justifyContent": "space-between",
            "alignItems": "center"
        })
    ], style={
        "backgroundColor": "#1F2937",
        "padding": "30px",
        "borderRadius": "12px",
        "marginBottom": "30px",
        "border": "1px solid #374151"
    }),
    
    html.Div([
        html.Label("Select Board:", style={
            "color": "white",
            "fontSize": "18px",
            "fontWeight": "600",
            "marginBottom": "10px",
            "display": "block"
        }),
        dcc.Dropdown(
            id="board-selector",
            options=[],
            value=None,
            placeholder="Select a board to view...",
            clearable=False,
            style={
                "width": "100%",
                "maxWidth": "400px"
            }
        )
    ], style={
        "backgroundColor": "#1F2937",
        "padding": "20px 30px",
        "borderRadius": "12px",
        "marginBottom": "30px",
        "border": "1px solid #374151"
    }),
    
    html.Div(id="status-card-container", children=[]),
    
    html.Div([
        html.Div([
            html.P([
                html.Span("Data Source: ", style={"fontWeight": "600", "color": "white"}),
                html.Span(id="data-source-text", children="", style={"color": "#9CA3AF"})
            ], style={"margin": "0", "fontSize": "14px"}),
            html.P([
                html.Span("Active Boards: ", style={"fontWeight": "600", "color": "white"}),
                html.Span(id="active-boards-count", children="0", style={"color": "#9CA3AF"})
            ], style={"margin": "0", "fontSize": "14px"})
        ], style={
            "display": "flex",
            "justifyContent": "space-between"
        })
    ], style={
        "backgroundColor": "#1F2937",
        "padding": "20px",
        "borderRadius": "12px",
        "marginTop": "30px",
        "border": "1px solid #374151"
    }),
    
    dcc.Interval(id="interval-component", interval=1000, n_intervals=0)
    
], style={
    "minHeight": "100vh",
    "background": "linear-gradient(to bottom right, #111827, #1E3A8A, #111827)",
    "padding": "40px",
    "maxWidth": "1200px",
    "margin": "0 auto"
})

@app.callback(
    Output("board-selector", "options"),
    Output("board-selector", "value"),
    Output("data-source-text", "children"),
    Input("interval-component", "n_intervals"),
    Input("board-selector", "value")
)
def update_board_options(n, current_value):
    options = generate_board_options()
    
    if MODE == "serial":
        source_text = f"Serial Port {PORT} @ {BAUDRATE} baud"
    elif MODE == "websocket":
        source_text = f"WebSocket: {WSS_ADDRESS}/gcs/all"
    else:
        source_text = f"API: {API_ADDRESS}/gcs/all"
    
    if current_value is None and options:
        return options, options[0]["value"], source_text
    
    if current_value in [opt["value"] for opt in options]:
        return options, current_value, source_text
    
    if options:
        return options, options[0]["value"], source_text
    
    return options, None, source_text

@app.callback(
    Output("status-card-container", "children"),
    Output("api-status-indicator", "style"),
    Output("api-status-text", "children"),
    Output("last-update-text", "children"),
    Output("active-boards-count", "children"),
    Input("interval-component", "n_intervals"),
    Input("board-selector", "value")
)
def update_dashboard(n, selected_board):
    if api_status == "connected":
        status_color = "#10B981"
        if MODE == "serial":
            status_text = "Serial Connected"
        elif MODE == "websocket":
            status_text = "WebSocket Connected"
        else:
            status_text = "API Connected"
    else:
        status_color = "#EF4444"
        if MODE == "serial":
            status_text = "Serial Disconnected"
        elif MODE == "websocket":
            status_text = "WebSocket Disconnected"
        else:
            status_text = "API Disconnected"
    
    status_indicator_style = {
        "width": "12px",
        "height": "12px",
        "borderRadius": "50%",
        "backgroundColor": status_color
    }
    
    update_text = f"Last update: {last_update}" if last_update else "Last update: --:--:--"
    active_count = str(len(board_statuses))
    
    if not board_statuses:
        if api_status == "connected":
            card = html.Div([
                html.Div("⚠️", style={"fontSize": "64px", "marginBottom": "20px"}),
                html.H3("No Boards Detected", style={
                    "fontSize": "24px",
                    "fontWeight": "bold",
                    "color": "white",
                    "marginBottom": "10px"
                }),
                html.P("Waiting for board connections...", style={
                    "color": "#9CA3AF"
                })
            ], style={
                "textAlign": "center",
                "padding": "80px 20px",
                "color": "white"
            })
        else:
            if MODE == "serial":
                error_msg = f"Cannot connect to serial port {PORT}"
                hint_msg = "Make sure the device is connected"
            elif MODE == "websocket":
                error_msg = f"Cannot connect to WebSocket server at {WSS_ADDRESS}"
                hint_msg = "Make sure the WebSocket server is running"
            else:
                error_msg = f"Cannot connect to API server at {API_ADDRESS}"
                hint_msg = "Make sure the API server is running"
                
            card = html.Div([
                html.Div("❌", style={"fontSize": "64px", "marginBottom": "20px"}),
                html.H3("Connection Error", style={
                    "fontSize": "24px",
                    "fontWeight": "bold",
                    "color": "white",
                    "marginBottom": "10px"
                }),
                html.P(error_msg, style={
                    "color": "#9CA3AF",
                    "marginBottom": "5px"
                }),
                html.P(hint_msg, style={
                    "fontSize": "12px",
                    "color": "#6B7280"
                })
            ], style={
                "textAlign": "center",
                "padding": "80px 20px",
                "color": "white"
            })
    elif selected_board is None:
        card = html.Div([
            html.Div("👆", style={"fontSize": "64px", "marginBottom": "20px"}),
            html.H3("Select a Board", style={
                "fontSize": "24px",
                "fontWeight": "bold",
                "color": "white",
                "marginBottom": "10px"
            }),
        ], style={
            "textAlign": "center",
            "padding": "80px 20px",
            "color": "white"
        })
    elif selected_board in board_statuses:
        card = create_status_card(selected_board, board_statuses[selected_board])
    else:
        card = html.Div([
            html.P("Board not found", style={"color": "white", "textAlign": "center"})
        ])
    
    return card, status_indicator_style, status_text, update_text, active_count

def create_status_card(board_id, status):
    phase_color = get_phase_color(status["phase"])
    
    return html.Div([
        html.Div([
            html.Div([
                html.H2(status["name"], style={
                    "fontSize": "32px",
                    "fontWeight": "bold",
                    "color": "white",
                    "margin": "0"
                }),
                html.Span(status["phase"], style={
                    "fontSize": "18px",
                    "fontWeight": "600",
                    "color": "white",
                    "backgroundColor": "rgba(0,0,0,0.3)",
                    "padding": "8px 20px",
                    "borderRadius": "12px"
                })
            ], style={
                "display": "flex",
                "justifyContent": "space-between",
                "alignItems": "center"
            })
        ], style={
            "backgroundColor": phase_color,
            "padding": "30px 40px"
        }),
        
        html.Div([
            html.Div([
                html.Div([
                    html.Div([
                        html.Span("✓" if status["main_deployed"] else "⏳", style={
                            "fontSize": "64px",
                            "color": "#4ADE80" if status["main_deployed"] else "#FBBF24"
                        }),
                        html.Div([
                            html.P("Main Deployment", style={
                                "color": "white",
                                "fontWeight": "700",
                                "margin": "0",
                                "fontSize": "36px"
                            }),
                            html.P("Primary deployment system", style={
                                "color": "#9CA3AF",
                                "margin": "5px 0 0 0",
                                "fontSize": "18px"
                            })
                        ], style={"marginLeft": "30px"})
                    ], style={"display": "flex", "alignItems": "center"}),
                    html.Span(
                        "DEPLOYED" if status["main_deployed"] else "STANDBY",
                        style={
                            "fontSize": "20px",
                            "fontWeight": "700",
                            "color": "white",
                            "backgroundColor": "#16A34A" if status["main_deployed"] else "#CA8A04",
                            "padding": "12px 30px",
                            "borderRadius": "12px"
                        }
                    )
                ], style={
                    "display": "flex",
                    "justifyContent": "space-between",
                    "alignItems": "center"
                })
            ], style={
                "backgroundColor": "#111827",
                "padding": "40px",
                "borderRadius": "12px",
                "border": "2px solid #374151",
                "marginBottom": "24px"
            }),
            
            html.Div([
                html.Div([
                    html.Div([
                        html.Span("✓" if status["second_deployed"] else "⏳", style={
                            "fontSize": "64px",
                            "color": "#4ADE80" if status["second_deployed"] else "#FBBF24"
                        }),
                        html.Div([
                            html.P("Second Deployment", style={
                                "color": "white",
                                "fontWeight": "700",
                                "margin": "0",
                                "fontSize": "36px"
                            }),
                            html.P("Secondary deployment system", style={
                                "color": "#9CA3AF",
                                "margin": "5px 0 0 0",
                                "fontSize": "18px"
                            })
                        ], style={"marginLeft": "30px"})
                    ], style={"display": "flex", "alignItems": "center"}),
                    html.Span(
                        "DEPLOYED" if status["second_deployed"] else "STANDBY",
                        style={
                            "fontSize": "20px",
                            "fontWeight": "700",
                            "color": "white",
                            "backgroundColor": "#16A34A" if status["second_deployed"] else "#CA8A04",
                            "padding": "12px 30px",
                            "borderRadius": "12px"
                        }
                    )
                ], style={
                    "display": "flex",
                    "justifyContent": "space-between",
                    "alignItems": "center"
                })
            ], style={
                "backgroundColor": "#111827",
                "padding": "40px",
                "borderRadius": "12px",
                "border": "2px solid #374151"
            })
        ], style={"padding": "40px"})
    ], style={
        "backgroundColor": "#1F2937",
        "borderRadius": "12px",
        "overflow": "hidden",
        "border": "1px solid #374151",
        "transition": "all 0.3s",
    })

if __name__ == "__main__":
    print("="*60)
    print("Starting Deployment Status Dashboard...")
    print("="*60)
    print(f"Mode: {MODE.upper()}")
    if MODE == "serial":
        print(f"Serial Port: {PORT}")
        print(f"Baud Rate: {BAUDRATE}")
    elif MODE == "websocket":
        print(f"WebSocket Endpoint: {WSS_ADDRESS}/gcs/all")
        print(f"Expected Boards: {NUM_BOARDS}")
    else:
        print(f"API Endpoints:")
        print(f"  - {API_ADDRESS}/gcs/all")
        print(f"  - {API_ADDRESS}/gcs/<device_id>")
    print(f"Dashboard: http://local:3000")
    print("="*60)
    
    threading.Thread(target=fetch_deployment_status, daemon=True).start()
    
    app.run(debug=True, host='localhost', port='3000', use_reloader=False)
