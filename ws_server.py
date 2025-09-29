from flask import Flask, jsonify
import threading
import time
import random
import json
from config import NUM_BOARDS, BOARD_NAMES  # Import from config

app = Flask(__name__)

# Global data storage - simulates database
device_data = {}
data_lock = threading.Lock()

class SampleDataGenerator:
    def __init__(self, num_devices: int = NUM_BOARDS):
        self.num_devices = num_devices
        self.device_states = {}
        
        # Initialize device states with realistic starting positions
        for i in range(num_devices):
            self.device_states[i] = {
                'lat': 30.0 + random.uniform(-0.01, 0.01),
                'lon': 90.0 + random.uniform(-0.01, 0.01),
                'alt': random.uniform(0, 50),  # Starting altitude
                'temp': random.uniform(20, 25),
                'pressure': random.uniform(1010, 1020),
                'humidity': random.uniform(40, 60),
                'speed': 0.0,
                'time_offset': random.uniform(0, 15),  # Stagger the flights
                'main_deploy_triggered': False,
                'second_deploy_triggered': False,
                'max_altitude_reached': 0,
                'has_launched': False,
                'has_landed': False,
                'launch_time': None,
                'landing_time': None,
                'prev_alt': None,
                'prev_time': None
            }
    
    def clamp_lat_lon(self, lat, lon):
        """Keep values inside valid ranges"""
        lat = max(min(lat, 90.0), -90.0)
        lon = ((lon + 180.0) % 360.0) - 180.0
        return lat, lon
    
    def generate_rocket_flight_data(self, device_id: int, elapsed_time: float):
        """Generate realistic rocket flight data"""
        state = self.device_states[device_id]
        
        # Initialize tracking variables if not set
        if state['prev_alt'] is None:
            state['prev_alt'] = state['alt']
            state['prev_time'] = elapsed_time
        
        # Calculate time since system start for this rocket
        flight_time = elapsed_time - state['time_offset']
        
        # Determine flight phase based on time and state
        if flight_time < 0:
            # Not launched yet - GROUND phase
            flight_phase = "GROUND"
            alt = state['alt'] + random.uniform(-1, 1)  # Small ground noise
            speed = random.uniform(0, 2)  # Very low speed on ground
            temp_change = random.uniform(-0.5, 0.5)  # Ambient temperature variation
            pressure_change = random.uniform(-2, 2)  # Weather pressure variation
            
        elif flight_time < 10 and not state['has_landed']:  # Launch/Rising phase (0-10 seconds)
            if not state['has_launched']:
                state['has_launched'] = True
                state['launch_time'] = elapsed_time
            flight_phase = "RISING"
            alt = state['alt'] + (flight_time ** 2) * 5  # Accelerating upward
            speed = flight_time * 10
            temp_change = -flight_time * 0.5  # Getting colder
            pressure_change = -flight_time * 2
            
        elif flight_time < 30 and not state['has_landed']:  # Coasting phase (10-30 seconds)
            flight_phase = "COASTING"
            t_ascent = flight_time - 10
            alt = state['alt'] + 500 + t_ascent * 25 - (t_ascent ** 2) * 0.3  # Slowing down
            speed = max(0, 50 - t_ascent * 2)
            temp_change = -10 - t_ascent * 0.3
            pressure_change = -30 - t_ascent * 1.5
            
        elif flight_time < 35 and not state['has_landed']:  # Apogee - MAIN DEPLOY phase (30-35 seconds)
            flight_phase = "MAIN DEPLOY"
            if not state['main_deploy_triggered']:
                state['main_deploy_triggered'] = True
                
            t_apogee = flight_time - 30
            max_alt = state['alt'] + 500 + 20 * 25 - (20 ** 2) * 0.3
            alt = max_alt - (t_apogee ** 2) * 2  # Start falling slowly
            speed = t_apogee * 4
            temp_change = -16
            pressure_change = -60
            
            # Update max altitude reached
            if alt > state['max_altitude_reached']:
                state['max_altitude_reached'] = alt
                
        elif not state['has_landed']:  # Descent phase
            t_descent = flight_time - 35
            max_alt = state['alt'] + 500 + 20 * 25 - (20 ** 2) * 0.3
            alt = max(state['alt'], max_alt - 50 - (t_descent ** 2) * 3)  # Falling faster
            speed = min(100, t_descent * 8)
            temp_change = -16 + t_descent * 0.2  # Warming up as descending
            pressure_change = -60 + t_descent * 1.2
            
            # SECOND DEPLOY triggers at 150m altitude
            if alt <= 150 and not state['second_deploy_triggered']:
                state['second_deploy_triggered'] = True
                flight_phase = "SECOND DEPLOY"
            elif state['second_deploy_triggered']:
                flight_phase = "SECOND DEPLOY"
            else:
                flight_phase = "MAIN DEPLOY"  # Still descending with main chute
            
            # Check for landing (altitude close to starting altitude and reasonable time)
            if alt <= state['alt'] + 10 and t_descent > 10:  # After reasonable descent time
                state['has_landed'] = True
                state['landing_time'] = elapsed_time
                
        else:  # LANDED phase
            flight_phase = "LANDED"
            time_since_landing = elapsed_time - state['landing_time']
            alt = state['alt'] + random.uniform(0, 2)  # Small ground variations
            speed = random.uniform(0, 1)  # Nearly zero speed
            temp_change = random.uniform(-0.3, 0.3) + (time_since_landing * 0.05)  # Gradually warming up
            pressure_change = random.uniform(-1, 1)  # Ambient pressure
        
        # Update position (slight drift during flight)
        if flight_phase not in ["GROUND", "LANDED"]:
            drift_factor = 0.001
            state['lat'] += random.uniform(-drift_factor, drift_factor)
            state['lon'] += random.uniform(-drift_factor, drift_factor)
            state['lat'], state['lon'] = self.clamp_lat_lon(state['lat'], state['lon'])
        
        # Store current altitude for next iteration
        state['prev_alt'] = alt
        state['prev_time'] = elapsed_time
        
        # Generate accelerometer data (simulate vibrations and movements)
        if flight_phase == "GROUND":
            accel_x = random.uniform(-1, 1)  # Minimal movement
            accel_y = random.uniform(-1, 1)
            accel_z = random.uniform(9, 11)  # ~1g + small noise
        elif flight_phase == "RISING":
            accel_x = random.uniform(-20, 20)
            accel_y = random.uniform(-20, 20) 
            accel_z = random.uniform(50, 100)  # Strong upward acceleration
        elif flight_phase == "COASTING":
            accel_x = random.uniform(-10, 10)
            accel_y = random.uniform(-10, 10)
            accel_z = random.uniform(0, 30)
        elif flight_phase == "MAIN DEPLOY":
            accel_x = random.uniform(-15, 15)
            accel_y = random.uniform(-15, 15)
            accel_z = random.uniform(-50, -10)  # Falling/deceleration
        elif flight_phase == "SECOND DEPLOY":
            accel_x = random.uniform(-8, 8)
            accel_y = random.uniform(-8, 8)
            accel_z = random.uniform(-20, -5)  # Slower descent with second chute
        elif flight_phase == "LANDED":
            accel_x = random.uniform(-0.5, 0.5)  # Very minimal movement
            accel_y = random.uniform(-0.5, 0.5)
            accel_z = random.uniform(9.5, 10.5)  # ~1g, very stable
        
        return {
            'accel_x': accel_x,
            'accel_y': accel_y,
            'accel_z': accel_z,
            'lat': state['lat'],
            'lon': state['lon'],
            'temp': state['temp'] + temp_change + random.uniform(-0.5, 0.5),
            'pressure': state['pressure'] + pressure_change + random.uniform(-1, 1),
            'humidity': max(0, min(100, state['humidity'] + random.uniform(-2, 2))),
            'speed': speed + random.uniform(-2, 2),
            'alt': max(0, alt + random.uniform(-5, 5)),
            'phase': flight_phase
        }
    
    def create_csv_data(self, data):
        """Convert data dict to CSV string format expected by groundboard"""
        return ",".join([
            f"{data['accel_x']:.2f}",
            f"{data['accel_y']:.2f}", 
            f"{data['accel_z']:.2f}",
            f"{data['lat']:.6f}",
            f"{data['lon']:.6f}",
            f"{data['temp']:.2f}",
            f"{data['pressure']:.2f}",
            f"{data['humidity']:.2f}",
            f"{data['speed']:.2f}",
            f"{data['alt']:.2f}",
            data['phase']  # 11th data point - flight phase
        ])
    
    def run_data_generator(self):
        """Main loop to generate and store data"""
        start_time = time.time()
        counter = 0
        
        print("Starting data generation for API server...")
        print(f"Generating data for {self.num_devices} devices")
        
        while True:
            try:
                elapsed_time = time.time() - start_time
                
                with data_lock:
                    for device_id in range(self.num_devices):
                        # Generate flight data
                        flight_data = self.generate_rocket_flight_data(device_id, elapsed_time)
                        
                        # Convert to CSV format
                        csv_data = self.create_csv_data(flight_data)
                        
                        # Store in global data structure
                        device_data[str(device_id)] = csv_data
                        
                        # Print status every 10 iterations for device 0
                        if counter % 10 == 0 and device_id == 0:
                            print(f"Device {device_id}: {flight_data['phase']} - "
                                  f"Alt: {flight_data['alt']:.1f}m, "
                                  f"Speed: {flight_data['speed']:.1f}m/s, "
                                  f"Temp: {flight_data['temp']:.1f}°C")
                
                counter += 1
                time.sleep(0.5)  # Update every 500ms
                
            except Exception as e:
                print(f"Error in data generator: {e}")
                time.sleep(1)

# Initialize data generator with dynamic board count
data_generator = SampleDataGenerator(num_devices=NUM_BOARDS)

# API Routes
@app.route('/')
def index():
    # Generate dynamic HTML based on NUM_BOARDS from config
    device_links = []
    for i in range(NUM_BOARDS):
        board_name = BOARD_NAMES.get(i, f"Board {i}")
        device_links.append(f'<li><a href="/gcs/device/{i}">/gcs/device/{i}</a> - Get data from {board_name}</li>')
    
    device_links_html = '\n        '.join(device_links)
    
    return f'''
    <h1>Rocket Telemetry API Server</h1>
    <p><strong>Configuration:</strong> {NUM_BOARDS} boards configured</p>
    <p>Available endpoints:</p>
    <ul>
        <li><a href="/gcs/all">/gcs/all</a> - Get data from all devices</li>
        {device_links_html}
        <li><a href="/status">/status</a> - Server status</li>
        <li><a href="/health">/health</a> - Health check</li>
    </ul>
    <p>Data format: CSV string with accelerometer, GPS, BME sensor data, and flight phase</p>
    <p>CSV Format: accel_x,accel_y,accel_z,lat,lon,temp,pressure,humidity,speed,alt,phase</p>
    <p>Flight Phases: GROUND, RISING, COASTING, MAIN DEPLOY, SECOND DEPLOY, LANDED</p>
    
    <h2>Board Configuration</h2>
    <ul>
    ''' + '\n    '.join([f'<li>Device {i}: {BOARD_NAMES.get(i, f"Board {i}")}</li>' for i in range(NUM_BOARDS)]) + '''
    </ul>
    '''

@app.route('/gcs/all')
def get_all_devices():
    """Get data from all devices - matches your original groundboard expectation"""
    with data_lock:
        # Return data in the format your groundboard expects
        return jsonify(dict(device_data))

@app.route('/gcs/device/<int:device_id>')
def get_device_data(device_id):
    """Get data from specific device"""
    with data_lock:
        device_key = str(device_id)
        if device_key in device_data:
            board_name = BOARD_NAMES.get(device_id, f"Board {device_id}")
            return jsonify({
                "device_id": device_id,
                "board_name": board_name,
                "data": device_data[device_key]
            })
        else:
            return jsonify({"error": f"Device {device_id} not found"}), 404

@app.route('/status')
def status():
    """Server status and statistics"""
    with data_lock:
        board_info = {}
        for i in range(NUM_BOARDS):
            board_info[str(i)] = BOARD_NAMES.get(i, f"Board {i}")
        
        return jsonify({
            "status": "running",
            "configured_boards": NUM_BOARDS,
            "active_devices": len(device_data),
            "board_names": board_info,
            "devices": list(device_data.keys()),
            "sample_data": {k: v for k, v in list(device_data.items())[:1]}  # Show one example
        })

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "timestamp": time.time(), "boards": NUM_BOARDS})

def start_data_generator():
    """Start the data generator in a background thread"""
    thread = threading.Thread(target=data_generator.run_data_generator, daemon=True)
    thread.start()
    return thread

if __name__ == '__main__':
    print("="*60)
    print("Rocket Telemetry API Server")
    print("="*60)
    print(f"Configuration: {NUM_BOARDS} boards")
    for i in range(NUM_BOARDS):
        board_name = BOARD_NAMES.get(i, f"Board {i}")
        print(f"  Device {i}: {board_name}")
    print("Starting data generator...")
    
    # Start data generation in background
    start_data_generator()
    
    print("Starting Flask API server...")
    print("API will be available at: http://localhost:5000")
    print("All devices endpoint: http://localhost:5000/gcs/all")
    print("="*60)
    
    # Start Flask server
    app.run(host='0.0.0.0', port=5000, debug=False)
