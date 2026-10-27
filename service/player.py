"""
YaSave playback service (python-for-android service "Player", own process).

Declared in buildozer.spec:
    services = Player:service/player.py:foregroundServiceType=mediaPlayback

The audio itself is played by the Java class org.yasave.media.YaSavePlayer
(MediaPlayer + MediaSession + MediaStyle notification). This script:
  * exposes a tiny JSON HTTP API on 127.0.0.1:58232 for the main app process;
  * forwards next / prev / ended from the notification and lock screen to the
    main app (which owns the queue and resolves stream URLs).
Every Java call is wrapped: if anything fails the service keeps running and the
app falls back to in-app playback.
"""
import json
import logging
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

SERVICE_PORT = 58232
APP_PORT = 58231

logging.basicConfig(level=logging.INFO, format="[YaSavePlayerSvc] %(levelname)s %(message)s")
log = logging.getLogger("player_service")

_player = None
_player_error = ""


def _init_player():
    global _player, _player_error
    try:
        from jnius import autoclass  # type: ignore
        PythonService = autoclass("org.kivy.android.PythonService")
        service = PythonService.mService
        if service is None:
            raise RuntimeError("PythonService.mService is null")
        YaSavePlayer = autoclass("org.yasave.media.YaSavePlayer")
        _player = YaSavePlayer.get(service)
        log.info("native player ready")
    except Exception as e:  # pragma: no cover - Android only
        _player = None
        _player_error = f"{type(e).__name__}: {e}"
        log.exception("native player init failed")


def _state():
    if _player is None:
        return {"state": "unavailable", "error": _player_error}
    try:
        return json.loads(_player.getStateJson())
    except Exception as e:
        log.exception("getStateJson failed")
        return {"state": "error", "error": str(e)}


def _command(data):
    cmd = data.get("cmd")
    if _player is None:
        raise RuntimeError(_player_error or "native player unavailable")
    if cmd == "play":
        _player.play(
            str(data.get("url") or ""),
            str(data.get("title") or ""),
            str(data.get("artist") or ""),
            str(data.get("cover") or ""),
            int(data.get("duration_ms") or 0),
            bool(data.get("has_prev")),
            bool(data.get("has_next")),
        )
    elif cmd == "pause":
        _player.pause()
    elif cmd == "resume":
        _player.resume()
    elif cmd == "toggle":
        _player.toggle()
    elif cmd == "seek":
        _player.seekTo(int(data.get("position_ms") or 0))
    elif cmd == "stop":
        _player.stop()
    elif cmd == "nav":
        _player.setNavigation(bool(data.get("has_prev")), bool(data.get("has_next")))
    else:
        raise ValueError(f"unknown command {cmd!r}")


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/state"):
            self._send(200, _state())
        elif self.path.startswith("/ping"):
            self._send(200, {"ok": True, "native": _player is not None, "error": _player_error})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}")
            _command(data)
            self._send(200, {"ok": True})
        except Exception as e:
            log.exception("command failed")
            self._send(500, {"error": str(e)})

    def log_message(self, *args):  # keep logcat quiet
        pass


class _Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _notify_app(direction, auto):
    """Ask the main app for the next/previous track; it resolves and plays it."""
    body = json.dumps({"dir": direction, "auto": auto}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{APP_PORT}/api/player/step", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=60).read()
    except Exception as e:
        log.warning(f"app step request failed: {e}")


def _command_loop():
    while True:
        try:
            cmd = _player.pollCommand() if _player is not None else None
        except Exception:
            log.exception("pollCommand failed")
            cmd = None
        if cmd in ("next", "ended"):
            threading.Thread(target=_notify_app, args=(1, cmd == "ended"), daemon=True).start()
        elif cmd == "prev":
            threading.Thread(target=_notify_app, args=(-1, False), daemon=True).start()
        time.sleep(0.25 if cmd is None else 0.05)


def main():
    _init_player()
    server = _Server(("127.0.0.1", SERVICE_PORT), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info(f"listening on {SERVICE_PORT}")
    _command_loop()


import os  # noqa: E402

# p4a runs the entrypoint as a script; the env check is a safety net in case it is imported
if __name__ == "__main__" or "PYTHON_SERVICE_ARGUMENT" in os.environ:
    main()
