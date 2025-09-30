"""
Simple startup script for the API-based rocket telemetry system
"""

import subprocess
import time
import sys
import os

def start_api_server():
    """Start the API server"""
    print("🚀 Starting API server...")
    try:
        proc = subprocess.Popen([
            sys.executable, 'ws_server.py'
        ])
        return proc
    except Exception as e:
        print(f"❌ Failed to start API server: {e}")
        return None

def start_groundboard():
    """Start the groundboard dashboard"""
    print("📊 Starting Groundboard dashboard...")
    try:
        # Wait for API server to be ready
        time.sleep(3)
        proc = subprocess.Popen([
            sys.executable, 'groundDashboard.py'
        ])
        return proc
    except Exception as e:
        print(f"❌ Failed to start Groundboard: {e}")
        return None

def main():
    print("="*70)
    print("🚀 ROCKET TELEMETRY SYSTEM - API MODE")
    print("="*70)
    
    # Check if files exist
    required_files = ['ws_server.py', 'groundDashboard.py']
    missing_files = [f for f in required_files if not os.path.exists(f)]
    
    if missing_files:
        print(f"❌ Missing files: {', '.join(missing_files)}")
        print("Please create these files first.")
        return
    
    print("📋 System Architecture:")
    print("   API Server (Port 5000) → HTTP REST API → Dashboard (Port 8050)")
    print()
    
    # Start API server
    api_proc = start_api_server()
    if not api_proc:
        return
    
    print("⏳ Waiting for API server to initialize...")
    time.sleep(5)
    
    # Start dashboard
    dash_proc = start_groundboard()
    if not dash_proc:
        print("❌ Stopping API server...")
        api_proc.terminate()
        return
    
    print()
    print("="*70)
    print("✅ SYSTEM STARTED SUCCESSFULLY!")
    print("="*70)
    print("🔧 API Server:        http://localhost:5000")
    print("   📄 Status page:    http://localhost:5000/")
    print("   📊 All devices:    http://localhost:5000/gcs/all")
    print("   🏥 Health check:   http://localhost:5000/health")
    print()
    print("📊 Groundboard:       http://localhost:8050")
    print("   🎯 Live dashboard")
    print()
    print("🔄 Data Flow:")
    print("   Sample Generator → API Server → HTTP Requests → Dashboard")
    print()
    print("⚠️  Press Ctrl+C to stop both services")
    print("="*70)
    
    try:
        # Wait for processes
        while api_proc.poll() is None and dash_proc.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Stopping services...")
    finally:
        if api_proc and api_proc.poll() is None:
            print("🔧 Stopping API server...")
            api_proc.terminate()
            api_proc.wait()
        
        if dash_proc and dash_proc.poll() is None:
            print("📊 Stopping dashboard...")
            dash_proc.terminate()
            dash_proc.wait()
        
        print("✅ All services stopped.")

if __name__ == '__main__':

    main()

