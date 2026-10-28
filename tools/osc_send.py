"""Send one OSC message. Fakes any node for standalone testing.

  python tools/osc_send.py /pathos/chair/heartbeat 60 0.1 0.7
  python tools/osc_send.py --port 9000 /pathos/sensor/present 1
  python tools/osc_send.py /pathos/diagram/position habit-build habit 3 5 0.75
"""
import argparse
from pythonosc.udp_client import SimpleUDPClient


def parse(v: str):
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return v


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=57120)
    ap.add_argument("address")
    ap.add_argument("args", nargs="*")
    a = ap.parse_args()
    SimpleUDPClient(a.host, a.port).send_message(a.address, [parse(x) for x in a.args])
    print(f"-> {a.host}:{a.port} {a.address} {a.args}")
