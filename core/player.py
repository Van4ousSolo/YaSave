"""
Playback controller (main app process).

Owns the queue and turns queue items into playable URLs. Playback itself happens:
  * on Android - natively in this process: YaSavePlayer.java (MediaPlayer, MediaSession,
    MediaStyle notification) + YaSaveMediaService (foreground, keeps the app alive);
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
from typing import Any, Dict, List, Optional

from .storage import get_download_directory, get_cache_dir, is_android

logger = logging.getLogger(__name__)

AUDIO_EXTS = (".mp3", ".m4a", ".webm", ".ogg", ".opus", ".flac", ".aac", ".wav")


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


PREV_RESTART_SEC = 3


class NativeBridge:
    """pyjnius wrapper around org.yasave.media.YaSavePlayer (same process, no IPC)."""

    def __init__(self):
        from . import android_bridge as ab
        # Class objects come from the main-thread preload (see android_bridge)
        self._cls = ab.jclass("org.yasave.media.YaSavePlayer")
        logger.info("native: step 1 - class org.yasave.media.YaSavePlayer found")
        self.player = self._cls.get(ab.activity())
        logger.info("native: step 2 - YaSavePlayer instance created")

    def state(self) -> Dict[str, Any]:
        return json.loads(self.player.getStateJson())


class PlayerController:
    _instance = None

    def __init__(self):
        self.lock = threading.RLock()
        self.queue: List[Dict[str, Any]] = []
        self.index = -1
        self.current: Optional[Dict[str, Any]] = None   # public track info for the UI
        self.native: Optional[NativeBridge] = None
        self.native_ok: Optional[bool] = None          # None = not tried yet
        self.native_error = ""
        self.notif_permission_asked = False
        self.resolve_seq = 0
        self.last_error = ""
        self._poller: Optional[threading.Thread] = None

    @classmethod
    def get(cls) -> "PlayerController":
        if cls._instance is None:
            cls._instance = PlayerController()
        return cls._instance

    # ------------------------------------------------------------------
    # Native layer
    # ------------------------------------------------------------------

    def request_notification_permission(self, force: bool = False) -> str:
        """Android 13+: runtime POST_NOTIFICATIONS. Returns granted / requested / not_needed / error."""
        if self.notif_permission_asked and not force:
            return "asked"
        self.notif_permission_asked = True
        try:
            import sys
            if getattr(sys, "getandroidapilevel", lambda: 0)() < 33:
                return "not_needed"
            from android.permissions import request_permissions, check_permission  # type: ignore
            perm = "android.permission.POST_NOTIFICATIONS"
            if check_permission(perm):
                logger.info("native: POST_NOTIFICATIONS already granted")
                return "granted"
            logger.info("native: requesting POST_NOTIFICATIONS")
            request_permissions([perm])
            return "requested"
        except Exception as e:
            logger.exception("native: notification permission request failed")
            return f"error: {e}"

    def ensure_native(self) -> bool:
        """Creates the Java player once. False -> the page plays through <audio>."""
        if not is_android():
            self.native_ok = False
            self.native_error = "не Android"
            return False
        if self.native_ok:
            return True
        if self.native_ok is False:
            return False
        logger.info("native: init step 1/2 - notification permission")
        self.request_notification_permission()
        logger.info("native: init step 2/2 - YaSavePlayer via pyjnius")
        try:
            self.native = NativeBridge()
        except Exception as e:
            self.native_ok = False
            self.native_error = f"{type(e).__name__}: {e}"
            logger.exception("native: init failed, falling back to in-app audio")
            return False
        self.native_ok = True
        self.native_error = ""
        self.apply_progress_mode()
        self._start_poller()
        return True

    def apply_progress_mode(self, mode: Optional[str] = None) -> str:
        """Notification progress: auto | session (system seekbar) | bar (setProgress)."""
        from .config import ConfigManager
        cfg = ConfigManager.get_instance()
        if mode is not None:
            if mode not in ("auto", "session", "bar"):
                raise ValueError("Режим: auto, session или bar")
            cfg.data["notif_progress"] = mode
            cfg.save()
        mode = cfg.data.get("notif_progress") or "auto"
        if self.native_ok and self.native:
            try:
                self.native.player.setProgressMode(mode)
                logger.info(f"native: notification progress mode = {mode}")
            except Exception:
                logger.exception("native: setProgressMode failed")
        return mode

    def prewarm(self):
        if is_android():
            threading.Thread(target=self.ensure_native, daemon=True).start()

    def _start_poller(self):
        """next / prev / ended pressed in the shade or lock screen -> resolve here."""
        if self._poller is not None:
            return

        def loop():
            logger.info("native: command poller started")
            while True:
                try:
                    cmd = self.native.player.pollCommand() if self.native else None
                except Exception:
                    logger.exception("native: pollCommand failed")
                    cmd = None
                if cmd:
                    logger.info(f"native: command from system player: {cmd}")
                    try:
                        if cmd in ("next", "ended"):
                            self.step(1, auto=(cmd == "ended"))
                        elif cmd == "prev":
                            self.step(-1)
                        elif cmd == "stop":
                            with self.lock:
                                self.current = None
                    except Exception as e:
                        logger.warning(f"native: command {cmd} failed: {e}")
                time.sleep(0.05 if cmd else 0.25)

        self._poller = threading.Thread(target=loop, daemon=True, name="yasave-player-commands")
        self._poller.start()

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
            self.resolve_seq += 1
            my_seq = self.resolve_seq
            item = self.queue[index]

        logger.info(f"player: resolving queue item {index + 1}/{len(self.queue)} ({item.get('type')})")
        resolved = self._resolve(item)  # network: outside the lock

        with self.lock:
            if my_seq != self.resolve_seq:
                raise RuntimeError("Переключено на другой трек")
            # The index moves only once the item is really playable
            self.index = index
            self.current = resolved["track"]
            self.last_error = ""
            has_prev, has_next = self._has_prev(), self._has_next()

        if self.ensure_native():
            try:
                t = resolved["track"]
                self.native.player.play(resolved["url"], t["title"], t["artist"], resolved["cover_native"],
                                        int(t["duration"]) * 1000, has_prev, has_next)
                logger.info(f"player: native play '{t['title']}' ({index + 1}/{len(self.queue)})")
                return {"native": True, "track": self.current, "has_prev": has_prev, "has_next": has_next}
            except Exception as e:
                logger.exception("player: native play failed, falling back to in-app audio")
                self.native_ok = False
                self.native_error = f"play: {type(e).__name__}: {e}"
        logger.info(f"player: web play '{resolved['track']['title']}' ({self.native_error or 'desktop'})")
        return {"native": False, "url": resolved["web_url"], "track": self.current,
                "has_prev": has_prev, "has_next": has_next}

    def play_queue(self, items: List[Dict[str, Any]], index: int) -> Dict[str, Any]:
        items = [i for i in (items or []) if isinstance(i, dict)][:200]
        if not items:
            raise ValueError("Пустая очередь")
        with self.lock:
            self.queue = items
            self.index = -1
        return self._start(max(0, min(int(index or 0), len(items) - 1)))

    def step(self, direction: int, auto: bool = False) -> Dict[str, Any]:
        with self.lock:
            target = self.index + (1 if direction > 0 else -1)
            in_range = 0 <= target < len(self.queue)
        if not in_range:
            if direction < 0:
                # First track: "back" restarts it
                self.command("seek", 0)
                with self.lock:
                    return {"native": bool(self.native_ok), "restart": True, "track": self.current,
                            "has_prev": self._has_prev(), "has_next": self._has_next()}
            if auto:
                # End of the queue: the finished track stays (paused at the end)
                return {"native": bool(self.native_ok), "end": True, "track": self.current}
            raise IndexError("Это последний трек в очереди")
        # Skip items that fail to resolve (e.g. a removed video), at most 3 in a row
        last_exc: Optional[Exception] = None
        for _ in range(3):
            try:
                return self._start(target)
            except Exception as e:
                last_exc = e
                logger.warning(f"player: skip unplayable queue item {target}: {e}")
                target += 1 if direction > 0 else -1
                with self.lock:
                    if not (0 <= target < len(self.queue)):
                        break
        self.last_error = str(last_exc) if last_exc else ""
        raise RuntimeError(f"Не удалось воспроизвести: {last_exc}")

    def previous(self, position_sec: float) -> Dict[str, Any]:
        """In-app "back": restart after 3 s (or on the first track), otherwise previous track."""
        if position_sec > PREV_RESTART_SEC or not self._has_prev():
            self.command("seek", 0)
            with self.lock:
                return {"native": bool(self.native_ok), "restart": True, "track": self.current,
                        "has_prev": self._has_prev(), "has_next": self._has_next()}
        return self.step(-1)

    def command(self, cmd: str, position_ms: int = 0) -> Dict[str, Any]:
        if cmd in ("next", "prev"):
            return self.step(1 if cmd == "next" else -1)
        if cmd == "stop":
            with self.lock:
                self.current = None
        if self.native_ok and self.native:
            p = self.native.player
            if cmd == "toggle":
                p.toggle()
            elif cmd == "pause":
                p.pause()
            elif cmd == "resume":
                p.resume()
            elif cmd == "seek":
                p.seekTo(int(position_ms))
            elif cmd == "stop":
                p.stop()
            elif cmd == "refresh":
                p.refresh()
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
        if self.native_ok and self.native:
            try:
                svc = self.native.state()
                base["playback"] = svc
                if svc.get("state") == "idle" and base["track"] is not None and svc.get("seq", 0) > 0:
                    base["track"] = None  # stopped from the notification
                    with self.lock:
                        self.current = None
            except Exception as e:
                base["playback"] = {"state": "unknown", "error": str(e)}
        return base

    # ------------------------------------------------------------------
    # Background playback helpers (Settings screen)
    # ------------------------------------------------------------------

    def system_status(self) -> Dict[str, Any]:
        from . import android_bridge as ab
        out: Dict[str, Any] = {"android": is_android(), "native": bool(self.native_ok),
                               "native_error": self.native_error}
        if not is_android():
            return out
        try:
            out.update(ab.system_status())
        except Exception as e:
            out["status_error"] = f"{type(e).__name__}: {e}"
            logger.exception("status: framework checks failed")
        self.ensure_native()
        out["native"] = bool(self.native_ok)
        out["native_error"] = self.native_error
        if self.native:
            try:
                out["playback"] = self.native.state()
            except Exception as e:
                out["playback_error"] = str(e)
        return out

    def open_settings(self, which: str) -> Dict[str, Any]:
        from . import android_bridge as ab
        if not is_android():
            raise RuntimeError("Доступно только в Android-приложении")
        if which == "permission":
            return {"result": ab.request_notification_permission()}
        return {"opened": ab.open_settings(which)}

    def self_test(self) -> Dict[str, Any]:
        """Settings -> "Проверить плеер в шторке": every step with a short reason."""
        steps: List[Dict[str, Any]] = []

        def step(name, ok, detail=""):
            steps.append({"name": name, "ok": ok, "detail": detail})
            logger.info(f"self-test: {name}: {'OK' if ok else 'FAIL'} {detail}")
            return ok

        if not is_android():
            step("Android", False, "проверка возможна только на телефоне")
            return {"steps": steps}
        from . import android_bridge as ab
        try:
            ab.jclass("org.yasave.media.YaSavePlayer")
            step("Класс YaSavePlayer найден", True)
        except Exception as e:
            step("Класс YaSavePlayer найден", False, str(e)[:300])
            return {"steps": steps}
        if not step("Плеер создан", self.ensure_native(), self.native_error):
            return {"steps": steps}
        st = ab.system_status()
        perm = st.get("notification_permission", {})
        step("Разрешение на уведомления", perm.get("value") is True,
             perm.get("reason") or ("" if perm.get("value") else "не выдано"))
        try:
            busy = (self.current is not None)
            if not busy:
                self.native.player.startSelfTest()
            deadline = time.time() + 6
            pb: Dict[str, Any] = {}
            while time.time() < deadline:
                pb = self.native.state()
                if pb.get("foreground") or pb.get("notification_error"):
                    break
                time.sleep(0.3)
            step("Канал уведомлений создан", bool(pb.get("channel")))
            step("MediaSession создана", bool(pb.get("session")))
            step("MediaSession активна", bool(pb.get("session_active")))
            step("Сервис запущен", bool(pb.get("service")), pb.get("notification_error") or "")
            step("Уведомление в шторке (foreground)", bool(pb.get("foreground")),
                 pb.get("notification_error") or ("" if pb.get("foreground") else "нет ответа за 6 с"))
            if not busy:
                # keep the test notification for a while so it can be seen, then remove it
                threading.Timer(12.0, lambda: self.native.player.endSelfTest()).start()
        except Exception as e:
            logger.exception("self-test failed")
            step("Тестовое уведомление", False, f"{type(e).__name__}: {e}"[:300])
        return {"steps": steps}
