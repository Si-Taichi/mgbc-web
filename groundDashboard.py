from dash import Dash, dcc, html, Input, Output, dash_table
import plotly.graph_objects as go
import requests
import threading
import time
import random
import traceback
import math
import serial
from config import NUM_BOARDS, MODE, PORT, BAUDRATE, DASHBOARD_UPDATE_INTERVAL, API_HOST, API_PORT, DASH_HOST, DASH_PORT

app = Dash(__name__, update_title=None, title='kits board UGCS')

def init_board_data():
    return {
        "x": [], "y": [], "z": [],
        "lat": [], "lon": [],
        "Tempurature": [], "Pressure": [], "Humidity": [],
        "speed": [], "alt": [],
        "phase": [],
        "time": [],
        "main_deploy": False,  # Track main deploy event
        "second_deploy": False  # Track second deploy event
    }

all_board = []
board_list = {}
start_time = time.time()
num_boards = NUM_BOARDS  # Will be updated dynamically from API
board_names = {}  # Will be populated from API
prediction_memory = {}  # Store predictions: {board_id: predicted_apogee_value}

def latlon_to_xy(lat0, lon0, lat, lon):
    """Convert lat/lon to local x,y in meters relative to lat0,lon0"""
    R = 6371000.0  # Earth radius in meters
    dlat = math.radians(lat - lat0)
    dlon = math.radians(lon - lon0)
    x = dlon * R * math.cos(math.radians((lat + lat0) / 2.0))
    y = dlat * R
    return x, y

def elapsed_seconds():
    return time.time() - start_time

def parse_csv_string(csv_string):
    """
    Parse CSV string with proper type conversion
    Expected format: x,y,z,lat,lon,temp,pressure,humidity,speed,alt,phase
    """
    try:
        parts = csv_string.strip().split(",")

        if parts[0].lower() == "accel_x":
            return None
        
        if len(parts) != 11:
            print(f"❌ Invalid CSV format: expected 11 parts, got {len(parts)}")
            print(f"   Raw data: {csv_string}")
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
            speed = float(parts[8].strip())
            alt = float(parts[9].strip())
            phase = parts[10].strip()  # Keep as string, don't convert to float
            
            return {
                "LIS331DLH axis x": [x],
                "LIS331DLH axis y": [y],
                "LIS331DLH axis z": [z],
                "lc86g lat": [lat],
                "lc86g lon": [lon],
                "bme tempurature": [temp],
                "bme pressure": [pressure],
                "bme humidity": [humidity],
                "lc86g speed": [speed],
                "lc86g alt": [alt],
                "phase": [phase]
            }
        except ValueError as e:
            print(f"❌ Value conversion error: {e}")
            print(f"   Parts: {parts}")
            return None
            
    except Exception as e:
        print(f"❌ Parse error: {e}")
        print(f"   Raw input: {csv_string}")
        return None

def get_api_config():
    """Get configuration from API server"""
    global num_boards, board_names
    try:
        r = requests.get(f"http://{API_HOST}:{API_PORT}/status", timeout=5)
        if r.status_code == 200:
            data = r.json()
            num_boards = data.get("configured_boards", 6)
            board_names = data.get("board_names", {})
            print(f"✅ Retrieved API config: {num_boards} boards")
            return True
    except Exception as e:
        print(f"⚠️ Could not get API config: {e}, using defaults")
        num_boards = 6
        board_names = {str(i): f"Board {i}" for i in range(num_boards)}
    return False

def data_fetcher_serial():
    """
    Separate function for serial mode to avoid double connection
    """
    global all_board, board_list, num_boards, board_names
    
    num_boards = 1
    board_names = {"0": "Serial Board"}
    
    print(f"📡 Attempting to connect to serial port {PORT} at {BAUDRATE} baud...")
    
    ser = None
    try:
        ser = serial.Serial(PORT, BAUDRATE, timeout=1)
        print(f"✅ Connected to serial port {PORT}")
    except serial.SerialException as e:
        print(f"❌ Could not open serial port {PORT}: {e}")
        print(f"   Make sure:")
        print(f"   - The device is plugged in")
        print(f"   - No other program is using the port")
        print(f"   - You have permission to access the port")
        return
    except Exception as e:
        print(f"❌ Unexpected error opening serial port: {e}")
        return

    print("📡 Serial data fetcher running...")
    print("   Waiting for data...")
    
    line_count = 0
    error_count = 0
    
    while True:
        try:
            # Check if serial port is still open
            if not ser.is_open:
                print("⚠️ Serial port closed, attempting to reconnect...")
                try:
                    ser.open()
                    print("✅ Reconnected to serial port")
                except:
                    time.sleep(5)
                    continue
            
            # Read line from serial
            line = ser.readline().decode("utf-8", errors='ignore').strip()
            
            if not line:
                continue
            
            line_count += 1
            
            # Debug: print first few lines
            if line_count <= 3:
                print(f"📥 Received line {line_count}: {line}")
            
            # Parse the CSV string
            v = parse_csv_string(line)
            if not v:
                error_count += 1
                if error_count <= 5:  # Only print first 5 errors
                    print(f"⚠️ Skipping invalid line {line_count}")
                continue

            # Reset error count on successful parse
            error_count = 0
            
            # Update board data
            all_board = [v]
            board_id = "0"

            if board_id not in board_list:
                board_list[board_id] = init_board_data()
                print(f"✅ Initialized data storage for board {board_id}")

            board_list[board_id]["x"].append(v["LIS331DLH axis x"][0])
            board_list[board_id]["y"].append(v["LIS331DLH axis y"][0])
            board_list[board_id]["z"].append(v["LIS331DLH axis z"][0])
            board_list[board_id]["lat"].append(v["lc86g lat"][0])
            board_list[board_id]["lon"].append(v["lc86g lon"][0])
            board_list[board_id]["Tempurature"].append(v["bme tempurature"][0])
            board_list[board_id]["Pressure"].append(v["bme pressure"][0])
            board_list[board_id]["Humidity"].append(v["bme humidity"][0])
            board_list[board_id]["speed"].append(v["lc86g speed"][0])
            board_list[board_id]["alt"].append(v["lc86g alt"][0])
            
            # Handle phase and deploy detection
            phase_raw = v["phase"][0].upper()
            
            # Detect deploy events
            if "MAIN" in phase_raw and "DEPLOY" in phase_raw:
                board_list[board_id]["main_deploy"] = True
                display_phase = "DESCENT"
            elif "SECOND" in phase_raw and "DEPLOY" in phase_raw:
                board_list[board_id]["second_deploy"] = True
                display_phase = "DESCENT"
            else:
                display_phase = phase_raw
            
            board_list[board_id]["phase"].append(display_phase)
            board_list[board_id]["time"].append(elapsed_seconds())
            
            # Periodic status update
            if line_count % 10 == 0:
                print(f"📊 Received {line_count} valid data points (Alt: {v['lc86g alt'][0]:.1f}m, Phase: {display_phase})")

        except serial.SerialException as e:
            print(f"❌ Serial connection error: {e}")
            print("   Attempting to reconnect in 5 seconds...")
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

def data_fetcher_all(mode):
    """
    Main data fetcher that routes to appropriate mode
    """
    global all_board, board_list, num_boards, board_names
    
    if mode == "serial":
        data_fetcher_serial()
        
    elif mode == "api":
        get_api_config()
        print("📡 Data fetcher running in API mode...")

        while True:
            try:
                url = f"http://{API_HOST}:{API_PORT}/gcs/all"
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    
                    # Update num_boards based on actual data received
                    received_boards = len(data)
                    if received_boards != num_boards:
                        print(f"📊 Board count updated: {num_boards} → {received_boards}")
                        num_boards = received_boards
                    
                    print(f"✅ API Success: Received data for {received_boards} devices {list(data.keys())}")
                else:
                    print(f"❌ API error: {r.status_code}")
                    time.sleep(2)
                    continue

                # Process data
                all_board = []
                for board_id, csv_string in data.items():
                    v = parse_csv_string(csv_string)
                    if not v:
                        continue
                    all_board.append(v)

                    if board_id not in board_list:
                        board_list[board_id] = init_board_data()

                    board_list[board_id]["x"].append(v["LIS331DLH axis x"][0])
                    board_list[board_id]["y"].append(v["LIS331DLH axis y"][0])
                    board_list[board_id]["z"].append(v["LIS331DLH axis z"][0])
                    board_list[board_id]["lat"].append(v["lc86g lat"][0])
                    board_list[board_id]["lon"].append(v["lc86g lon"][0])
                    board_list[board_id]["Tempurature"].append(v["bme tempurature"][0])
                    board_list[board_id]["Pressure"].append(v["bme pressure"][0])
                    board_list[board_id]["Humidity"].append(v["bme humidity"][0])
                    board_list[board_id]["speed"].append(v["lc86g speed"][0])
                    board_list[board_id]["alt"].append(v["lc86g alt"][0])
                    
                    # Handle phase and deploy detection
                    phase_raw = v["phase"][0].upper()
                    
                    # Detect deploy events
                    if "MAIN" in phase_raw and "DEPLOY" in phase_raw:
                        board_list[board_id]["main_deploy"] = True
                        display_phase = "DESCENT"
                    elif "SECOND" in phase_raw and "DEPLOY" in phase_raw:
                        board_list[board_id]["second_deploy"] = True
                        display_phase = "DESCENT"
                    else:
                        display_phase = phase_raw
                    
                    board_list[board_id]["phase"].append(display_phase)
                    board_list[board_id]["time"].append(elapsed_seconds())

            except Exception as e:
                print(f"❌ Fetcher crashed: {repr(e)}")
                traceback.print_exc()

            time.sleep(1)
    
    else:
        print(f"⚠️ Unknown mode: {mode}")
        print(f"   Valid modes are: 'api' or 'serial'")
def clamp_lat_lon(lat, lon):
    # keep values inside valid ranges
    lat = max(min(lat, 90.0), -90.0)
    lon = ((lon + 180.0) % 360.0) - 180.0
    return lat, lon

def generate_board_options():
    """Generate board options dynamically"""
    options = []
    for i in range(num_boards):
        board_name = board_names.get(str(i), f"Board {i}")
        options.append({"label": board_name, "value": str(i)})
    return options


# Create figures
fig2d = go.Figure()
fig2d.update_layout(title="Temperature, Pressure, Humidity",
                    xaxis_title="Reading #", yaxis_title="Value")

fig_speed = go.Figure()
fig_speed.update_layout(title="Speed Over Time",
                       xaxis_title="Time (seconds)", yaxis_title="Speed (m/s)")

fig_alt = go.Figure()
fig_alt.update_layout(title="Altitude Over Time",
                     xaxis_title="Time (seconds)", yaxis_title="Altitude (m)")

fig_accel = go.Figure()
fig_accel.update_layout(title="Accelerometer Data (LIS331DLH)",
                       xaxis_title="Time (seconds)", yaxis_title="Acceleration (g)")

fig3d = go.Figure()
figgeo = go.Figure()

fig3d.update_layout(scene=dict(aspectmode="auto",bgcolor="#102c55"),
                    margin=dict(l=0, r=0, t=30, b=0),
                    title="Rocket 3D Trajectory")

figgeo.update_layout(
    geo=dict(projection=dict(type="orthographic")),
    title="Latitude Longitude Position")

# Layout with dynamic board count
app.layout = html.Div([
    # Logo
    html.Div([
        html.Img(src="/assets/wangchan_logo.png", style={"height": "80px", "margin": "10px"}),
        html.Img(src="/assets/intel_logo.png", style={"height": "70px", "margin": "10px"}),
        html.Img(src="/assets/space_ac_logo.png", style={"height": "80px", "margin": "10px"}),
        html.Img(src="/assets/school_logo.png", style={"height": "80px", "margin": "10px"}),
        html.Img(src="/assets/dti_logo.png", style={"height": "80px", "margin": "10px"}),
        html.Img(src="/assets/kmutt_logo.png", style={"height": "80px", "margin": "10px"}),
    ], style={
        "display": "flex", 
        "justifyContent": "center", 
        "alignItems": "center",
        "backgroundColor": "#0a1929",
        "padding": "15px",
        "flexWrap": "wrap",
        "gap": "20px"
    }),
    html.H1("Multi Ground Board Connection - Website", style={"textAlign": "center", "color" : "white"}),
    
    # API Status indicator
    html.Div([
        html.P("📡 API Mode: Receiving data from http://localhost:5000/gcs/all", 
               style={"color": "lime", "textAlign": "center", "fontSize": "14px", "margin": "10px"}),
        html.P("Make sure the API server is running!", 
               style={"color": "yellow", "textAlign": "center", "fontSize": "12px", "margin": "5px"}),
        html.P(id="board-count-display", children="Loading board configuration...",
               style={"color": "cyan", "textAlign": "center", "fontSize": "12px", "margin": "5px"}),
    ]),
    
    # Control Panel Row
    html.Div([
        html.Div([
            html.Label("Select board to view", style={"color" : "white"}),
            dcc.Dropdown(
                id="board-select",
                options=[],  # Will be populated dynamically
                value="0",
                clearable=False,
                style={"width": "200px"}
            )
        ], style={"padding" : "20px", "flex": "1"}),
        
        html.Div([
            html.Label("Select BME Metric:", style={"color" : "white"}),
            dcc.Dropdown(
                id="bme-dropdown",
                options=[
                    {"label": "Temperature", "value": "Tempurature"},
                    {"label": "Pressure", "value": "Pressure"},
                    {"label": "Humidity", "value": "Humidity"}
                ],
                value="Tempurature", clearable=False,
                style={"width": "200px"}
            ),
        ], style={"padding" : "20px", "flex": "1"}),
        
        # Apogee Prediction Input with memory
        html.Div([
            html.Label("Predicted Apogee (m):", style={"color": "white"}),
            dcc.Input(
                id="predicted-apogee-input",
                type="number",
                value=1000,
                placeholder="Enter predicted apogee",
                style={"width": "150px", "margin": "5px"}
            ),
            html.Label("Board for prediction:", style={"color": "white", "marginTop": "10px"}),
            dcc.Dropdown(
                id="prediction-board-select",
                options=[],  # Will be populated dynamically
                value="0",
                clearable=False,
                style={"width": "150px"}
            ),
            html.Button("Save Prediction", id="save-prediction-btn", 
                       style={"backgroundColor": "#4CAF50", "color": "white", "border": "none", 
                             "padding": "8px 16px", "marginTop": "10px", "borderRadius": "4px"}),
            html.Div(id="prediction-status", style={"color": "lime", "fontSize": "12px", "marginTop": "5px"})
        ], style={"padding": "20px", "flex": "1"}),
    ], style={"display": "flex", "gap": "20px"}),

    # Status Board with phase display and deploy status
    html.Div([
        html.H2("Flight Status Board", style={"textAlign": "center", "color": "white"}),
        dash_table.DataTable(
            id="status-board",
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
                {"name": "Score (20)", "id": "score"},
            ],
            style_table={"overflowX": "auto"},
            style_header={
                "backgroundColor": "#1c3c6e",
                "color": "white",
                "fontWeight": "bold",
                "textAlign": "center"
            },
            style_cell={
                "backgroundColor": "#102c55",
                "color": "white",
                "textAlign": "center",
                "padding": "12px"
            },
            style_data_conditional=[
                {
                    'if': {'filter_query': '{phase} = DESCENT'},
                    'backgroundColor': '#0e4b99',
                    'color': 'white',
                },
                {
                    'if': {'filter_query': '{phase} = COASTING'},
                    'backgroundColor': '#8B0000',
                    'color': 'yellow',
                },
                {
                    'if': {'filter_query': '{phase} = RISING'},
                    'backgroundColor': '#FF4500',
                    'color': 'white',
                },
                {
                    'if': {'filter_query': '{main_deploy} = "✅ DEPLOYED"'},
                    'color': 'lime',
                },
                {
                    'if': {'filter_query': '{second_deploy} = "✅ DEPLOYED"'},
                    'color': 'lime',
                }
            ]
        )
    ], style={"padding" : "15px"}),

    # Row 1: BME + Accelerometer
    html.Div([
        dcc.Graph(id="2d-bmestats", figure=fig2d,
                  style={"height": "350px", "flex": "1", "borderRadius": "1px solid gray", 
                         "padding": "10px", "boxShadow": "0 4px 10px rgba(0,0,0,0.1)"}),
        dcc.Graph(id="accelerometer-chart", figure=fig_accel,
                  style={"height": "350px", "flex": "1", "borderRadius": "1px solid gray", 
                         "padding": "10px", "boxShadow": "0 4px 10px rgba(0,0,0,0.1)"}),
    ], style={"display": "flex", "gap": "20px", "marginBottom": "20px"}),

    # Row 2: Speed + Altitude (separate graphs)
    html.Div([
        dcc.Graph(id="speed-chart", figure=fig_speed,
                  style={"height": "350px", "flex": "1", "borderRadius": "1px solid gray", 
                         "padding": "10px", "boxShadow": "0 4px 10px rgba(0,0,0,0.1)"}),
        dcc.Graph(id="altitude-chart", figure=fig_alt,
                  style={"height": "350px", "flex": "1", "borderRadius": "1px solid gray", 
                         "padding": "10px", "boxShadow": "0 4px 10px rgba(0,0,0,0.1)"}),
    ], style={"display": "flex", "gap": "20px", "marginBottom": "20px"}),

    # Row 3: 3D Trajectory + Globe
    html.Div([
        dcc.Graph(id="3d-trajectory", figure=fig3d,
                  style={"height": "400px", "flex": "1", "borderRadius": "1px solid gray", 
                         "padding": "10px", "boxShadow": "0 4px 10px rgba(0,0,0,0.1)"}),
        dcc.Graph(id="globe-latlon", figure=figgeo,
                  style={"height": "400px", "flex": "1", "borderRadius": "1px solid gray", 
                         "padding": "10px", "boxShadow": "0 4px 10px rgba(0,0,0,0.1)"}),
    ], style={"display": "flex", "gap": "10px"}),

    # Hidden div to store prediction memory
    html.Div(id="prediction-memory-store", style={"display": "none"}),
    
    dcc.Interval(id="interval", interval=DASHBOARD_UPDATE_INTERVAL, n_intervals=0)
])

# Callback to save predictions
@app.callback(
    Output("prediction-status", "children"),
    Output("prediction-memory-store", "children"),
    Input("save-prediction-btn", "n_clicks"),
    Input("predicted-apogee-input", "value"),
    Input("prediction-board-select", "value"),
    prevent_initial_call=True
)
def save_prediction(n_clicks, predicted_apogee, board_id):
    global prediction_memory
    if n_clicks and predicted_apogee and board_id is not None:
        prediction_memory[board_id] = predicted_apogee
        board_name = board_names.get(board_id, f"Board {board_id}")
        status_msg = f"Saved prediction: {predicted_apogee}m for {board_name}"
        return status_msg, str(prediction_memory)
    return "", str(prediction_memory)

# Callback to update dropdown options dynamically
@app.callback(
    Output("board-select", "options"),
    Output("prediction-board-select", "options"),
    Output("board-count-display", "children"),
    Input("interval", "n_intervals")
)
def update_board_options(n):
    options = generate_board_options()
    count_msg = f"System: {num_boards} boards configured and active"
    return options, options, count_msg

@app.callback(
    Output("2d-bmestats", "figure"),
    Output("accelerometer-chart", "figure"),
    Output("speed-chart", "figure"),
    Output("altitude-chart", "figure"),
    Output("3d-trajectory", "figure"),
    Output("globe-latlon", "figure"),
    Output("status-board", "data"),
    Input("interval", "n_intervals"),
    Input("board-select", "value"),
    Input("bme-dropdown", "value"),
    Input("predicted-apogee-input", "value"),
    Input("prediction-board-select", "value")
)

def update_charts(n, selected_board, selected_metric, predicted_apogee, prediction_board):
    if selected_board not in board_list or len(board_list[selected_board]["x"]) == 0:
        return go.Figure(), go.Figure(), go.Figure(), go.Figure(), go.Figure(), go.Figure(), []

    board_data = board_list[selected_board]

    # Status Board Data with phase system and deploy status
    status_rows = []
    for bid, bdata in board_list.items():
        if not bdata["alt"] or not bdata["phase"]:
            continue

        current_alt = bdata["alt"][-1]
        max_alt = max(bdata["alt"])
        current_phase = bdata["phase"][-1]
        
        # Deploy status
        main_deploy_status = "✅ DEPLOYED" if bdata["main_deploy"] else "⏳ Waiting"
        second_deploy_status = "✅ DEPLOYED" if bdata["second_deploy"] else "⏳ Waiting"
        
        # Get stored prediction for this board
        stored_prediction = prediction_memory.get(bid, None)
        predicted_display = f"{stored_prediction}m" if stored_prediction else "Not set"
        
        # Calculate prediction difference
        apogee_diff = "N/A"
        if stored_prediction:
            try:
                diff = max_alt - float(stored_prediction)
                apogee_diff = f"{diff:+.1f}m"
                if abs(diff) < 50:
                    apogee_diff = f"{apogee_diff} ✓"
                elif diff > 0:
                    apogee_diff = f"{apogee_diff} ↑"
                else:
                    apogee_diff = f"{apogee_diff} ↓"
            except:
                apogee_diff = "Error"
        # --- Distance calculation ---
        distance_m = "N/A"
        if bdata["lat"] and bdata["lon"]:
            lat0, lon0 = bdata["lat"][0], bdata["lon"][0]  # launch
            lat_end, lon_end = bdata["lat"][-1], bdata["lon"][-1]  # landing
            dx, dy = latlon_to_xy(lat0, lon0, lat_end, lon_end)
            dist_val = math.sqrt(dx**2 + dy**2)
            distance_m = f"{dist_val:.1f}"

        # --- Scoring system ---
        apogee_score = 0
        distance_score = 0

        # Apogee score based on % error ranges
        if stored_prediction:
            try:
                error_pct = abs(max_alt - float(stored_prediction)) / float(stored_prediction) * 100
                if error_pct < 2: apogee_score = 10
                elif error_pct < 5: apogee_score = 9
                elif error_pct < 10: apogee_score = 8
                elif error_pct < 15: apogee_score = 7
                elif error_pct < 20: apogee_score = 6
                elif error_pct < 25: apogee_score = 5
                elif error_pct < 30: apogee_score = 4
                elif error_pct < 40: apogee_score = 3
                elif error_pct < 50: apogee_score = 2
                else: apogee_score = 1
            except:
                pass

        # Distance score: max apogee/2 is cutoff, linear scale
        if isinstance(distance_m, str) and distance_m != "N/A":
            try:
                dist_val = float(distance_m)
                max_dist = max_alt / 2 if max_alt > 0 else 1
                score_ratio = max(0, 1 - dist_val / max_dist)  # closer → higher
                distance_score = round(score_ratio * 10, 1)
            except:
                pass

        total_score = apogee_score + distance_score
        board_name = board_names.get(bid, f"Board {bid}")
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
            "score": f"{apogee_score:.1f} + {distance_score:.1f} = {total_score:.1f}"
        })

    # BME Chart
    fig2d = go.Figure(go.Scatter(
        y=board_data[selected_metric],
        x=board_data["time"],
        mode="lines+markers",
        line=dict(color="brown")
    ))
    unit = {"Tempurature": " (C)", "Pressure": " (Pa)", "Humidity": " (%)"}
    selected_board_name = board_names.get(selected_board, f"Board {selected_board}")
    fig2d.update_layout(
        title=f"{selected_metric} Over Time ({selected_board_name})",
        xaxis_title="Time (seconds)",
        yaxis_title=selected_metric + unit.get(selected_metric, ""),
        plot_bgcolor="#102c55", paper_bgcolor="#102c55", font=dict(color="white")
    )

    # Accelerometer Chart
    fig_accel = go.Figure()
    fig_accel.add_trace(go.Scatter(
        y=board_data["x"],
        x=board_data["time"],
        mode="lines+markers",
        name="X-axis",
        line=dict(color="red")
    ))
    fig_accel.add_trace(go.Scatter(
        y=board_data["y"],
        x=board_data["time"],
        mode="lines+markers",
        name="Y-axis",
        line=dict(color="green")
    ))
    fig_accel.add_trace(go.Scatter(
        y=board_data["z"],
        x=board_data["time"],
        mode="lines+markers",
        name="Z-axis",
        line=dict(color="blue")
    ))
    fig_accel.update_layout(
        title=f"Accelerometer Data ({selected_board_name})",
        xaxis_title="Time (seconds)",
        yaxis_title="Acceleration (g)",
        plot_bgcolor="#102c55", paper_bgcolor="#102c55", font=dict(color="white")
    )

    # Speed Chart
    fig_speed = go.Figure(go.Scatter(
        y=board_data["speed"],
        x=board_data["time"],
        mode="lines+markers",
        name="Speed",
        line=dict(color="orange")
    ))
    fig_speed.update_layout(
        title=f"Speed Over Time ({selected_board_name})",
        xaxis_title="Time (seconds)",
        yaxis_title="Speed (m/s)",
        plot_bgcolor="#102c55", paper_bgcolor="#102c55", font=dict(color="white")
    )

    # Altitude Chart with all saved prediction lines
    fig_alt = go.Figure()
    fig_alt.add_trace(go.Scatter(
        y=board_data["alt"],
        x=board_data["time"],
        mode="lines+markers",
        name="Altitude",
        line=dict(color="cyan", width=3)
    ))
    
    # Add prediction line for the selected board if it has a saved prediction
    stored_prediction = prediction_memory.get(selected_board, None)
    if stored_prediction:
        try:
            max_time = max(board_data["time"]) if board_data["time"] else 100
            fig_alt.add_hline(
                y=float(stored_prediction), 
                line_dash="dash", 
                line_color="yellow",
                line_width=2,
                annotation_text=f"Predicted: {stored_prediction}m"
            )
        except:
            pass
    
    # Add current input prediction line if different from stored
    if predicted_apogee and prediction_board == selected_board:
        if not stored_prediction or float(predicted_apogee) != stored_prediction:
            try:
                fig_alt.add_hline(
                    y=float(predicted_apogee), 
                    line_dash="dot", 
                    line_color="orange",
                    line_width=1,
                    annotation_text=f"Current Input: {predicted_apogee}m"
                )
            except:
                pass
    
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

    fig3d = go.Figure(go.Scatter3d(
        x=xs, y=ys, z=zs,
        mode="lines+markers",
        name=selected_board_name,
        line=dict(color="blue"),
        marker=dict(size=4, color="red")
    ))
    fig3d.update_layout(
        scene=dict(
            xaxis_title="East-West (m)",
            yaxis_title="North-South (m)",
            zaxis_title="Altitude (m)",
            aspectmode="auto",
            bgcolor="#102c55"
        ),
        margin=dict(l=0, r=0, t=80, b=0),
        title=f"Rocket 3D Trajectory ({selected_board_name})",
        paper_bgcolor="#102c55",
        font=dict(color="white")
    )

    # Globe View - show all boards
    figgeo = go.Figure()
    for bid, bdata in board_list.items():
        if len(bdata["lat"]) > 1 and bid != selected_board:
            board_name = board_names.get(bid, f"Board {bid}")
            figgeo.add_trace(go.Scattergeo(
                lon=bdata["lon"],
                lat=bdata["lat"],
                mode="lines+markers",
                name=board_name,
                line=dict(width=1),
                marker=dict(size=4),
                opacity=0.6
            ))

    figgeo.add_trace(go.Scattergeo(
        lon=board_data["lon"],
        lat=board_data["lat"],
        mode="lines+markers",
        name=f"{selected_board_name} (selected)",
        line=dict(width=3),
        marker=dict(size=7)
    ))
    
    if board_data["lat"] and board_data["lon"]:
        last_lat = board_data["lat"][-1]
        last_lon = board_data["lon"][-1]
        figgeo.update_geos(
            projection_type="orthographic",
            projection_rotation=dict(lat=last_lat, lon=last_lon),
            showland=True, landcolor="lightgray",
            showcountries=True,
            showocean=True, oceancolor="lightblue"
        )
    
    figgeo.update_layout(
        title="Latitude Longitude Position", 
        uirevision="stay",
        paper_bgcolor="#102c55",
        font=dict(color="white")   
    )

    return fig2d, fig_accel, fig_speed, fig_alt, fig3d, figgeo, status_rows

if __name__ == "__main__":

    print("Starting Groundboard Dashboard...")
    if MODE == "api":
        print(f"Dashboard will connect to API server at: http://{API_HOST}:{API_PORT}/gcs/all")
    else:
        print(f"Dashboard will read from SERIAL port {PORT} at {BAUDRATE} baud")

    threading.Thread(target=data_fetcher_all, kwargs={"mode": MODE}, daemon=True).start()

    print(f"Dashboard available at: http://{DASH_HOST}:{DASH_PORT}")
    print("="*60)
    app.run(debug=True, port=DASH_PORT)
