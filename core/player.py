"""
Playback controller (main app process).

Owns the queue and turns queue items into playable URLs. Playback itself happens:
  * on Android - in the native "Player" service (service/player.py + YaSavePlayer.java):
    MediaSession, notification in the shade, lock screen, background playback;
  * elsewhere, or if the service could not start - in the WebView <audio> element
    (the API returns {"native": false, "url": ...} and the page plays it).
"""
import hashlib
import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from .storage import get_download_directory, get_cache_dir, is_android

logger = logging.getLogger(__name__)

SERVICE_URL = "http://127.0.0.1:58232"
SERVICE_START_TIMEOUT = 12.0
AUDIO_EXTS = (".mp3", ".m4a", ".webm", ".ogg", ".opus", ".flac", ".aac", ".wav")


def _http(method: str, path: str, payload: Optional[dict] = None, timeout: float = 3.0) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        SERVICE_URL + path, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read() or b"{}")


def safe_audio_path(filename: str) -> Optional[str]:
    """Only files directly inside the download folder can be played or read."""
    if not filename:
        return None
    name = os.path.basename(filename)
    if name != filename or not name.lower().endswith(AUDIO_EXTS):
        return None
    path = os.path.join(get_download_directory(), name)
    return path if os.path.isfile(path) else None


def read_file_tags(path: str) -> Dict[str, Any]:
    """Title / artist / duration from tags, falling back to 'Artist - Title' filename."""
    base = os.path.splitext(os.path.basename(path))[0]
    artist, title = ("", base)
    if " - " in base:
        artist, title = base.split(" - ", 1)
    duration = 0
    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(path)
        if audio is not None:
            duration = int(getattr(audio.info, "length", 0) or 0)
            tags = audio.tags or {}
            t = tags.get("TIT2") or tags.get("\xa9nam") or tags.get("title")
            a = tags.get("TPE1") or tags.get("\xa9ART") or tags.get("artist")
            if t:
                title = str(t[0] if isinstance(t, list) else t)
            if a:
                artist = str(a[0] if isinstance(a, list) else a)
    except Exception as e:
        logger.debug(f"tags for {path}: {e}")
    return {"title": title, "artist": artist, "duration": duration}


def extract_cover(path: str) -> Optional[str]:
    """Embedded cover -> cached image file. Returns the file path or None."""
    try:
        st = os.stat(path)
        key = hashlib.md5(f"{path}|{st.st_mtime}|{st.st_size}".encode("utf-8")).hexdigest()
        out = os.path.join(get_cache_dir("covers"), key + ".jpg")
        if os.path.exists(out):
            return out
        from mutagen import File as MutagenFile
        audio = MutagenFile(path)
        data = None
        if audio is not None and audio.tags:
            for k in list(audio.tags.keys()):
                if str(k).startswith("APIC"):
                    data = audio.tags[k].data
                    break
            if data is None and "covr" in audio.tags:
                data = bytes(audio.tags["covr"][0])
        if data is None and hasattr(audio, "pictures") and audio.pictures:
            data = audio.pictures[0].data
        if not data:
            return None
        with open(out, "wb") as f:
            f.write(data)
        return out
    except Exception as e:
        logger.debug(f"cover for {path}: {e}")
        return None


class PlayerController:
    _instance = None

    def __init__(self):
        self.lock = threading.RLock()
        self.queue: List[Dict[str, Any]] = []
        self.index = -1
        self.current: Optional[Dict[str, Any]] = None   # public track info for the UI
        self.native_ok: Optional[bool] = None          # None = not tried yet
        self.native_error = ""
        self.notif_permission_asked = False
        self.resolve_seq = 0
        self.last_error = ""

    @classmethod
    def get(cls) -> "PlayerController":
        if cls._instance is None:
            cls._instance = PlayerController()
        return cls._instance

    # ------------------------------------------------------------------
    # Native service
    # ------------------------------------------------------------------

    def _request_notification_permission(self):
        if self.notif_permission_asked:
            return
        self.notif_permission_asked = True
        try:
            import sys
            if getattr(sys, "getandroidapilevel", lambda: 0)() < 33:
                return
            from android.permissions import request_permissions, check_permission  # type: ignore
            perm = "android.permission.POST_NOTIFICATIONS"
            if not check_permission(perm):
                request_permissions([perm])
        except Exception as e:
            logger.warning(f"notification permission request failed: {e}")

    def _ping(self) -> Optional[dict]:
        try:
            return _http("GET", "/ping", timeout=1.0)
        except Exception:
            return None

    def ensure_native(self) -> bool:
        """Starts the Android playback service once. False -> use in-app <audio>."""
        if not is_android():
            self.native_ok = False
            self.native_error = "not android"
            return False
        if self.native_ok:
            return True
        if self.native_ok is False and self.native_error and "timeout" not in self.native_error:
            return False

        self._request_notification_permission()
        info = self._ping()
        if info is None:
            try:
                from jnius import autoclass  # type: ignore
                activity = autoclass("org.kivy.android.PythonActivity").mActivity
                autoclass("org.yasave.yasave.ServicePlayer").start(activity, "")
            except Exception as e:
                self.native_ok = False
                self.native_error = f"service start failed: {e}"
                logger.exception("player service start failed")
                return False
            deadline = time.time() + SERVICE_START_TIMEOUT
            while time.time() < deadline:
                info = self._ping()
                if info is not None:
                    break
                time.sleep(0.25)
        if info is None:
            self.native_ok = False
            self.native_error = "service timeout"
            return False
        if not info.get("native"):
            self.native_ok = False
            self.native_error = info.get("error") or "native player unavailable"
            logger.error(f"native player unavailable: {self.native_error}")
            return False
        self.native_ok = True
        self.native_error = ""
        return True

    def prewarm(self):
        """Start the service in the background so the first play is instant."""
        if is_android():
            threading.Thread(target=self.ensure_native, daemon=True).start()

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------

    def _resolve(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """-> {"track": public info, "url": stream url or path, "web_url": for <audio>, "cover_native": ...}"""
        kind = item.get("type")
        if kind == "candidate":
            from .alt_sources import AlternativeSourcesManager
            c = item.get("candidate") or {}
            url = AlternativeSourcesManager.get_preview_audio_url(c)
            if not url:
                raise RuntimeError("Не удалось получить аудиопоток")
            cover = c.get("cover_url") or c.get("thumbnail") or ""
            track = {
                "id": c.get("id"),
                "title": c.get("title") or "",
                "artist": c.get("artist") or c.get("channel") or "",
                "cover": cover,
                "duration": int(c.get("duration") or 0),
                "source": c.get("source") or "",
                "kind": "candidate",
            }
            return {"track": track, "url": url, "web_url": url, "cover_native": cover}
        if kind == "file":
            path = safe_audio_path(item.get("filename", ""))
            if not path:
                raise RuntimeError("Файл не найден в папке загрузок")
            tags = read_file_tags(path)
            name = os.path.basename(path)
            q = urllib.parse.quote(name)
            cover_file = extract_cover(path)
            track = {
                "id": f"file:{name}",
                "title": tags["title"],
                "artist": tags["artist"],
                "cover": f"/api/player/art?file={q}" if cover_file else "",
                "duration": tags["duration"],
                "source": "Файл",
                "kind": "file",
            }
            return {"track": track, "url": path, "web_url": f"/api/player/file?file={q}", "cover_native": cover_file or ""}
        raise ValueError("Неизвестный элемент очереди")

    def _has_prev(self) -> bool:
        return self.index > 0

    def _has_next(self) -> bool:
        return 0 <= self.index < len(self.queue) - 1

    def _start(self, index: int) -> Dict[str, Any]:
        with self.lock:
            if not (0 <= index < len(self.queue)):
                raise IndexError("Нет трека в очереди")
            self.index = index
            self.resolve_seq += 1
            my_seq = self.resolve_seq
            item = self.queue[index]

        resolved = self._resolve(item)  # network: outside the lock

        with self.lock:
            if my_seq != self.resolve_seq:
                raise RuntimeError("Переключено на другой трек")
            self.current = resolved["track"]
            self.last_error = ""
            has_prev, has_next = self._has_prev(), self._has_next()

        if self.ensure_native():
            try:
                _http("POST", "/cmd", {
                    "cmd": "play",
                    "url": resolved["url"],
                    "title": resolved["track"]["title"],
                    "artist": resolved["track"]["artist"],
                    "cover": resolved["cover_native"],
                    "duration_ms": resolved["track"]["duration"] * 1000,
                    "has_prev": has_prev,
                    "has_next": has_next,
                }, timeout=5)
                return {"native": True, "track": self.current, "has_prev": has_prev, "has_next": has_next}
            except Exception as e:
                logger.exception("native play failed, falling back to web audio")
                self.native_ok = False
                self.native_error = f"play failed: {e}"
        return {"native": False, "url": resolved["web_url"], "track": self.current,
                "has_prev": has_prev, "has_next": has_next}

    def play_queue(self, items: List[Dict[str, Any]], index: int) -> Dict[str, Any]:
        items = [i for i in (items or []) if isinstance(i, dict)][:200]
        if not items:
            raise ValueError("Пустая очередь")
        with self.lock:
            self.queue = items
        return self._start(max(0, min(int(index or 0), len(items) - 1)))

    def step(self, direction: int, auto: bool = False) -> Dict[str, Any]:
        with self.lock:
            target = self.index + (1 if direction > 0 else -1)
            if not (0 <= target < len(self.queue)):
                if auto and self.native_ok:
                    # End of queue: leave the finished track paused in the notification
                    return {"native": True, "track": self.current, "end": True}
                raise IndexError("Это последний трек в очереди" if direction > 0 else "Это первый трек")
        # Skip items that fail to resolve (e.g. a removed video), at most 3 in a row
        last_exc: Optional[Exception] = None
        for _ in range(3):
            try:
                return self._start(target)
            except Exception as e:
                last_exc = e
                logger.warning(f"skip unplayable queue item {target}: {e}")
                with self.lock:
                    target += 1 if direction > 0 else -1
                    if not (0 <= target < len(self.queue)):
                        break
        self.last_error = str(last_exc) if last_exc else ""
        raise RuntimeError(f"Не удалось воспроизвести: {last_exc}")

    def command(self, cmd: str, position_ms: int = 0) -> Dict[str, Any]:
        if cmd in ("next", "prev"):
            return self.step(1 if cmd == "next" else -1)
        if cmd == "stop":
            with self.lock:
                self.current = None
        if self.native_ok:
            payload = {"cmd": cmd}
            if cmd == "seek":
                payload["position_ms"] = int(position_ms)
            _http("POST", "/cmd", payload, timeout=3)
        return {"ok": True}

    def state(self) -> Dict[str, Any]:
        with self.lock:
            base = {
                "track": self.current,
                "has_prev": self._has_prev(),
                "has_next": self._has_next(),
                "index": self.index,
                "queue_length": len(self.queue),
                "native": bool(self.native_ok),
                "native_error": self.native_error,
                "error": self.last_error,
            }
        if self.native_ok:
            try:
                svc = _http("GET", "/state", timeout=1.5)
                base["playback"] = svc
                if svc.get("state") == "idle" and base["track"] is not None and svc.get("seq", 0) > 0:
                    base["track"] = None  # stopped from the notification
                    with self.lock:
                        self.current = None
            except Exception as e:
                base["playback"] = {"state": "unknown", "error": str(e)}
        return base
