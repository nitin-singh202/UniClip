"""
UniClip - Unified Application Launcher

Usage:
    python run.py             # Start the Flask web dashboard (default)
    python run.py web         # Start the Flask web dashboard on http://127.0.0.1:5000
    python run.py load-test   # Start in LOAD-TEST MODE (isolated SQLite, 0% Firestore)
    python run.py watcher     # Start the Windows desktop clipboard watcher
    python run.py all         # Run both web dashboard and clipboard watcher concurrently
"""

import sys
import os
import subprocess
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

def run_load_test():
    """Run Flask dashboard web application in isolated LOAD_TEST_MODE."""
    os.environ["LOAD_TEST_MODE"] = "1"
    os.environ["DEV_MOCK_AUTH"] = "1"
    from web.config import LoadTestConfig
    from web.app import create_app
    print("=" * 60)
    print("Starting UniClip in LOAD-TEST MODE...")
    print("Isolated Database: clipboard_load_test.db")
    print("Cloud Firestore: STRICTLY DISABLED (Fail-closed)")
    print("Mock Authentication: ACTIVE")
    print("URL: http://127.0.0.1:5000")
    print("=" * 60)
    app = create_app(LoadTestConfig)
    app.run(host="127.0.0.1", port=5000, debug=False)

def run_web():
    """Run Flask dashboard web application."""
    print("=" * 60)
    print("Starting UniClip Web Dashboard...")
    print("URL: http://127.0.0.1:5000")
    print("=" * 60)
    from web.app import create_app
    app = create_app()
    app.run(host="127.0.0.1", port=5000, debug=True)

def run_watcher():
    """Run Windows desktop clipboard watcher."""
    print("=" * 60)
    print("Starting UniClip Desktop Watcher...")
    print("Press Ctrl+C to stop.")
    print("=" * 60)
    import desktop_watcher
    desktop_watcher.main()

def run_all():
    """Run both web server and desktop watcher simultaneously."""
    print("=" * 60)
    print("Starting UniClip (Web + Watcher)...")
    print("Web: http://127.0.0.1:5000")
    print("Watcher: Active (Monitoring Windows clipboard)")
    print("Press Ctrl+C to terminate both services.")
    print("=" * 60)
    
    python_exe = sys.executable
    processes = []
    try:
        # Launch Web server
        p_web = subprocess.Popen([python_exe, "-m", "web.app"], cwd=str(ROOT_DIR))
        processes.append(p_web)
        
        # Launch Desktop watcher
        p_watcher = subprocess.Popen([python_exe, "desktop_watcher.py"], cwd=str(ROOT_DIR))
        processes.append(p_watcher)
        
        while True:
            time.sleep(1)
            # Check if either crashed
            for p in processes:
                if p.poll() is not None:
                    print(f"Process {p.pid} exited with code {p.returncode}.")
                    return
    except KeyboardInterrupt:
        print("\nStopping services...")
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
        print("UniClip services stopped.")

def main():
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else "web"
    
    if arg in ("load-test", "loadtest", "load_test", "load"):
        run_load_test()
    elif arg in ("web", "app", "dashboard", "server"):
        run_web()
    elif arg in ("watcher", "clip", "clipboard", "desktop"):
        run_watcher()
    elif arg in ("all", "both"):
        run_all()
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
