from dash import Dash, dcc, html, Input, Output
import plotly.graph_objects as go
import requests
import threading
import time
from config import API_ADDRESS, DASH_HOST, DASH_PORT, BOARD_NAMES, NUM_BOARDS

app = Dash(__name__, update_title=None, title='Deployment Status Monitor')

# Global data storage
board_statuses = {}
deployment_history = {}  # Track deployment events persistently
api_status = "connecting"
last_update = None

def parse_csv_string(csv_string):
    """Parse CSV string from API"""
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
            "humidity": float(parts[7]),
            "alt": float(parts[8]),
            "phase": parts[9].strip().upper()
        }
    except Exception as e:
        print(f"Parse error: {e}")
        return None

def fetch_deployment_status():
    """Fetch data from API and update board statuses"""
    global board_statuses, api_status, last_update, deployment_history
    
    while True:
        try:
            response = requests.get(f"{API_ADDRESS}/gcs/all", timeout=5)
            if response.status_code == 200:
                data = response.json()
                new_statuses = {}
                
                for board_id, csv_string in data.items():
                    parsed_data = parse_csv_string(csv_string)
                    if parsed_data:
                        phase = parsed_data["phase"]
                        
                        # Initialize deployment history for this board if not exists
                        if board_id not in deployment_history:
                            deployment_history[board_id] = {
                                "main_deployed": False,
                                "second_deployed": False
                            }
                        
                        # Check if deployments occurred and persist them
                        if "MAIN" in phase and "DEPLOY" in phase:
                            deployment_history[board_id]["main_deployed"] = True
                        
                        if "SECOND" in phase and "DEPLOY" in phase:
                            deployment_history[board_id]["second_deployed"] = True
                        
                        # Use persistent deployment status from history
                        new_statuses[board_id] = {
                            "name": BOARD_NAMES.get(int(board_id), f"Board {board_id}"),
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

def get_phase_color(phase):
    """Get color based on flight phase"""
    if phase == "GROUND":
        return "#4B5563"
    elif phase == "RISING":
        return "#F97316"
    elif phase == "COASTING":
        return "#DC2626"
    elif "DEPLOY" in phase:
        return "#3B82F6"
    elif phase == "LANDED":
        return "#10B981"
    return "#6B7280"

# App Layout
app.layout = html.Div([
    # Header
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
                ], style={"marginLeft": "20px"})
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
                    html.Span(id="api-status-text", children="API Connected", style={
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
    
    # Status Cards Container
    html.Div(id="status-cards-container", children=[]),
    
    # Footer Info
    html.Div([
        html.Div([
            html.P([
                html.Span("API Endpoint: ", style={"fontWeight": "600", "color": "white"}),
                html.Span(f"{API_ADDRESS}/gcs/all", style={"color": "#9CA3AF"})
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
    
    # Update interval
    dcc.Interval(id="interval-component", interval=1000, n_intervals=0)
    
], style={
    "minHeight": "100vh",
    "background": "linear-gradient(to bottom right, #111827, #1E3A8A, #111827)",
    "padding": "40px"
})

@app.callback(
    Output("status-cards-container", "children"),
    Output("api-status-indicator", "style"),
    Output("api-status-text", "children"),
    Output("last-update-text", "children"),
    Output("active-boards-count", "children"),
    Input("interval-component", "n_intervals")
)
def update_dashboard(n):
    # Update API status
    if api_status == "connected":
        status_color = "#10B981"
        status_text = "API Connected"
    else:
        status_color = "#EF4444"
        status_text = "API Disconnected"
    
    status_indicator_style = {
        "width": "12px",
        "height": "12px",
        "borderRadius": "50%",
        "backgroundColor": status_color
    }
    
    # Update last update time
    update_text = f"Last update: {last_update}" if last_update else "Last update: --:--:--"
    
    # Active boards count
    active_count = str(len(board_statuses))
    
    # Create status cards
    if not board_statuses:
        if api_status == "connected":
            cards = html.Div([
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
            cards = html.Div([
                html.Div("❌", style={"fontSize": "64px", "marginBottom": "20px"}),
                html.H3("Connection Error", style={
                    "fontSize": "24px",
                    "fontWeight": "bold",
                    "color": "white",
                    "marginBottom": "10px"
                }),
                html.P(f"Cannot connect to API server at {API_ADDRESS}", style={
                    "color": "#9CA3AF",
                    "marginBottom": "5px"
                }),
                html.P("Make sure the API server is running", style={
                    "fontSize": "12px",
                    "color": "#6B7280"
                })
            ], style={
                "textAlign": "center",
                "padding": "80px 20px",
                "color": "white"
            })
    else:
        cards = html.Div([
            create_status_card(board_id, status)
            for board_id, status in board_statuses.items()
        ], style={
            "display": "grid",
            "gridTemplateColumns": "repeat(auto-fit, minmax(350px, 1fr))",
            "gap": "24px"
        })
    
    return cards, status_indicator_style, status_text, update_text, active_count

def create_status_card(board_id, status):
    """Create a status card for a board"""
    phase_color = get_phase_color(status["phase"])
    
    return html.Div([
        # Card Header
        html.Div([
            html.Div([
                html.H2(status["name"], style={
                    "fontSize": "20px",
                    "fontWeight": "bold",
                    "color": "white",
                    "margin": "0"
                }),
                html.Span(status["phase"], style={
                    "fontSize": "12px",
                    "fontWeight": "600",
                    "color": "white",
                    "backgroundColor": "rgba(0,0,0,0.3)",
                    "padding": "4px 12px",
                    "borderRadius": "12px"
                })
            ], style={
                "display": "flex",
                "justifyContent": "space-between",
                "alignItems": "center"
            })
        ], style={
            "backgroundColor": phase_color,
            "padding": "20px 24px"
        }),
        
        # Card Body
        html.Div([
            # Main Parachute
            html.Div([
                html.Div([
                    html.Div([
                        html.Span("✓" if status["main_deployed"] else "⏳", style={
                            "fontSize": "28px",
                            "color": "#4ADE80" if status["main_deployed"] else "#FBBF24"
                        }),
                        html.Div([
                            html.P("Main Deployment", style={
                                "color": "white",
                                "fontWeight": "700",
                                "margin": "0",
                                "fontSize": "24px"
                            }),
                            html.P("Primary deployment", style={
                                "color": "#9CA3AF",
                                "margin": "0",
                                "fontSize": "16px"
                            })
                        ], style={"marginLeft": "20px"})
                    ], style={"display": "flex", "alignItems": "center"}),
                    html.Span(
                        "DEPLOYED" if status["main_deployed"] else "STANDBY",
                        style={
                            "fontSize": "16px",
                            "fontWeight": "700",
                            "color": "white",
                            "backgroundColor": "#16A34A" if status["main_deployed"] else "#CA8A04",
                            "padding": "8px 20px",
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
                "padding": "24px",
                "borderRadius": "8px",
                "border": "1px solid #374151",
                "marginBottom": "16px"
            }),
            
            # Secondary Parachute
            html.Div([
                html.Div([
                    html.Div([
                        html.Span("✓" if status["second_deployed"] else "⏳", style={
                            "fontSize": "28px",
                            "color": "#4ADE80" if status["second_deployed"] else "#FBBF24"
                        }),
                        html.Div([
                            html.P("Second Deployment", style={
                                "color": "white",
                                "fontWeight": "700",
                                "margin": "0",
                                "fontSize": "24px"
                            }),
                            html.P("Secondary deployment", style={
                                "color": "#9CA3AF",
                                "margin": "0",
                                "fontSize": "16px"
                            })
                        ], style={"marginLeft": "20px"})
                    ], style={"display": "flex", "alignItems": "center"}),
                    html.Span(
                        "DEPLOYED" if status["second_deployed"] else "STANDBY",
                        style={
                            "fontSize": "16px",
                            "fontWeight": "700",
                            "color": "white",
                            "backgroundColor": "#16A34A" if status["second_deployed"] else "#CA8A04",
                            "padding": "8px 20px",
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
                "padding": "24px",
                "borderRadius": "8px",
                "border": "1px solid #374151"
            })
        ], style={"padding": "24px"})
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
    print(f"API Server: {API_ADDRESS}")
    print(f"Dashboard: http://{DASH_HOST}:{DASH_PORT}")
    print(f"Configured Boards: {NUM_BOARDS}")
    print("="*60)
    
    # Start data fetcher thread
    threading.Thread(target=fetch_deployment_status, daemon=True).start()
    
    # Run the app
    app.run(debug=True, host=DASH_HOST, port=DASH_PORT, use_reloader=False)
