import os
import re
import time
import logging
import requests
from typing import List, Dict, Any, Optional, Callable
import yt_dlp
from .storage import get_download_directory, sanitize_filename
from .metadata import embed_metadata, fetch_cover_bytes

logger = logging.getLogger(__name__)

class AlternativeSourcesManager:
    @staticmethod
    def resolve_spotify_url(url: str) -> Optional[Dict[str, str]]:
        """Extracts title and thumbnail from Spotify track URL via oEmbed."""
        if "open.spotify.com/track/" not in url:
            return None
        try:
            resp = requests.get(f"https://open.spotify.com/oembed?url={url}", timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                title = data.get("title", "")
                return {
                    "title": title,
                    "thumbnail_url": data.get("thumbnail_url"),
                    "provider": "Spotify"
                }
        except Exception as e:
            logger.error(f"Error resolving Spotify URL: {e}")
        return None

    @staticmethod
    def search_candidates(
        artist: str, 
        title: str, 
        source: str = "all",
        limit_per_source: int = 4
    ) -> List[Dict[str, Any]]:
        """
        Searches for explicit / uncensored versions across YouTube, SoundCloud, and Spotify.
        source options: 'all', 'youtube', 'soundcloud', 'spotify'
        """
        candidates: List[Dict[str, Any]] = []

        clean_query = f"{artist} {title}".strip()
        if not clean_query:
            return candidates

        # --- 1. SPOTIFY MATCH (if requested or in 'all') ---
        if source in ("all", "spotify"):
            # If user entered a direct Spotify track URL
            if "open.spotify.com/track/" in clean_query:
                sp_info = AlternativeSourcesManager.resolve_spotify_url(clean_query)
                if sp_info:
                    candidates.append({
                        "id": f"sp_{int(time.time())}",
                        "title": sp_info["title"],
                        "channel": "Spotify Official",
                        "duration": 0,
                        "duration_str": "HQ",
                        "url": clean_query,
                        "source": "Spotify",
                        "is_explicit": True,
                        "thumbnail": sp_info.get("thumbnail_url")
                    })
                    # Re-assign clean_query for audio stream fallback
                    clean_query = sp_info["title"]

        # --- 2. YOUTUBE / YT MUSIC SEARCH ---
        if source in ("all", "youtube", "spotify"):
            yt_query = f"ytsearch{limit_per_source}:{clean_query} explicit uncensored"
            ydl_opts = {
                'quiet': True,
                'extract_flat': True,
                'skip_download': True,
                'default_search': 'ytsearch',
                'no_warnings': True,
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    result = ydl.extract_info(yt_query, download=False)
                    for entry in result.get('entries', []):
                        if not entry:
                            continue
                        dur = entry.get('duration') or 0
                        url = entry.get('url') or entry.get('webpage_url')
                        if not url or not url.startswith("http"):
                            url = f"https://www.youtube.com/watch?v={entry.get('id')}"

                        entry_title = entry.get('title', 'Без названия')
                        is_explicit = any(w in entry_title.lower() for w in ['explicit', 'uncensored', 'dirty', '18+'])

                        candidates.append({
                            "id": f"yt_{entry.get('id')}",
                            "title": entry_title,
                            "channel": entry.get('channel') or entry.get('uploader') or "YouTube Music",
                            "duration": dur,
                            "duration_str": f"{dur // 60}:{dur % 60:02d}",
                            "url": url,
                            "source": "YouTube Music",
                            "is_explicit": is_explicit or True,
                            "thumbnail": entry.get('thumbnail')
                        })
            except Exception as e:
                logger.error(f"Error querying YouTube: {e}")

        # --- 3. SOUNDCLOUD SEARCH ---
        if source in ("all", "soundcloud"):
            sc_query = f"scsearch{limit_per_source}:{clean_query} uncensored"
            ydl_opts = {
                'quiet': True,
                'extract_flat': True,
                'skip_download': True,
                'default_search': 'scsearch',
                'no_warnings': True,
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    result = ydl.extract_info(sc_query, download=False)
                    for entry in result.get('entries', []):
                        if not entry:
                            continue
                        dur = int(entry.get('duration') or 0)
                        url = entry.get('url') or entry.get('webpage_url')
                        entry_title = entry.get('title', 'SoundCloud Track')

                        candidates.append({
                            "id": f"sc_{entry.get('id', int(time.time()))}",
                            "title": entry_title,
                            "channel": entry.get('uploader') or "SoundCloud",
                            "duration": dur,
                            "duration_str": f"{dur // 60}:{dur % 60:02d}",
                            "url": url,
                            "source": "SoundCloud",
                            "is_explicit": True,
                            "thumbnail": entry.get('thumbnail')
                        })
            except Exception as e:
                logger.error(f"Error querying SoundCloud: {e}")

        # Fallback if list still empty
        if not candidates:
            fallback_query = f"ytsearch{limit_per_source}:{clean_query} audio"
            try:
                with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True, 'skip_download': True}) as ydl:
                    result = ydl.extract_info(fallback_query, download=False)
                    for entry in result.get('entries', []):
                        if entry:
                            dur = entry.get('duration') or 0
                            url = entry.get('url') or entry.get('webpage_url') or f"https://www.youtube.com/watch?v={entry.get('id')}"
                            candidates.append({
                                "id": f"yt_{entry.get('id')}",
                                "title": entry.get('title', 'Без названия'),
                                "channel": entry.get('channel') or "Web Audio",
                                "duration": dur,
                                "duration_str": f"{dur // 60}:{dur % 60:02d}",
                                "url": url,
                                "source": "Web / YouTube",
                                "is_explicit": True
                            })
            except Exception as e:
                logger.error(f"Error fallback query: {e}")

        return candidates

    @staticmethod
    def get_preview_audio_url(webpage_url: str) -> Optional[str]:
        """Extracts direct streamable audio URL for in-app preview playback."""
        # Handle Spotify URLs by searching YouTube stream fallback
        if "open.spotify.com/track/" in webpage_url:
            sp = AlternativeSourcesManager.resolve_spotify_url(webpage_url)
            if sp and sp.get("title"):
                # find first yt candidate
                cands = AlternativeSourcesManager.search_candidates("", sp["title"], source="youtube", limit_per_source=1)
                if cands:
                    webpage_url = cands[0]["url"]

        ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'quiet': True,
            'skip_download': True,
            'no_warnings': True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(webpage_url, download=False)
                return info.get('url')
        except Exception as e:
            logger.error(f"Error extracting preview audio URL from {webpage_url}: {e}")
            return None

    @staticmethod
    def download_alternative(
        candidate: Dict[str, Any],
        ym_track_info: Dict[str, Any],
        target_dir: Optional[str] = None,
        on_progress: Optional[Callable[[float, float, float, str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None
    ) -> str:
        """
        Downloads selected alternative audio stream (from SoundCloud / YouTube / Spotify match),
        converts/saves as MP3 and embeds original Yandex Music metadata and 1000x1000 cover art.
        """
        save_folder = target_dir or get_download_directory()
        os.makedirs(save_folder, exist_ok=True)

        filename_base = f"{sanitize_filename(ym_track_info['artist'])} - {sanitize_filename(ym_track_info['title'])}"
        out_path = os.path.join(save_folder, f"{filename_base}.mp3")
        temp_out = os.path.join(save_folder, f"temp_{int(time.time())}.%(ext)s")

        download_url = candidate.get("url", "")
        # If Spotify link, resolve audio match from YouTube
        if "open.spotify.com/track/" in download_url:
            if on_status:
                on_status("Поиск несжатого аудиопотока для Spotify трека...")
            cands = AlternativeSourcesManager.search_candidates(
                ym_track_info.get("artist", ""), 
                ym_track_info.get("title", ""), 
                source="youtube", 
                limit_per_source=1
            )
            if cands:
                download_url = cands[0]["url"]

        if on_status:
            source_name = candidate.get("source", "Альтернативный источник")
            on_status(f"Загрузка аудиопотока из {source_name}...")

        def progress_hook(d):
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes') or 0
                speed = d.get('speed') or 0
                speed_str = f"{(speed / (1024*1024)):.1f} МБ/с" if speed else ""
                percent = (downloaded / total * 100) if total else 0.0
                dl_mb = round(downloaded / (1024 * 1024), 2)
                tot_mb = round(total / (1024 * 1024), 2) if total else 0.0
                if on_progress:
                    on_progress(percent, dl_mb, tot_mb, speed_str)
            elif d['status'] == 'finished':
                if on_progress:
                    on_progress(100.0, 0, 0, "")

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': temp_out,
            'quiet': True,
            'no_warnings': True,
            'progress_hooks': [progress_hook]
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([download_url])

        # Find downloaded file
        downloaded_file = None
        for f in os.listdir(save_folder):
            if f.startswith("temp_"):
                downloaded_file = os.path.join(save_folder, f)
                break

        if not downloaded_file:
            raise RuntimeError("Не удалось обнаружить скачанный временный файл.")

        # Rename to final MP3
        if os.path.exists(out_path):
            os.remove(out_path)
        os.rename(downloaded_file, out_path)

        # Embed original Yandex Music metadata and album art
        if on_status:
            on_status("Вшиваем оригинальную обложку (1000x1000) и теги ID3v2...")

        cover_data = None
        if ym_track_info.get("cover_url"):
            cover_data = fetch_cover_bytes(ym_track_info["cover_url"])

        embed_metadata(
            filepath=out_path,
            title=ym_track_info["title"],
            artist=ym_track_info["artist"],
            album=ym_track_info.get("album"),
            year=ym_track_info.get("year"),
            cover_data=cover_data
        )

        if on_status:
            on_status("Трек успешно скачан и обогащён тегами!")

        return out_path
