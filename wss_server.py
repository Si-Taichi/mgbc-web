# wss_server.py
import threading
import time
import random
import csv
import io
from flask import Flask, jsonify
from flask_sock import Sock
from blinker import Signal

class WSDeviceData:
    def __init__(self, num_devices, *, host='0.0.0.0', port=8765, debug=False):
        self.app = Flask(__name__)
        self.sock = Sock(self.app)
        self.num_devices = num_devices
        self.host, self.port, self.debug = host, port, debug
        self.sig = [Signal(f'dev:{i}') for i in range(num_devices)]
        self.device_data = {str(i): "" for i in range(num_devices)}
        self.lock = threading.Lock()
        self._register_routes()

    def publish(self, dev_id: int, data: str):
        if 0 <= dev_id < self.num_devices:
            with self.lock:
                self.device_data[str(dev_id)] = data
            # Send just the CSV string to WebSocket clients
            self.sig[dev_id].send(data=data)

    def _register_routes(self):
        @self.app.route('/')
        def index():
            return '✅ WebSocket test server running.'

        # WebSocket for individual device - sends CSV string
        @self.sock.route('/data/<int:dev_id>')
        def ws_data(ws, dev_id):
            if not (0 <= dev_id < self.num_devices):
                ws.send('error: invalid device id')
                return
            
            stop = threading.Event()
            def handler(sender=None, data=None):
                if not stop.is_set():
                    try:
                        ws.send(data)  # Send CSV string directly
                    except Exception:
                        stop.set()
            
            self.sig[dev_id].connect(handler, weak=False)
            try:
                while ws.receive() is not None:
                    pass
            finally:
                stop.set()
                self.sig[dev_id].disconnect(handler)

        # WebSocket for all devices - sends CSV strings
        @self.sock.route('/data')
        def ws_all(ws):
            stop = threading.Event()
            def make_handler():
                def h(sender=None, data=None):
                    if not stop.is_set():
                        try:
                            ws.send(data)  # Send CSV string directly
                        except Exception:
                            stop.set()
                return h
            
            handlers = []
            for sig in self.sig:
                h = make_handler()
                sig.connect(h, weak=False)
                handlers.append((sig, h))
            
            try:
                while ws.receive() is not None:
                    pass
            finally:
                stop.set()
                for sig, h in handlers:
                    sig.disconnect(h)

        # WebSocket for /gcs/all - sends CSV strings (not JSON)
        @self.sock.route('/gcs/all')
        def ws_gcs_all(ws):
            """Send CSV strings from all devices"""
            stop = threading.Event()
            
            def make_handler():
                def h(sender=None, data=None):
                    if not stop.is_set():
                        try:
                            # Send just the CSV string
                            ws.send(data)
                        except Exception:
                            stop.set()
                return h
            
            handlers = []
            for sig in self.sig:
                h = make_handler()
                sig.connect(h, weak=False)
                handlers.append((sig, h))
            
            try:
                while ws.receive() is not None:
                    pass
            finally:
                stop.set()
                for sig, h in handlers:
                    sig.disconnect(h)

        # REST API endpoints (return JSON)
        @self.app.route('/gcs/<int:device_id>')
        def get_device(device_id):
            """Return latest CSV for one device"""
            with self.lock:
                key = str(device_id)
                if key in self.device_data:
                    return jsonify({"data": self.device_data[key]})
                else:
                    return jsonify({"error": f"Device {device_id} not found"}), 404

        @self.app.route('/gcs/all')
        def get_all_devices():
            """Return all latest CSVs as JSON"""
            with self.lock:
                return jsonify(dict(self.device_data))

    def run(self):
        self.app.run(host=self.host, port=self.port, debug=self.debug)


class SampleDataGenerator:
    def __init__(self, num_devices: int):
        self.num_devices = num_devices
        self.device_states = {
            i: {
                'lat': 13.7563 + random.uniform(-0.01, 0.01),
                'lon': 100.5018 + random.uniform(-0.01, 0.01),
                'alt': 0,
                'temp': 25 + random.uniform(-2, 2),
                'pressure': 101325,
                'humidity': 60 + random.uniform(-10, 10),
                'time_offset': i * random.uniform(0, 5),  # Stagger launches
                'launch_time': 10,
                'ascent_time': 20,
                'max_alt': 1300 + random.uniform(-100, 100),
                'main_deploy': False,
                'second_deploy': False
            } for i in range(num_devices)
        }

    def generate_flight_data(self, device_id: int, elapsed_time: float):
        state = self.device_states[device_id]
        flight_time = elapsed_time - state['time_offset']
        
        # Initialize altitude to current state value
        alt = state['alt']
        
        # Determine phase
        if flight_time < 0:
            phase = "IDLE"
            alt = 0
            ax, ay, az = 0, 0, 9.81
        elif flight_time < state['launch_time']:
            phase = "LAUNCH"
            progress = flight_time / state['launch_time']
            alt = state['max_alt'] * 0.2 * progress
            ax, ay, az = random.uniform(-2, 2), random.uniform(-2, 2), 15 + random.uniform(-3, 3)
        elif flight_time < state['launch_time'] + state['ascent_time']:
            phase = "RISING"
            progress = (flight_time - state['launch_time']) / state['ascent_time']
            alt = state['max_alt'] * 0.2 + state['max_alt'] * 0.8 * (progress ** 1.5)
            ax, ay, az = random.uniform(-1, 1), random.uniform(-1, 1), 5 + random.uniform(-2, 2)
        elif flight_time < state['launch_time'] + state['ascent_time'] + 5:
            phase = "COASTING"
            alt = state['max_alt']
            ax, ay, az = random.uniform(-0.5, 0.5), random.uniform(-0.5, 0.5), -1
        else:
            # Descent - FIXED: Initialize alt before using it
            time_since_apogee = flight_time - (state['launch_time'] + state['ascent_time'] + 5)
            
            # Start from max altitude
            alt = state['max_alt']
            
            # Deploy parachutes at specific altitudes
            descent_rate = 50  # Fast freefall initially
            if alt < state['max_alt'] * 0.7 and not state['main_deploy']:
                state['main_deploy'] = True
                phase = "MAIN_DEPLOY"
                descent_rate = 15
            elif alt < state['max_alt'] * 0.3 and not state['second_deploy']:
                state['second_deploy'] = True
                phase = "SECOND_DEPLOY"
                descent_rate = 5
            else:
                phase = "DESCENT"
                if state['second_deploy']:
                    descent_rate = 5
                elif state['main_deploy']:
                    descent_rate = 15
            
            # Calculate altitude based on descent rate
            alt = max(0, state['max_alt'] - descent_rate * time_since_apogee)
            ax, ay, az = random.uniform(-1, 1), random.uniform(-1, 1), -2 + random.uniform(-1, 1)
        
        # Update position with drift
        drift_factor = alt * 0.00001
        state['lat'] += random.uniform(-drift_factor, drift_factor)
        state['lon'] += random.uniform(-drift_factor, drift_factor)
        
        # Update environmental
        state['temp'] = 25 - (alt * 0.0065) + random.uniform(-0.5, 0.5)
        state['pressure'] = 101325 * (1 - 0.0065 * alt / 288.15) ** 5.255 + random.uniform(-100, 100)
        state['humidity'] = max(0, min(100, 60 + random.uniform(-5, 5)))
        state['alt'] = alt
        
        return {
            'ax': ax,
            'ay': ay,
            'az': az,
            'lat': state['lat'],
            'lon': state['lon'],
            'temp': state['temp'],
            'pressure': state['pressure'],
            'humidity': state['humidity'],
            'alt': alt,
            'phase': phase
        }

    def to_csv(self, data):
        """Convert data dict to CSV string"""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            round(data['ax'], 3),
            round(data['ay'], 3),
            round(data['az'], 3),
            round(data['lat'], 6),
            round(data['lon'], 6),
            round(data['temp'], 2),
            round(data['pressure'], 2),
            round(data['humidity'], 2),
            round(data['alt'], 2),
            data['phase']
        ])
        return output.getvalue().strip()


if __name__ == "__main__":
    from config import NUM_BOARDS
    
    srv = WSDeviceData(NUM_BOARDS, host="0.0.0.0", port=8765, debug=False)
    generator = SampleDataGenerator(NUM_BOARDS)

    def sampler():
        start = time.time()
        msg_count = 0
        while True:
            elapsed = time.time() - start
            for i in range(NUM_BOARDS):
                data = generator.generate_flight_data(i, elapsed)
                csv_msg = generator.to_csv(data)
                srv.publish(i, csv_msg)
                
                # Log every 20 messages
                msg_count += 1
                if msg_count % 20 == 0:
                    print(f"📤 Board {i}: Alt={data['alt']:.1f}m, Phase={data['phase']}")
            
            time.sleep(0.5)

    print("🚀 Starting data sampler...")
    threading.Thread(target=sampler, daemon=True).start()
    srv.run()