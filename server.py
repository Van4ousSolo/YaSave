import os
import sys
import json
import time
import threading
import subprocess
import logging
from typing import Dict, Any
from wsgiref.simple_server import WSGIServer, make_server
from socketserver import ThreadingMixIn

from bottle import Bottle, request, response, static_file, run, ServerAdapter

from core.config import ConfigManager
from core.storage import get_download_directory, sanitize_filename
from core.auth import AuthManager
from core.yandex_api import YandexParser, YandexDownloader
from core.alt_sources import AlternativeSourcesManager
from core.player import PlayerController, safe_audio_path, extract_cover

logger = logging.getLogger(__name__)

# Multi-threaded WSGI server adapter so parallel requests never block each other
class ThreadedWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True
    allow_reuse_address = True

class ThreadedWSGIAdapter(ServerAdapter):
    def run(self, handler):
        server = make_server(self.host, self.port, handler, server_class=ThreadedWSGIServer)
        server.serve_forever()

app = Bottle()

# Global re-entrant lock to safely prevent nested deadlocks
download_lock = threading.RLock()
download_state: Dict[str, Any] = {
    "is_downloading": False,
    "percent": 0.0,
    "downloaded_mb": 0.0,
    "total_mb": 0.0,
    "speed": "",
    "status": "Готов",
    "error": None,
    "filepath": None,
    "complete": False,
    "quality": None
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

def reset_download_state():
    with download_lock:
        download_state["is_downloading"] = False
        download_state["percent"] = 0.0
        download_state["downloaded_mb"] = 0.0
        download_state["total_mb"] = 0.0
        download_state["speed"] = ""
        download_state["status"] = "Готов"
        download_state["error"] = None
        download_state["filepath"] = None
        download_state["complete"] = False
        download_state["quality"] = None

# Static files
@app.route('/')
def index():
    return static_file('index.html', root=WEB_DIR)

@app.route('/assets/<filename:path>')
def serve_assets(filename):
    if os.path.exists(os.path.join(ASSETS_DIR, filename)):
        return static_file(filename, root=ASSETS_DIR)
    return static_file(filename, root=os.path.join(WEB_DIR, 'assets'))

@app.route('/<filepath:path>')
def serve_static(filepath):
    return static_file(filepath, root=WEB_DIR)

# --- API ENDPOINTS ---

# Status caching (avoids hammering Yandex API and blocking requests)
_status_cache = {
    "token": None,
    "timestamp": 0.0,
    "result": None
}

def invalidate_status_cache():
    _status_cache["token"] = None
    _status_cache["timestamp"] = 0.0
    _status_cache["result"] = None

@app.route('/api/status', method='GET')
def api_status():
    config = ConfigManager.get_instance()
    token = config.token
    user_name = config.user_name or "Не авторизован"
    has_plus = config.has_plus
    is_valid = bool(token and config.user_name)

    now = time.time()
    if token:
        if _status_cache["token"] == token and (now - _status_cache["timestamp"] < 300) and _status_cache["result"]:
            cached = _status_cache["result"]
            is_valid = cached["is_valid"]
            user_name = cached["user_name"]
            has_plus = cached["has_plus"]
        elif config.user_name:
            # We already have saved user profile from previous session
            is_valid = True
            user_name = config.user_name
            has_plus = config.has_plus
            _status_cache["token"] = token
            _status_cache["timestamp"] = now
            _status_cache["result"] = {
                "is_valid": True,
                "user_name": user_name,
                "has_plus": has_plus
            }
            # Background verify without blocking frontend launch
            def verify_bg():
                try:
                    auth = AuthManager()
                    v_ok, v_name = auth.validate_token(token)
                    if v_ok:
                        v_plus = "Плюс активен" in v_name
                        config.user_name = v_name
                        config.has_plus = v_plus
                        _status_cache["result"] = {
                            "is_valid": True,
                            "user_name": v_name,
                            "has_plus": v_plus
                        }
                    else:
                        if "Неверный токен" in v_name:
                            config.user_name = ""
                            config.has_plus = False
                            _status_cache["result"] = {
                                "is_valid": False,
                                "user_name": "Не авторизован",
                                "has_plus": False
                            }
                except Exception:
                    pass
            threading.Thread(target=verify_bg, daemon=True).start()
        else:
            # First time: validate synchronously and save
            auth = AuthManager()
            is_valid, user_name = auth.validate_token(token)
            has_plus = "Плюс активен" in user_name
            if is_valid:
                config.user_name = user_name
                config.has_plus = has_plus
            _status_cache["token"] = token
            _status_cache["timestamp"] = now
            _status_cache["result"] = {
                "is_valid": is_valid,
                "user_name": user_name,
                "has_plus": has_plus
            }

    return {
        "token_present": bool(token),
        "is_valid": is_valid,
        "user_name": user_name,
        "has_plus": has_plus,
        "theme": config.theme,
        "accent_color": config.accent_color,
        "download_dir": get_download_directory(),
        "spotify_configured": bool(config.spotify_client_id and config.spotify_client_secret),
        "spotify_client_id": config.spotify_client_id
    }

@app.route('/api/track_info', method='POST')
def api_track_info():
    data = request.json or {}
    url = data.get("url", "").strip()
    track_id = YandexParser.extract_track_id(url)
    if not track_id:
        response.status = 400
        return {"error": "Не удалось распознать ссылку на трек или ID."}

    try:
        downloader = YandexDownloader()
        info = downloader.get_track_info(track_id)
        # remove un-serializable raw_track
        info_cleaned = {k: v for k, v in info.items() if k != "raw_track"}
        # Real stream quality for the card badge (never blocks the card on errors)
        try:
            info_cleaned["quality"] = downloader.probe_quality(track_id)
        except Exception as qe:
            logger.warning(f"quality probe failed: {qe}")
            info_cleaned["quality"] = None
        return {"track": info_cleaned}
    except Exception as e:
        response.status = 500
        return {"error": str(e)}

@app.route('/api/download_ym', method='POST')
def api_download_ym():
    with download_lock:
        if download_state["is_downloading"]:
            response.status = 409
            return {"error": "Загрузка уже выполняется"}
        reset_download_state()
        download_state["is_downloading"] = True
        download_state["status"] = "Подготовка к скачиванию..."

    data = request.json or {}
    track_info = data.get("track_info")
    if not track_info:
        reset_download_state()
        response.status = 400
        return {"error": "Данные трека не переданы"}

    def worker():
        def on_progress(percent, dl_mb, tot_mb, speed_str):
            with download_lock:
                download_state["percent"] = round(percent, 1)
                download_state["downloaded_mb"] = dl_mb
                download_state["total_mb"] = tot_mb
                download_state["speed"] = speed_str

        def on_status(status_text):
            with download_lock:
                download_state["status"] = status_text

        def on_quality(q):
            with download_lock:
                download_state["quality"] = q

        try:
            downloader = YandexDownloader()
            filepath = downloader.download_track(
                track_info=track_info,
                on_progress=on_progress,
                on_status=on_status,
                on_quality=on_quality
            )
            with download_lock:
                download_state["filepath"] = filepath
                download_state["complete"] = True
                download_state["is_downloading"] = False
                download_state["percent"] = 100.0
        except Exception as e:
            with download_lock:
                download_state["error"] = str(e)
                download_state["is_downloading"] = False
                download_state["status"] = f"Ошибка: {str(e)}"

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return {"status": "started"}

@app.route('/api/ym_search', method='POST')
def api_ym_search():
    data = request.json or {}
    query = (data.get("query") or "").strip()
    if not query:
        response.status = 400
        return {"error": "Введите запрос"}
    try:
        tracks = YandexDownloader().search_tracks(query, limit=20)
        return {"tracks": tracks}
    except Exception as e:
        response.status = 500
        return {"error": str(e)}

@app.route('/api/search_uncensored', method='POST')
def api_search_uncensored():
    data = request.json or {}
    query = (data.get("query") or "").strip()
    if not query:
        # Backward compatibility with {artist, title}
        query = f"{data.get('artist', '')} {data.get('title', '')}".strip()
    source = (data.get("source") or "all").strip().lower()
    try:
        ref_duration = int(data.get("ref_duration") or 0)
    except (TypeError, ValueError):
        ref_duration = 0
    if not query:
        response.status = 400
        return {"error": "Введите запрос для поиска"}

    try:
        return AlternativeSourcesManager.search_candidates(query, source=source, ref_duration=ref_duration)
    except Exception as e:
        response.status = 500
        return {"error": str(e)}

@app.route('/api/get_preview_url', method='POST')
def api_get_preview():
    data = request.json or {}
    candidate = data.get("candidate") or ({"url": data["url"]} if data.get("url") else None)
    if not candidate:
        response.status = 400
        return {"error": "Не передан трек для предпрослушивания"}

    try:
        preview_url = AlternativeSourcesManager.get_preview_audio_url(candidate)
        if not preview_url:
            raise RuntimeError("Не удалось получить аудиопоток")
        return {"preview_url": preview_url}
    except Exception as e:
        response.status = 500
        return {"error": str(e)}

# --- PLAYER (native Android service or in-app <audio>) ---

def _player_call(fn):
    try:
        return fn()
    except (ValueError, IndexError) as e:
        response.status = 400
        return {"error": str(e)}
    except Exception as e:
        logger.exception("player error")
        response.status = 500
        return {"error": str(e)}

@app.route('/api/player/play', method='POST')
def api_player_play():
    data = request.json or {}
    logger.info(f"api: player/play {len(data.get('items') or [])} items, index {data.get('index')}")
    return _player_call(lambda: PlayerController.get().play_queue(data.get("items") or [], data.get("index") or 0))

@app.route('/api/player/step', method='POST')
def api_player_step():
    data = request.json or {}
    return _player_call(lambda: PlayerController.get().step(int(data.get("dir") or 1), bool(data.get("auto"))))

@app.route('/api/player/previous', method='POST')
def api_player_previous():
    data = request.json or {}
    return _player_call(lambda: PlayerController.get().previous(float(data.get("position") or 0)))

@app.route('/api/player/progress_mode', method='POST')
def api_player_progress_mode():
    data = request.json or {}
    return _player_call(lambda: {"mode": PlayerController.get().apply_progress_mode(data.get("mode"))})

@app.route('/api/player/selftest', method='POST')
def api_player_selftest():
    return _player_call(lambda: PlayerController.get().self_test())

@app.route('/api/logs', method='GET')
def api_logs():
    from core import applog
    return {"text": applog.text()}

@app.route('/api/logs/client', method='POST')
def api_logs_client():
    from core import applog
    data = request.json or {}
    applog.add("js", str(data.get("msg") or ""))
    return {"ok": True}

@app.route('/api/logs/save', method='POST')
def api_logs_save():
    from core import applog
    def save():
        path = os.path.join(get_download_directory(), f"yasave-log-{time.strftime('%Y%m%d-%H%M%S')}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(applog.text())
        logger.info(f"log saved to {path}")
        return {"path": path}
    return _player_call(save)

@app.route('/api/logs/share', method='POST')
def api_logs_share():
    from core import applog, android_bridge
    def share():
        if not android_bridge.is_android():
            raise RuntimeError("Поделиться можно только в Android-приложении")
        return {"shared": android_bridge.share_text("YaSave: лог плеера", applog.text())}
    return _player_call(share)

@app.route('/api/system/status', method='GET')
def api_system_status():
    return _player_call(lambda: PlayerController.get().system_status())

@app.route('/api/system/open', method='POST')
def api_system_open():
    data = request.json or {}
    return _player_call(lambda: PlayerController.get().open_settings(str(data.get("which") or "app")))

@app.route('/api/player/command', method='POST')
def api_player_command():
    data = request.json or {}
    return _player_call(lambda: PlayerController.get().command(str(data.get("cmd") or ""), int(data.get("position_ms") or 0)))

@app.route('/api/player/state', method='GET')
def api_player_state():
    return _player_call(lambda: PlayerController.get().state())

@app.route('/api/player/file', method='GET')
def api_player_file():
    path = safe_audio_path(request.query.getunicode("file", "") or "")
    if not path:
        response.status = 404
        return {"error": "Файл не найден"}
    return static_file(os.path.basename(path), root=os.path.dirname(path))

@app.route('/api/player/art', method='GET')
def api_player_art():
    path = safe_audio_path(request.query.getunicode("file", "") or "")
    cover = extract_cover(path) if path else None
    if not cover:
        response.status = 404
        return {"error": "Нет обложки"}
    return static_file(os.path.basename(cover), root=os.path.dirname(cover), mimetype="image/jpeg")

@app.route('/api/quality_report', method='POST')
def api_quality_report():
    data = request.json or {}
    track_id = YandexParser.extract_track_id(str(data.get("track_id") or data.get("url") or ""))
    if not track_id:
        response.status = 400
        return {"error": "Сначала выберите трек во вкладке «Скачать»"}
    return _player_call(lambda: YandexDownloader().quality_report(track_id))

@app.route('/api/diagnostics', method='GET')
def api_diagnostics():
    from core.alt_sources import run_diagnostics
    return _player_call(run_diagnostics)

@app.route('/api/spotify_credentials', method='POST')
def api_spotify_credentials():
    from core.alt_sources import SpotifyClient
    data = request.json or {}
    cfg = ConfigManager.get_instance()
    new_id = (data.get("client_id") or "").strip()
    new_secret = (data.get("client_secret") or "").strip()
    old_id, old_secret = cfg.spotify_client_id, cfg.spotify_client_secret

    # Same ID with the (hidden) secret left blank: keep the saved keys
    if new_id and not new_secret and new_id == old_id and old_secret:
        return {"success": True, "configured": True}

    # Empty fields = back to the built-in keys
    if not (new_id and new_secret):
        cfg.set_spotify_credentials("", "")
        SpotifyClient.reset()
        return {"success": True, "configured": False}

    # User keys are saved only if Spotify accepts them
    cfg.set_spotify_credentials(new_id, new_secret)
    SpotifyClient.reset()
    try:
        SpotifyClient.get_token()
        return {"success": True, "configured": True}
    except Exception as e:
        cfg.set_spotify_credentials(old_id, old_secret)
        SpotifyClient.reset()
        response.status = 400
        return {"success": False, "configured": bool(old_id and old_secret), "error": str(e)}

@app.route('/api/download_alternative', method='POST')
def api_download_alt():
    with download_lock:
        if download_state["is_downloading"]:
            response.status = 409
            return {"error": "Загрузка уже выполняется"}
        reset_download_state()
        download_state["is_downloading"] = True
        download_state["status"] = "Загрузка альтернативного трека..."

    data = request.json or {}
    candidate = data.get("candidate")
    ym_track = data.get("ym_track")  # optional: original Yandex track tags
    if not candidate:
        reset_download_state()
        response.status = 400
        return {"error": "Не переданы параметры для скачивания"}

    def worker():
        def on_progress(percent, dl_mb, tot_mb, speed_str):
            with download_lock:
                download_state["percent"] = round(percent, 1)
                download_state["downloaded_mb"] = dl_mb
                download_state["total_mb"] = tot_mb
                download_state["speed"] = speed_str

        def on_status(status_text):
            with download_lock:
                download_state["status"] = status_text

        try:
            filepath = AlternativeSourcesManager.download_alternative(
                candidate=candidate,
                ym_track_info=ym_track,
                on_progress=on_progress,
                on_status=on_status
            )
            with download_lock:
                download_state["filepath"] = filepath
                download_state["complete"] = True
                download_state["is_downloading"] = False
                download_state["percent"] = 100.0
                download_state["status"] = "Альтернативный трек успешно сохранён!"
        except Exception as e:
            with download_lock:
                download_state["error"] = str(e)
                download_state["is_downloading"] = False
                download_state["status"] = f"Ошибка: {str(e)}"

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return {"status": "started"}

@app.route('/api/download_progress', method='GET')
def api_download_progress():
    with download_lock:
        return dict(download_state)

@app.route('/api/auth/device_code', method='POST')
def api_device_code():
    auth = AuthManager()
    try:
        data = auth.request_device_flow()
        return data
    except Exception as e:
        response.status = 500
        return {"error": str(e)}

@app.route('/api/auth/poll_token', method='GET')
def api_poll_token():
    device_code = request.query.get('code')
    if not device_code:
        response.status = 400
        return {"error": "Код устройства отсутствует"}

    from yandex_music import Client
    from yandex_music.exceptions import DeviceAuthError
    client = Client()
    try:
        oauth_token = client.poll_device_token(device_code)
        if oauth_token and oauth_token.access_token:
            tok = oauth_token.access_token
            cfg = ConfigManager.get_instance()
            cfg.token = tok
            auth = AuthManager()
            is_valid, msg = auth.validate_token(tok)
            if is_valid:
                cfg.user_name = msg
                cfg.has_plus = ("Плюс активен" in msg)
            invalidate_status_cache()
            return {"success": True, "token": tok, "user_name": cfg.user_name, "has_plus": cfg.has_plus}
        return {"success": False, "pending": True}
    except DeviceAuthError as e:
        return {"success": False, "expired": "expired" in str(e).lower(), "error": str(e)}
    except Exception as e:
        return {"success": False, "pending": True, "error": str(e)}

@app.route('/api/auth/save_token', method='POST')
def api_save_token():
    data = request.json or {}
    tok = data.get("token", "").strip()
    if not tok:
        response.status = 400
        return {"error": "Токен не может быть пустым"}

    auth = AuthManager()
    is_valid, msg = auth.validate_token(tok)
    if is_valid:
        cfg = ConfigManager.get_instance()
        cfg.token = tok
        cfg.user_name = msg
        cfg.has_plus = ("Плюс активен" in msg)
        invalidate_status_cache()
        return {"success": True, "account": msg, "user_name": msg, "has_plus": cfg.has_plus}
    else:
        response.status = 400
        return {"success": False, "error": msg}

@app.route('/api/auth/logout', method='POST')
def api_logout():
    cfg = ConfigManager.get_instance()
    cfg.token = ""
    cfg.user_name = ""
    cfg.has_plus = False
    invalidate_status_cache()
    return {"status": "logged_out"}

@app.route('/api/history', method='GET')
def api_history():
    folder = get_download_directory()
    items = []
    if os.path.exists(folder):
        for f in os.listdir(folder):
            if f.lower().endswith((".mp3", ".flac", ".m4a")) and not f.startswith("yasave_tmp_"):
                full_path = os.path.join(folder, f)
                stat = os.stat(full_path)
                size_mb = round(stat.st_size / (1024 * 1024), 2)
                # Parse artist and title from filename
                name_part = os.path.splitext(f)[0]
                parts = name_part.split(" - ", 1)
                artist = parts[0] if len(parts) > 1 else ""
                title = parts[1] if len(parts) > 1 else name_part

                items.append({
                    "filename": f,
                    "filepath": full_path,
                    "artist": artist,
                    "title": title,
                    "size_mb": size_mb,
                    "time": stat.st_mtime
                })
    items.sort(key=lambda x: x["time"], reverse=True)
    return {"history": items, "folder": folder}

@app.route('/api/settings', method='POST')
def api_settings():
    data = request.json or {}
    cfg = ConfigManager.get_instance()
    if "theme" in data:
        cfg.theme = data["theme"]
    if "accent_color" in data:
        cfg.accent_color = data["accent_color"]
    if "download_dir" in data:
        cfg.download_dir = data["download_dir"]
    return {"status": "ok"}

@app.route('/api/open_folder', method='POST')
def api_open_folder():
    folder = get_download_directory()
    try:
        if sys.platform == 'win32':
            os.startfile(folder)
        else:
            subprocess.Popen(['xdg-open', folder])
        return {"status": "opened"}
    except Exception as e:
        response.status = 500
        return {"error": str(e)}

def start_server(host='127.0.0.1', port=58231):
    # Android: start the playback service early so the first play is instant
    threading.Timer(4.0, PlayerController.get().prewarm).start()
    adapter = ThreadedWSGIAdapter(host=host, port=port)
    run(app, server=adapter, quiet=True)

if __name__ == '__main__':
    start_server()
