"""OSC in and out (contract v0.3 §4).

OscOut         — the ONE path to SuperCollider. Every message goes through safety.limit().
                 After panic() it latches and refuses everything except further panics
                 until reset() (start of the next session). The keepalive stops too, so
                 SC's own watchdog (§7.1) also fades master.
KeepAlive      — /pathos/keepalive at 4 Hz for the life of the process.
SensorListener — /pathos/sensor/{present,proximity,heartbeat} on 0.0.0.0:9000. Only with --sensor
                 (parked this week). Also accepts /pathos/panic there, for a networked panic button.
NullSensor     — stand-in when the sensor is off: never alive, never present.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

from . import safety
from .safety import Calibration

log = logging.getLogger("pathos.osc")

SC_HOST, SC_PORT = "127.0.0.1", 57120
ORCH_HOST, ORCH_PORT = "0.0.0.0", 9000
PANIC_REPEATS = 3            # UDP can drop; panic is cheap to repeat


class OscOut:
    def __init__(self, cal: Calibration, *, dry: bool = False, sc: tuple[str, int] = (SC_HOST, SC_PORT),
                 printer: Callable[[str], None] = print):
        self.cal = cal
        self.dry = dry
        self.printer = printer
        self._client = None if dry else SimpleUDPClient(*sc)
        self._lock = threading.Lock()
        self._panicked = False
        self._t0 = time.monotonic()

    @property
    def panicked(self) -> bool:
        return self._panicked

    def reset(self) -> None:
        """Clear the panic latch (operator starts a new session)."""
        with self._lock:
            if self._panicked:
                log.warning("panic latch cleared")
            self._panicked = False

    def send(self, address: str, *args, quiet: bool = False) -> bool:
        """Limit and send. Returns False if suppressed by the panic latch."""
        safe = safety.limit(address, args, self.cal)
        with self._lock:
            if self._panicked and address != "/pathos/panic":
                return False
            self._emit(address, safe, quiet)
        return True

    def _emit(self, address: str, args: tuple, quiet: bool) -> None:
        if not quiet:
            line = f"{time.monotonic() - self._t0:8.2f}s  {address} {' '.join(_fmt(a) for a in args)}".rstrip()
            if self.dry:
                self.printer(line)
            else:
                log.info(line)
        if self._client is not None:
            self._client.send_message(address, list(args))

    def panic(self) -> None:
        """Everything to silence, then latch."""
        with self._lock:
            self._panicked = True
            for i in range(PANIC_REPEATS):
                self._emit("/pathos/panic", (), quiet=i > 0)
        log.warning("PANIC sent")


def _fmt(a) -> str:
    if isinstance(a, float):
        return f"{a:.4f}".rstrip("0").rstrip(".")
    return str(a)


class KeepAlive:
    """§4: /pathos/keepalive at 4 Hz, always. Suppressed by the panic latch like any other send."""

    def __init__(self, out: OscOut, hz: float = safety.KEEPALIVE_HZ):
        self.out = out
        self.period = 1.0 / hz
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="keepalive", daemon=True)

    def start(self) -> "KeepAlive":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _loop(self) -> None:
        while not self._stop.wait(self.period):
            try:
                self.out.send("/pathos/keepalive", quiet=True)
            except OSError as e:  # network hiccup must never kill the keepalive
                log.error("keepalive send failed: %s", e)


class SensorListener:
    """Node 04 reports. Thread-safe; polled by the session controller."""

    def __init__(self, host: str = ORCH_HOST, port: int = ORCH_PORT,
                 on_panic: Callable[[], None] | None = None, timeout_s: float = safety.SENSOR_TIMEOUT_S):
        self.host, self.port = host, port
        self.on_panic = on_panic
        self.timeout_s = timeout_s
        self._lock = threading.Lock()
        self._last_seen: float | None = None
        self._present = False
        self._present_since: float | None = None    # when present last became 1
        self._absent_since: float | None = None     # when present last became 0
        self.proximity_mm: int | None = None
        self._was_alive = False
        self._server: ThreadingOSCUDPServer | None = None

    def start(self) -> bool:
        d = Dispatcher()
        d.map("/pathos/sensor/proximity", self._on_proximity)
        d.map("/pathos/sensor/present", self._on_present)
        d.map("/pathos/sensor/heartbeat", self._on_heartbeat)
        d.map("/pathos/panic", self._on_panic)
        try:
            self._server = ThreadingOSCUDPServer((self.host, self.port), d)
        except OSError as e:
            log.error("cannot listen on %s:%d (%s); sensor disabled, use the operator keys", self.host, self.port, e)
            return False
        threading.Thread(target=self._server.serve_forever, name="sensor-osc", daemon=True).start()
        log.info("listening for sensor on %s:%d", self.host, self.port)
        return True

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    # -- handlers (server thread) --------------------------------------------
    def _on_heartbeat(self, _addr, *args) -> None:
        with self._lock:
            self._last_seen = time.monotonic()

    def _on_proximity(self, _addr, *args) -> None:
        with self._lock:
            self._last_seen = time.monotonic()
            if args:
                self.proximity_mm = int(args[0])

    def _on_present(self, _addr, *args) -> None:
        flag = bool(int(args[0])) if args else False
        now = time.monotonic()
        with self._lock:
            self._last_seen = now
            if flag and not self._present:
                self._present_since, self._absent_since = now, None
                log.info("sensor: present")
            elif not flag and self._present:
                self._absent_since, self._present_since = now, None
                log.info("sensor: absent")
            self._present = flag

    def _on_panic(self, _addr, *args) -> None:
        log.warning("/pathos/panic received on :%d", self.port)
        if self.on_panic:
            self.on_panic()

    # -- queries -------------------------------------------------------------
    def alive(self) -> bool:
        with self._lock:
            return self._last_seen is not None and time.monotonic() - self._last_seen <= self.timeout_s

    def present_for(self) -> float:
        """Seconds someone has been continuously present (0 if absent or sensor dead)."""
        with self._lock:
            if not self._present or self._present_since is None:
                return 0.0
            since = self._present_since
        return time.monotonic() - since if self.alive() else 0.0

    def absent_for(self) -> float:
        """Seconds continuously absent after having been present (0 if present, unknown, or sensor dead)."""
        with self._lock:
            if self._present or self._absent_since is None:
                return 0.0
            since = self._absent_since
        return time.monotonic() - since if self.alive() else 0.0

    def check_alarm(self) -> None:
        """§7.1: log loudly when the sensor heartbeat is missing for > 3 s."""
        alive = self.alive()
        if self._was_alive and not alive:
            log.error("SENSOR LOST: nothing on :%d for > %.0f s. Operator keys still work.", self.port, self.timeout_s)
        elif alive and not self._was_alive:
            log.info("sensor online")
        self._was_alive = alive


class NullSensor:
    def start(self) -> bool:
        return True

    def stop(self) -> None:
        pass

    def alive(self) -> bool:
        return False

    def present_for(self) -> float:
        return 0.0

    def absent_for(self) -> float:
        return 0.0

    def check_alarm(self) -> None:
        pass
