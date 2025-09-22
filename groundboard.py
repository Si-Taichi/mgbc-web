from dash import Dash, dcc, html, Input, Output, dash_table
import plotly.graph_objects as go
import requests
import threading
import time
import random
import traceback
import math

app = Dash(__name__, update_title=None, title='kits board UGCS')

def init_board_data():
    return {
        "x": [], "y": [], "z": [],
        "lat": [], "lon": [],
        "Tempurature": [], "Pressure": [], "Humidity": [],
        "speed" : [], "alt" : [],
        "time" : []
    }

all_board = []
board_list = {}
start_time = time.time()

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
    parts = csv_string.strip().split(",")
    if len(parts) != 10:
        print("amount of data not equal to 10")
        return None
    return {
        "LIS331DLH axis x": [float(parts[0])],
        "LIS331DLH axis y": [float(parts[1])],
        "LIS331DLH axis z": [float(parts[2])],
        "lc86g lat": [float(parts[3])],
        "lc86g lon": [float(parts[4])],
        "bme tempurature": [float(parts[5])],
        "bme pressure": [float(parts[6])],
        "bme humidity": [float(parts[7])],
        "lc86g speed": [float(parts[8])],
        "lc86g alt": [float(parts[9])]
    }

### ------------ For testing ------------ ###
def clamp_lat_lon(lat, lon):
    # keep values inside valid ranges
    lat = max(min(lat, 90.0), -90.0)
    lon = ((lon + 180.0) % 360.0) - 180.0
    return lat, lon
### ------------------------------------- ###

def data_fetcher_all(mode):
    global all_board, board_list
    board_count = 3
    while True:
        try:
            if mode == "api":
                url = "http://gurt_yo/gcs/all" # API url
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    data = r.json()  # {"0": "...", "1": "..."}
                else:
                    print("API error:", r.status_code)
                    time.sleep(2)
                    continue
            ### -------------------------- THIS IS PART IS FOR TESTING -------------------------- ###
            elif mode == "random": # for testing
                data = {}
                for i in range(board_count):
                    board_id = str(i)
                    if board_id not in board_list or len(board_list[board_id]["lat"]) == 0:
                        lat, lon = 30.0 + random.uniform(-0.01, 0.01), 90.0 + random.uniform(-0.01, 0.01)
                    else:
                        lat = board_list[board_id]["lat"][-1] + random.uniform(-0.05, 0.05)
                        lon = board_list[board_id]["lon"][-1] + random.uniform(-0.05, 0.05)
                    lat, lon = clamp_lat_lon(lat, lon)
                    data[board_id] = ",".join(map(str, [
                        random.randint(-10, 10),  # x
                        random.randint(-10, 10),  # y
                        random.randint(-10, 10),  # z
                        lat, lon,
                        random.uniform(20, 30),      # temp
                        random.uniform(1000, 1020),  # pressure
                        random.uniform(40, 70),      # humidity
                        random.uniform(10,100),      # speed
                        random.uniform(0, 1000)      # alt
                    ]))
            ### -------------------------------------------------------------------------------- ###
            else:
                raise ValueError("mode must be 'api' or 'random'")

            # process data
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
                board_list[board_id]["time"].append(elapsed_seconds())

        except Exception as e:
            print("Fetcher crashed:", repr(e))
            traceback.print_exc()

        time.sleep(1)

# start background thread
threading.Thread(target=lambda: data_fetcher_all(mode="random"), daemon=True).start() # REMEMBER to check the mode "api" and "random"

fig2d = go.Figure()
fig2d.update_layout(title="Temperature, Pressure, Humidity",
                    xaxis_title="Reading #", yaxis_title="Value")

fig2dlc = go.Figure()
fig2dlc.update_layout(title="Speed and Altitude",
                    xaxis_title="Reading #", yaxis_title="Value")

fig3d = go.Figure()
figgeo = go.Figure()

fig3d.update_layout(scene=dict(aspectmode="auto",bgcolor="#102c55"),
                    margin=dict(l=0, r=0, t=30, b=0),
                    title="Rocket 3D Trajectory")

figgeo.update_layout(
    geo=dict(projection=dict(type="orthographic")),
    title="Latitude Longitude Position")

app.layout = html.Div([
    html.H1("Universal Ground Control System", style={"textAlign": "center", "color" : "white"}),
    html.Div(children=[
        html.Label("Select board to view", style={"color" : "white"}),
        dcc.Dropdown(
            id="board-select",
            options=[{"label": f"Board {i}", "value": str(i)} for i in range(3)],
            value="0",
            clearable=False,
            style={"width": "200px",}
            )
        ], style={"padding" : "30px",}),
    html.Div(children=[
        html.Label("Select Metric to Display:",style={"color" : "white"}),
        dcc.Dropdown(
            id="bme-dropdown",
            options=[
                {"label": "Temperature", "value": "Tempurature"},
                {"label": "Pressure", "value": "Pressure"},
                {"label": "Humidity", "value": "Humidity"}],
            value="Tempurature", clearable=False,
            style={"width": "200px", }
        ),
    ], style={"padding" : "30px", }),
    # -------- Leaderboard --------
    html.Div([
        html.H2("Leaderboard", style={"textAlign": "center", "color": "white"}),
        dash_table.DataTable(
            id="leaderboard",
            columns=[
                {"name": "Board", "id": "board"},
                {"name": "Best Altitude (m)", "id": "alt"},
                {"name": "Δ from 1000m (m)", "id": "alt_diff"},
                {"name": "Max Speed (m/s)", "id": "speed"}
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
            }
        )
    ],style={"padding" : "15px"}),

    # -------- Row 1: BME + Speed/Alt --------
    html.Div([
        dcc.Graph(id="2d-bmestats", figure=fig2d,
                  style={"height": "400px", "flex": "1", "borderRadius": "1px solid gray", "padding": "10px", "boxShadow": "0 4px 10px rgba(0,0,0,0.1)"}),
        dcc.Graph(id="2d-speedalt", figure=fig2dlc,
                  style={"height": "400px", "flex": "1", "borderRadius": "1px solid gray", "padding": "10px", "boxShadow": "0 4px 10px rgba(0,0,0,0.1)"}),
    ], style={"display": "flex", "gap": "20px", "marginBottom": "20px"}),

    # -------- Row 2: 3D Trajectory + Globe --------
    html.Div([
        dcc.Graph(id="3d-trajectory", figure=fig3d,
                  style={"height": "400px", "flex": "1", "borderRadius": "1px solid gray", "padding": "10px", "boxShadow": "0 4px 10px rgba(0,0,0,0.1)"}),
        dcc.Graph(id="globe-latlon", figure=figgeo,
                  style={"height": "400px", "flex": "1", "borderRadius": "1px solid gray", "padding": "10px", "boxShadow": "0 4px 10px rgba(0,0,0,0.1)"}),
    ], style={"display": "flex", "gap": "10px"}),

    dcc.Interval(id="interval", interval=800, n_intervals=0)
    
])


@app.callback(
    Output("2d-bmestats", "figure"),
    Output("2d-speedalt", "figure"),
    Output("3d-trajectory", "figure"),
    Output("globe-latlon", "figure"),
    Output("leaderboard", "data"),
    Input("interval", "n_intervals"),
    Input("board-select", "value"),
    Input("bme-dropdown", "value")
)
def update_charts(n, selected_board, selected_metric):
    if selected_board not in board_list or len(board_list[selected_board]["x"]) == 0:
        return go.Figure(), go.Figure(), go.Figure(), go.Figure(), []

    board_data = board_list[selected_board]

    rows = []
    for bid, bdata in board_list.items():
        if not bdata["alt"] or not bdata["speed"]:
            continue

        # Best altitude (closest to 1000)
        alt_diffs = [abs(a - 1000) for a in bdata["alt"]]
        best_index = alt_diffs.index(min(alt_diffs))
        best_alt = bdata["alt"][best_index]
        best_alt_diff = alt_diffs[best_index]

        # Max speed
        max_speed = max(bdata["speed"])

        rows.append({
            "board": bid,
            "alt": round(best_alt, 1),
            "alt_diff": round(best_alt_diff, 1),
            "speed": round(max_speed, 1)
        })

    # Sort by Δ altitude first, then speed
    rows.sort(key=lambda x: (x["alt_diff"], -x["speed"]))

    fig2d = go.Figure(go.Scatter(
        y=board_data[selected_metric],
        x=board_data["time"],
        mode="lines+markers",
        line=dict(color="brown")
    ))
    unit = {"Tempurature": " (°C)", "Pressure": " (Pa)", "Humidity": " (%)"}
    fig2d.update_layout(
        title=f"{selected_metric} Over Time (Board {selected_board})",
        xaxis_title="Time (seconds)",
        yaxis_title=selected_metric + unit.get(selected_metric, ""),
        plot_bgcolor="#102c55",paper_bgcolor="#102c55",font=dict(color="white")
    )
    fig2dlc = go.Figure()
    fig2dlc.add_trace(go.Scatter(
        y=board_data["speed"],
        x=board_data["time"],
        mode="lines+markers",
        name="Speed"
    ))
    fig2dlc.add_trace(go.Scatter(
        y=board_data["alt"],
        x=board_data["time"],
        mode="lines+markers",
        name="Altitude"
    ))
    fig2dlc.update_layout(
        title=f"Speed and Altitude Over Time (Board {selected_board})",
        xaxis_title="Time (seconds)",
        yaxis_title="alt(m), speed(m/s)",
        plot_bgcolor="#102c55",paper_bgcolor="#102c55",font=dict(color="white")
    )
    if len(board_data["lat"]) > 1:
        lat0, lon0 = board_data["lat"][0], board_data["lon"][0]
        xs, ys, zs = [], [], []
        for la, lo, al in zip(board_data["lat"], board_data["lon"], board_data["alt"]):
            x, y = latlon_to_xy(lat0, lon0, la, lo)
            xs.append(x)
            ys.append(y)
            zs.append(al)  # altitude in meters
    else:
        xs, ys, zs = board_data["x"], board_data["y"], board_data["z"]

    fig3d = go.Figure(go.Scatter3d(
        x=xs,
        y=ys,
        z=zs,
        mode="lines+markers",
        name=f"Board {selected_board}",
        line=dict(color="blue"),
        marker=dict(size=4, color="red")
    ))
    fig3d.update_layout(scene=dict(
        xaxis_title="East-West (m)",
        yaxis_title="North-South (m)",
        zaxis_title="Altitude (m)",
        aspectmode="auto",
        bgcolor="#102c55"),
        margin=dict(l=0, r=0, t=80, b=0),
        title=f"Rocket 3D Trajectory (Board {selected_board})",
        paper_bgcolor="#102c55",
        font=dict(color="white")
    )
    figgeo = go.Figure()
    for bid, bdata in board_list.items():
        if len(bdata["lat"]) > 1 and bid != selected_board:
            figgeo.add_trace(go.Scattergeo(
                lon=bdata["lon"],
                lat=bdata["lat"],
                mode="lines+markers",
                name=f"Board {bid}",
                line=dict(width=1),
                marker=dict(size=4),
                opacity=0.6
            ))
    figgeo.add_trace(go.Scattergeo(
        lon=board_data["lon"],
        lat=board_data["lat"],
        mode="lines+markers",
        name=f"Board {selected_board} (selected)",
        line=dict(width=3),
        marker=dict(size=7)
    ))
    last_lat = board_data["lat"][-1]
    last_lon = board_data["lon"][-1]
    figgeo.update_geos(
        projection_type="orthographic",
        projection_rotation=dict(lat=last_lat, lon=last_lon),
        showland=True, landcolor="lightgray",
        showcountries=True,
        showocean=True, oceancolor="lightblue"
    ),
    figgeo.update_layout(title="Latitude Longitude Position", uirevision="stay",paper_bgcolor="#102c55",font=dict(color="white"))

    return fig2d, fig2dlc, fig3d, figgeo, rows

if __name__ == "__main__":
    app.run(debug=True)
