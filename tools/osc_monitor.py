"""Print every OSC message arriving on a port.

  python tools/osc_monitor.py --port 9000
"""
import argparse
import time
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=9000)
    a = ap.parse_args()
    d = Dispatcher()
    d.set_default_handler(lambda addr, *args: print(f"{time.strftime('%H:%M:%S')} {addr} {list(args)}"))
    print(f"listening on {a.host}:{a.port}")
    BlockingOSCUDPServer((a.host, a.port), d).serve_forever()
