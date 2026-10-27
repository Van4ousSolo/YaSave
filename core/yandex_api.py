import os
import re
import time
import logging
import requests
from typing import Optional, Callable, Dict, Any, List
from yandex_music import Client
from .config import ConfigManager
from .storage import get_download_directory, sanitize_filename
from .metadata import embed_metadata, fetch_cover_bytes, measure_audio_bitrate

logger = logging.getLogger(__name__)

class YandexParser:
    @staticmethod
    def extract_track_id(url_or_id: str) -> Optional[str]:
        text = url_or_id.strip()
        if not text:
            return None

        # Clean query parameters / fragments
        clean_text = text.split("?")[0].split("#")[0].strip()

        # Check if direct ID
        if clean_text.isdigit():
            return clean_text

        # Match /album/<id>/track/<track_id>
        match = re.search(r'/track/(\d+)', clean_text)
        if match:
            return match.group(1)

        # Match /album/<id> (we can check if it's album later or treat as track)
        return None

    @staticmethod
    def extract_album_id(url_or_id: str) -> Optional[str]:
        text = url_or_id.strip().split("?")[0].split("#")[0]
        # Match /album/<id> but NOT if followed by /track/
        if "/track/" not in text:
            match = re.search(r'/album/(\d+)', text)
            if match:
                return match.group(1)
        return None


class YandexDownloader:
    def __init__(self, client: Optional[Client] = None):
        self.config = ConfigManager.get_instance()
        self.client = client

    def ensure_client(self) -> Client:
        if self.client:
            return self.client
        tok = self.config.token
        if not tok:
            raise ValueError("API токен Яндекс Музыки не задан. Авторизуйтесь в приложении.")
        self.client = Client(tok)
        return self.client

    def _search_client(self) -> Client:
        """Catalog search works anonymously too; use the token when available."""
        if self.client:
            return self.client
        tok = self.config.token
        return Client(tok) if tok else Client()

    @staticmethod
    def _cover(uri: Optional[str], size: str) -> Optional[str]:
        return f"https://{uri.replace('%%', size)}" if uri else None

    def search_tracks(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        client = self._search_client()
        try:
            result = client.search(query, type_='track', nocorrect=False)
        except Exception as e:
            msg = str(e)
            if "451" in msg or "Legal Reasons" in msg:
                raise RuntimeError(
                    "Каталог недоступен в этом регионе без входа. Авторизуйтесь в Настройках или отключите VPN."
                ) from e
            if "401" in msg or "Unauthorized" in msg:
                raise RuntimeError("Токен Яндекс Музыки недействителен. Войдите заново.") from e
            raise
        if not result or not result.tracks or not result.tracks.results:
            return []
        out = []
        for track in result.tracks.results[:limit]:
            if not track or not track.id:
                continue
            if track.available is False:
                continue
            title = track.title or "Без названия"
            if track.version:
                title = f"{title} ({track.version})"
            artists = ", ".join(a.name for a in (track.artists or []) if a.name) or "Неизвестный исполнитель"
            album = track.albums[0] if track.albums else None
            dur = (track.duration_ms or 0) // 1000
            cover_uri = track.cover_uri or (album.cover_uri if album else None) or track.og_image
            album_id = album.id if album else None
            out.append({
                "id": str(track.id),
                "title": title,
                "artist": artists,
                "album": album.title if album else None,
                "year": str(album.year) if album and album.year else None,
                "duration": dur,
                "duration_str": f"{dur // 60}:{dur % 60:02d}",
                "explicit": track.content_warning == 'explicit',
                "thumb_url": self._cover(cover_uri, "200x200"),
                "url": f"https://music.yandex.ru/album/{album_id}/track/{track.id}" if album_id else f"https://music.yandex.ru/track/{track.id}",
            })
        return out

    # ------------------------------------------------------------------
    # Stream selection (real bitrate, best first)
    # ------------------------------------------------------------------

    _account_cache: Dict[str, Any] = {}

    def account_quality(self) -> Dict[str, Any]:
        """Plus / high-quality permission of the current account (cached for 10 min)."""
        tok = self.config.token
        cached = YandexDownloader._account_cache
        if cached.get("token") == tok and time.time() - cached.get("ts", 0) < 600:
            return cached["info"]
        info = {"has_plus": None, "high_quality": None}
        try:
            st = self.ensure_client().account_status()
            info["has_plus"] = bool(st.plus and st.plus.has_plus)
            perms = (st.permissions.values if st.permissions else None) or []
            info["high_quality"] = "high-quality" in perms
        except Exception as e:
            logger.warning(f"account_status failed: {e}")
        YandexDownloader._account_cache = {"token": tok, "ts": time.time(), "info": info}
        return info

    def pick_stream(self, track) -> Dict[str, Any]:
        """
        Chooses the best MP3 stream.
        1. get-file-info (current API, the only one that serves 320 kbps now) asked for 'hq'.
        2. Legacy download-info (often capped at 192 kbps), sorted by bitrate.
        The highest bitrate wins. Returns url, codec, bitrate, quality, api.
        """
        options: List[Dict[str, Any]] = []
        client = self.ensure_client()
        track_id = str(getattr(track, "track_id", None) or getattr(track, "id", None) or track)

        try:
            fi = client.tracks_file_info(track_id, quality="hq", codecs=["mp3"], transport="raw")
            d = fi.download_info if fi else None
            if d and d.url and d.codec == "mp3" and d.transport == "raw":
                options.append({"url": d.url, "codec": d.codec, "bitrate": int(d.bitrate or 0),
                                "quality": d.quality, "api": "get-file-info"})
        except Exception as e:
            logger.warning(f"get-file-info failed for {track_id}: {e}")

        if not options or options[0]["bitrate"] < 320:
            try:
                track_obj = track if hasattr(track, "get_download_info") else client.tracks([track_id])[0]
                infos = [i for i in track_obj.get_download_info() if i.codec == "mp3" and not i.preview]
                infos.sort(key=lambda i: i.bitrate_in_kbps or 0, reverse=True)
                if infos and (not options or (infos[0].bitrate_in_kbps or 0) > options[0]["bitrate"]):
                    best = infos[0]
                    options.insert(0, {"url": best.get_direct_link(), "codec": "mp3",
                                       "bitrate": int(best.bitrate_in_kbps or 0),
                                       "quality": "hq" if (best.bitrate_in_kbps or 0) >= 320 else "nq",
                                       "api": "download-info"})
            except Exception as e:
                logger.warning(f"download-info failed for {track_id}: {e}")

        if not options:
            raise RuntimeError("Яндекс не выдал ссылку на файл (нет прав на трек или он недоступен в регионе).")
        best = max(options, key=lambda o: o["bitrate"])
        best["note"] = self.quality_note(best)
        return best

    def quality_note(self, stream: Dict[str, Any]) -> str:
        """Explains honestly why the stream is below 320 kbps ('' when it is 320)."""
        if stream.get("bitrate", 0) >= 320:
            return ""
        acc = self.account_quality()
        if acc.get("has_plus") is False:
            return "320 kbps доступен только с подпиской Яндекс Плюс. Без неё Яндекс отдаёт 192 kbps."
        if acc.get("high_quality") is False:
            return "У аккаунта нет права на высокое качество (high-quality), поэтому только 192 kbps."
        if stream.get("quality") == "nq":
            return ("Яндекс выдал этому устройству только обычное качество (192 kbps), хотя Плюс активен. "
                    "Так бывает при входе не из страны подписки, например через VPN.")
        return "Для этого трека Яндекс не предоставляет 320 kbps."

    def probe_quality(self, track_id: str) -> Dict[str, Any]:
        """Quality info for the track card (no download)."""
        s = self.pick_stream(track_id)
        return {k: s.get(k) for k in ("codec", "bitrate", "quality", "api", "note")}

    def get_stream_url(self, track_id: str, preview: bool = False) -> str:
        """Direct mp3 link. For preview the lowest mp3 bitrate is used to start faster."""
        client = self.ensure_client()
        tracks = client.tracks([track_id])
        if not tracks:
            raise ValueError("Трек не найден")
        infos = [i for i in tracks[0].get_download_info() if i.codec == 'mp3'] or tracks[0].get_download_info()
        if not infos:
            raise RuntimeError("Нет доступных аудиопотоков")
        infos.sort(key=lambda i: i.bitrate_in_kbps or 0, reverse=not preview)
        return infos[0].get_direct_link()

    def get_track_info(self, track_id: str) -> Dict[str, Any]:
        client = self.ensure_client()
        tracks = client.tracks([track_id])
        if not tracks or not tracks[0]:
            raise ValueError(f"Трек с ID {track_id} не найден.")

        track = tracks[0]
        title = track.title or "Неизвестный трек"
        if track.version:
            title = f"{title} ({track.version})"

        artists = ", ".join([a.name for a in track.artists if a.name]) if track.artists else "Неизвестный исполнитель"
        
        album_name = None
        year = None
        if track.albums and len(track.albums) > 0:
            album = track.albums[0]
            album_name = album.title
            year = str(album.year) if album.year else None

        cover_url = None
        if track.cover_uri:
            cover_url = f"https://{track.cover_uri.replace('%%', '1000x1000')}"
        elif track.og_image:
            cover_url = f"https://{track.og_image.replace('%%', '1000x1000')}"

        duration_sec = (track.duration_ms or 0) // 1000
        is_explicit = bool(track.content_warning == 'explicit')

        return {
            "id": str(track.id),
            "title": title,
            "artist": artists,
            "album": album_name,
            "year": year,
            "duration": duration_sec,
            "duration_str": f"{duration_sec // 60}:{duration_sec % 60:02d}",
            "cover_url": cover_url,
            "explicit": is_explicit,
            "raw_track": track
        }

    def download_track(
        self,
        track_info: Dict[str, Any],
        target_dir: Optional[str] = None,
        on_progress: Optional[Callable[[float, float, float, str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        on_quality: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> str:
        """
        Downloads the track with streaming progress callback.
        on_progress(percent: 0-100, downloaded_mb, total_mb, speed_str)
        on_quality(dict): stream bitrate from the API, then the bitrate measured in the file.
        Returns the absolute filepath of the tagged MP3 file.
        """
        client = self.ensure_client()
        track = track_info.get("raw_track")
        if not track:
            track_id = track_info["id"]
            track = client.tracks([track_id])[0]

        if on_status:
            on_status("Выбор лучшего качества...")

        stream = self.pick_stream(track)
        direct_link = stream["url"]
        quality: Dict[str, Any] = {
            "api_bitrate": stream["bitrate"], "codec": stream["codec"],
            "quality": stream["quality"], "api": stream["api"], "note": stream["note"],
        }
        if on_quality:
            on_quality(dict(quality))
        logger.info(f"Yandex stream for {track_info.get('id')}: {stream['codec']} {stream['bitrate']} kbps "
                    f"({stream['quality']}, {stream['api']})")

        save_folder = target_dir or get_download_directory()
        os.makedirs(save_folder, exist_ok=True)

        filename = f"{sanitize_filename(track_info['artist'])} - {sanitize_filename(track_info['title'])}.mp3"
        filepath = os.path.join(save_folder, filename)

        if on_status:
            on_status(f"Загрузка: MP3 {stream['bitrate']} kbps (по ответу Яндекса)...")

        # Streaming download
        resp = requests.get(direct_link, stream=True, timeout=30)
        resp.raise_for_status()

        total_length = int(resp.headers.get('content-length', 0))
        total_mb = round(total_length / (1024 * 1024), 2) if total_length else 0.0

        downloaded = 0
        chunk_size = 64 * 1024  # 64 KB
        start_time = time.time()
        last_progress_time = 0

        temp_filepath = filepath + ".part"

        with open(temp_filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if cancel_check and cancel_check():
                    f.close()
                    if os.path.exists(temp_filepath):
                        os.remove(temp_filepath)
                    raise InterruptedError("Загрузка отменена")

                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

                    now = time.time()
                    if now - last_progress_time >= 0.1:  # update 10 times/sec
                        last_progress_time = now
                        elapsed = max(now - start_time, 0.001)
                        speed_mb = (downloaded / (1024 * 1024)) / elapsed
                        speed_str = f"{speed_mb:.1f} МБ/с"
                        downloaded_mb = round(downloaded / (1024 * 1024), 2)
                        percent = (downloaded / total_length * 100) if total_length else 0.0

                        if on_progress:
                            on_progress(percent, downloaded_mb, total_mb, speed_str)

        # Final progress update
        if on_progress and total_length:
            on_progress(100.0, total_mb, total_mb, "")

        if os.path.exists(filepath):
            os.remove(filepath)
        os.rename(temp_filepath, filepath)

        # Embed metadata
        if on_status:
            on_status("Запись обложки и тегов (ID3v2)...")

        cover_data = None
        if track_info.get("cover_url"):
            cover_data = fetch_cover_bytes(track_info["cover_url"])

        embed_metadata(
            filepath=filepath,
            title=track_info["title"],
            artist=track_info["artist"],
            album=track_info.get("album"),
            year=track_info.get("year"),
            cover_data=cover_data
        )

        # Verify the real bitrate from the saved file
        measured = measure_audio_bitrate(filepath)
        quality["file_bitrate"] = measured.get("kbps", 0)
        quality["file_mode"] = measured.get("mode", "")
        quality["file_method"] = measured.get("method", "")
        if on_quality:
            on_quality(dict(quality))

        if on_status:
            how = "по файлу" if measured.get("method") == "file_header" else "оценка по размеру"
            on_status(f"Сохранено: MP3 {measured.get('kbps') or stream['bitrate']} kbps ({how})")

        return filepath
