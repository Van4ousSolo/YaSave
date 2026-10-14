import os
import re
import time
import logging
import requests
from typing import Optional, Callable, Dict, Any, List
from yandex_music import Client
from .config import ConfigManager
from .storage import get_download_directory, sanitize_filename
from .metadata import embed_metadata, fetch_cover_bytes

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
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> str:
        """
        Downloads the track with streaming progress callback.
        on_progress(percent: 0-100, downloaded_mb, total_mb, speed_str)
        Returns the absolute filepath of the tagged MP3 file.
        """
        client = self.ensure_client()
        track = track_info.get("raw_track")
        if not track:
            track_id = track_info["id"]
            track = client.tracks([track_id])[0]

        if on_status:
            on_status("Получение прямой ссылки...")

        # Find best download info
        download_infos = track.get_download_info()
        best_info = None
        for info in download_infos:
            if info.codec == 'mp3' and info.bitrate_in_kbps == 320:
                best_info = info
                break
        if not best_info:
            for info in download_infos:
                if info.codec == 'mp3':
                    best_info = info
                    break
        if not best_info and download_infos:
            best_info = download_infos[0]

        if not best_info:
            raise RuntimeError("Не удалось получить информацию для скачивания.")

        direct_link = best_info.get_direct_link()

        save_folder = target_dir or get_download_directory()
        os.makedirs(save_folder, exist_ok=True)

        filename = f"{sanitize_filename(track_info['artist'])} - {sanitize_filename(track_info['title'])}.mp3"
        filepath = os.path.join(save_folder, filename)

        if on_status:
            on_status(f"Загрузка ({best_info.bitrate_in_kbps} kbps)...")

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

        if on_status:
            on_status("Скачивание завершено!")

        return filepath
