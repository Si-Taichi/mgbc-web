from flask import Flask, jsonify
import threading
import time
import random
from config import NUM_BOARDS, BOARD_NAMES

app = Flask(__name__)

# Global data storage
device_data = {}
data_lock = threading.Lock()

class SampleDataGenerator:
    def __init__(self, num_devices: int = NUM_BOARDS):
        self.num_devices = num_devices
        self.device_states = {}
        
        for i in range(num_devices):
            self.device_states[i] = {
                'lat': 30.0 + random.uniform(-0.01, 0.01),
                'lon': 90.0 + random.uniform(-0.01, 0.01),
                'alt': random.uniform(0, 50),
                'temp': random.uniform(20, 25),
                'pressure': random.uniform(1010, 1020),
                'humidity': random.uniform(40, 60),
                'time_offset': random.uniform(0, 15),
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
        lat = max(min(lat, 90.0), -90.0)
        lon = ((lon + 180.0) % 360.0) - 180.0
        return lat, lon
    
    def generate_rocket_flight_data(self, device_id: int, elapsed_time: float):
        state = self.device_states[device_id]
        
        if state['prev_alt'] is None:
            state['prev_alt'] = state['alt']
            state['prev_time'] = elapsed_time
        
        flight_time = elapsed_time - state['time_offset']
        
        if flight_time < 0:
            flight_phase = "GROUND"
            alt = state['alt'] + random.uniform(-1, 1)
            temp_change = random.uniform(-0.5, 0.5)
            pressure_change = random.uniform(-2, 2)
            
        elif flight_time < 10 and not state['has_landed']:
            if not state['has_launched']:
                state['has_launched'] = True
                state['launch_time'] = elapsed_time
            flight_phase = "RISING"
            alt = state['alt'] + (flight_time ** 2) * 5
            temp_change = -flight_time * 0.5
            pressure_change = -flight_time * 2
            
        elif flight_time < 30 and not state['has_landed']:
            flight_phase = "COASTING"
            t_ascent = flight_time - 10
            alt = state['alt'] + 500 + t_ascent * 25 - (t_ascent ** 2) * 0.3
            temp_change = -10 - t_ascent * 0.3
            pressure_change = -30 - t_ascent * 1.5
            
        elif flight_time < 35 and not state['has_landed']:
            flight_phase = "MAIN DEPLOY"
            if not state['main_deploy_triggered']:
                state['main_deploy_triggered'] = True
                
            t_apogee = flight_time - 30
            max_alt = state['alt'] + 500 + 20 * 25 - (20 ** 2) * 0.3
            alt = max_alt - (t_apogee ** 2) * 2
            temp_change = -16
            pressure_change = -60
            
            if alt > state['max_altitude_reached']:
                state['max_altitude_reached'] = alt
                
        elif not state['has_landed']:
            t_descent = flight_time - 35
            max_alt = state['alt'] + 500 + 20 * 25 - (20 ** 2) * 0.3
            alt = max(state['alt'], max_alt - 50 - (t_descent ** 2) * 3)
            temp_change = -16 + t_descent * 0.2
            pressure_change = -60 + t_descent * 1.2
            
            if alt <= 150 and not state['second_deploy_triggered']:
                state['second_deploy_triggered'] = True
                flight_phase = "SECOND DEPLOY"
            elif state['second_deploy_triggered']:
                flight_phase = "SECOND DEPLOY"
            else:
                flight_phase = "MAIN DEPLOY"
            
            if alt <= state['alt'] + 10 and t_descent > 10:
                state['has_landed'] = True
                state['landing_time'] = elapsed_time
                
        else:
            flight_phase = "LANDED"
            time_since_landing = elapsed_time - state['landing_time']
            alt = state['alt'] + random.uniform(0, 2)
            temp_change = random.uniform(-0.3, 0.3) + (time_since_landing * 0.05)
            pressure_change = random.uniform(-1, 1)
        
        if flight_phase not in ["GROUND", "LANDED"]:
            drift_factor = 0.001
            state['lat'] += random.uniform(-drift_factor, drift_factor)
            state['lon'] += random.uniform(-drift_factor, drift_factor)
            state['lat'], state['lon'] = self.clamp_lat_lon(state['lat'], state['lon'])
        
        state['prev_alt'] = alt
        state['prev_time'] = elapsed_time
        
        if flight_phase == "GROUND":
            accel_x = random.uniform(-1, 1)
            accel_y = random.uniform(-1, 1)
            accel_z = random.uniform(9, 11)
        elif flight_phase == "RISING":
            accel_x = random.uniform(-20, 20)
            accel_y = random.uniform(-20, 20)
            accel_z = random.uniform(50, 100)
        elif flight_phase == "COASTING":
            accel_x = random.uniform(-10, 10)
            accel_y = random.uniform(-10, 10)
            accel_z = random.uniform(0, 30)
        elif flight_phase == "MAIN DEPLOY":
            accel_x = random.uniform(-15, 15)
            accel_y = random.uniform(-15, 15)
            accel_z = random.uniform(-50, -10)
        elif flight_phase == "SECOND DEPLOY":
            accel_x = random.uniform(-8, 8)
            accel_y = random.uniform(-8, 8)
            accel_z = random.uniform(-20, -5)
        elif flight_phase == "LANDED":
            accel_x = random.uniform(-0.5, 0.5)
            accel_y = random.uniform(-0.5, 0.5)
            accel_z = random.uniform(9.5, 10.5)
        
        return {
            'accel_x': accel_x,
            'accel_y': accel_y,
            'accel_z': accel_z,
            'lat': state['lat'],
            'lon': state['lon'],
            'temp': state['temp'] + temp_change + random.uniform(-0.5, 0.5),
            'pressure': state['pressure'] + pressure_change + random.uniform(-1, 1),
            'humidity': max(0, min(100, state['humidity'] + random.uniform(-2, 2))),
            'alt': max(0, alt + random.uniform(-5, 5)),
            'phase': flight_phase
        }
    
    def create_csv_data(self, data):
        return ",".join([
            f"{data['accel_x']:.2f}",
            f"{data['accel_y']:.2f}",
            f"{data['accel_z']:.2f}",
            f"{data['lat']:.6f}",
            f"{data['lon']:.6f}",
            f"{data['temp']:.2f}",
            f"{data['pressure']:.2f}",
            f"{data['humidity']:.2f}",
            f"{data['alt']:.2f}",
            data['phase']
        ])
    
    def run_data_generator(self):
        start_time = time.time()
        counter = 0
        
        print(f"Starting data generation for {self.num_devices} devices")
        
        while True:
            try:
                elapsed_time = time.time() - start_time
                
                with data_lock:
                    for device_id in range(self.num_devices):
                        flight_data = self.generate_rocket_flight_data(device_id, elapsed_time)
                        csv_data = self.create_csv_data(flight_data)
                        device_data[str(device_id)] = csv_data
                        
                        if counter % 10 == 0 and device_id == 0:
                            print(f"Device {device_id}: {flight_data['phase']} - Alt: {flight_data['alt']:.1f}m")
                
                counter += 1
                time.sleep(0.5)
                
            except Exception as e:
                print(f"Error in data generator: {e}")
                time.sleep(1)

data_generator = SampleDataGenerator(num_devices=NUM_BOARDS)

# API Routes - Only /gcs/all and /gcs/<device_id>

@app.route('/gcs/all')
def get_all_devices():
    """Return data for all devices in format: {"0": csv_string, "1": csv_string, ...}"""
    with data_lock:
        return jsonify(dict(device_data))

@app.route('/gcs/<int:device_id>')
def get_device_data(device_id):
    """Return data for specific device in format: {"data": csv_string}"""
    with data_lock:
        device_key = str(device_id)
        if device_key in device_data:
            return jsonify({"data": device_data[device_key]})
        else:
            return jsonify({"error": f"Device {device_id} not found"}), 404

def start_data_generator():
    thread = threading.Thread(target=data_generator.run_data_generator, daemon=True)
    thread.start()
    return thread

if __name__ == '__main__':
    print("="*60)
    print("API Server")
    print("="*60)
    print(f"Configuration: {NUM_BOARDS} boards")
    for i in range(NUM_BOARDS):
        board_name = BOARD_NAMES.get(i, f"Board {i}")
        print(f"  Device {i}: {board_name}")
    print("\nAvailable endpoints:")
    print("  /gcs/all - Get all device data")
    print("  /gcs/<device_id> - Get specific device data")
    print("="*60)
    
    start_data_generator()
    app.run(host='0.0.0.0', port=5000, debug=True)
