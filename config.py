"""
Configuration file for the Rocket Telemetry System
Modify these values to customize the system behavior
"""

# ==========================================
# BOARD CONFIGURATION
# ==========================================

# Number of rocket boards to simulate
# You can change this to any number (tested up to 10)
NUM_BOARDS = 6

# Board names (optional, will use "Board 0", "Board 1", etc. if not specified)
BOARD_NAMES = {
    0: "Rocket Alpha",
    1: "Rocket Beta", 
    2: "Rocket Charlie",
    3: "Rocket Delta",
    4: "Rocket Echo",
    5: "Rocket Foxtrot"
}

# ==========================================
# SERVER CONFIGURATION
# ==========================================

# API Server settings
API_HOST = "localhost"
API_PORT = 5000

# Dashboard settings
DASH_HOST = "localhost"
DASH_PORT = 8050

# ==========================================
# DATA GENERATION SETTINGS
# ==========================================

# How often to generate new data (seconds)
DATA_UPDATE_INTERVAL = 0.5

# How often dashboard updates (milliseconds)
DASHBOARD_UPDATE_INTERVAL = 500

# Flight simulation parameters
FLIGHT_CONFIG = {
    "launch_duration": 10,      # seconds
    "ascent_duration": 20,      # seconds (after launch)
    "apogee_duration": 5,       # seconds at apogee
    "max_altitude": 1200,       # target maximum altitude in meters
    "launch_stagger": 15,       # max seconds between launches
}

# Sensor noise levels (realistic variations)
SENSOR_NOISE = {
    "accelerometer": 2.0,       # +/- g
    "temperature": 0.5,         # +/- degrees C
    "pressure": 1.0,            # +/- Pa
    "humidity": 2.0,            # +/- %
    "gps_drift": 0.001,         # +/- degrees lat/lon
    "altitude": 5.0,            # +/- meters
    "speed": 2.0,               # +/- m/s
}

# ==========================================
# UI CONFIGURATION
# ==========================================

# Chart colors
COLORS = {
    "temperature": "brown",
    "pressure": "purple", 
    "humidity": "teal",
    "speed": "orange",
    "altitude": "cyan",
    "accel_x": "red",
    "accel_y": "green", 
    "accel_z": "blue",
    "trajectory": "blue",
    "prediction_line": "yellow"
}

# Default values
DEFAULTS = {
    "predicted_apogee": 1200,   # meters
    "selected_board": "0",
    "selected_metric": "Tempurature"
}

# ==========================================
# ADVANCED SETTINGS
# ==========================================

# Maximum data points to store per board (memory management)
MAX_DATA_POINTS = 10000

def get_board_options():
    """Generate dropdown options for board selection"""
    options = []
    for i in range(NUM_BOARDS):
        name = BOARD_NAMES.get(i, f"Board {i}")
        options.append({"label": name, "value": str(i)})
    return options

def get_api_url():
    """Get the API base URL"""
    return f"http://{API_HOST}:{API_PORT}"

def get_dashboard_url():
    """Get the dashboard URL"""  
    return f"http://{DASH_HOST}:{DASH_PORT}"

if __name__ == '__main__':
    print("🚀 Rocket Telemetry System Configuration")
    print("=" * 50)
    print(f"Number of boards: {NUM_BOARDS}")
    print(f"API Server: {get_api_url()}")
    print(f"Dashboard: {get_dashboard_url()}")
    print(f"Data update interval: {DATA_UPDATE_INTERVAL}s")
    print(f"Dashboard update interval: {DASHBOARD_UPDATE_INTERVAL}ms")
    print("\nBoard Names:")
    for i in range(NUM_BOARDS):
        name = BOARD_NAMES.get(i, f"Board {i}")
        print(f"  {i}: {name}")
    print("\nTo change the number of boards, edit NUM_BOARDS in this file.")

