"""
Simple startup script
"""

import subprocess
import time
import sys
import os
from config import API_ADDRESS, DASH_HOST, DASH_PORT

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
    print("🚀 Multi Ground Board Connection - API MODE")
    print("="*70)
    
    # Check if files exist
    required_files = ['ws_server.py', 'groundDashboard.py', 'config.py']
    missing_files = [f for f in required_files if not os.path.exists(f)]
    
    if missing_files:
        print(f"❌ Missing files: {', '.join(missing_files)}")
        print("Please create these files first.")
        return
    
    print("📋 System Architecture:")
    print(f"   API Server (Address {API_ADDRESS}) → HTTP REST API → Dashboard (Port {DASH_PORT})")
    print()
    
    # Start API server
    api_proc = start_api_server()
    if not api_proc:
        return
    
    print("⏳ Waiting for API server to initialize...")
    
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
    print(f"🔧 API Server:        {API_ADDRESS}")
    print(f"   📄 Status page:    {API_ADDRESS}/")
    print(f"   📊 All devices:    {API_ADDRESS}/gcs/all")
    print(f"   🏥 Health check:   {API_ADDRESS}/health")
    print()
    print(f"📊 Groundboard:       http://{DASH_HOST}:{DASH_PORT}")
    print("   🎯 Live dashboard")
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
