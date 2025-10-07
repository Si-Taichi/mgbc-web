import threading
import time
import random
import csv
import io
from flask import Flask, jsonify
from flask_sock import Sock
from blinker import Signal
from config import NUM_BOARDS, BOARD_NAMES

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

        # --- PHASE LOGIC ---
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

        # --- Update position ---
        if flight_phase not in ["GROUND", "LANDED"]:
            drift_factor = 0.001
            state['lat'] += random.uniform(-drift_factor, drift_factor)
            state['lon'] += random.uniform(-drift_factor, drift_factor)
            state['lat'], state['lon'] = self.clamp_lat_lon(state['lat'], state['lon'])

        # --- Acceleration ---
        if flight_phase == "GROUND":
            accel_x, accel_y, accel_z = random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(9, 11)
        elif flight_phase == "RISING":
            accel_x, accel_y, accel_z = random.uniform(-20, 20), random.uniform(-20, 20), random.uniform(50, 100)
        elif flight_phase == "COASTING":
            accel_x, accel_y, accel_z = random.uniform(-10, 10), random.uniform(-10, 10), random.uniform(0, 30)
        elif flight_phase == "MAIN DEPLOY":
            accel_x, accel_y, accel_z = random.uniform(-15, 15), random.uniform(-15, 15), random.uniform(-50, -10)
        elif flight_phase == "SECOND DEPLOY":
            accel_x, accel_y, accel_z = random.uniform(-8, 8), random.uniform(-8, 8), random.uniform(-20, -5)
        elif flight_phase == "LANDED":
            accel_x, accel_y, accel_z = random.uniform(-0.5, 0.5), random.uniform(-0.5, 0.5), random.uniform(9.5, 10.5)

        # --- Final update ---
        state['prev_alt'] = alt
        state['prev_time'] = elapsed_time

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


if __name__ == "__main__":
    import socket

    srv = WSDeviceData(NUM_BOARDS, host="0.0.0.0", port=8765, debug=False)
    generator = SampleDataGenerator(NUM_BOARDS)

    # Find local IP (for your Wi-Fi or LAN)
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    ws_url = f"ws://{local_ip}:8765/data"
    gcs_url = f"http://{local_ip}:8765/gcs/all"

    print("🚀 Starting WebSocket Data Generator...")
    print("---------------------------------------------------")
    print(f"🌐 Local WebSocket URLs:")
    print(f"   🔹 All devices: {ws_url}")
    print(f"   🔹 Single device (example): {ws_url}/0")
    print()
    print(f"📡 REST API:")
    print(f"   🔹 All data: {gcs_url}")
    print(f"   🔹 Single device (example): {gcs_url.replace('/all', '/0')}")
    print("---------------------------------------------------")

    def sampler():
        start = time.time()
        msg_count = 0
        while True:
            elapsed = time.time() - start
            for i in range(NUM_BOARDS):
                data = generator.generate_rocket_flight_data(i, elapsed)
                csv_msg = generator.create_csv_data(data)
                srv.publish(i, csv_msg)

                if msg_count % 20 == 0 and i == 0:
                    print(f"📤 Device {i}: Alt={data['alt']:.1f}m, Phase={data['phase']}")

            msg_count += 1
            time.sleep(0.5)

    threading.Thread(target=sampler, daemon=True).start()
    srv.run()
