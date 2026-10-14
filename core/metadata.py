import os
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

def fetch_cover_bytes(cover_url: str) -> Optional[bytes]:
    if not cover_url:
        return None
    try:
        # Normalize url e.g. https://avatars.yandex.net/get-music-content/123/%%
        if "%%" in cover_url:
            cover_url = cover_url.replace("%%", "1000x1000")
        if cover_url.startswith("//"):
            cover_url = "https:" + cover_url
            
        resp = requests.get(cover_url, timeout=15)
        if resp.status_code == 200:
            return resp.content
    except Exception as e:
        logger.error(f"Failed to fetch cover art from {cover_url}: {e}")
    return None

def embed_metadata(
    filepath: str,
    title: str,
    artist: str,
    album: Optional[str] = None,
    year: Optional[str] = None,
    cover_data: Optional[bytes] = None,
    track_num: Optional[int] = None
) -> bool:
    """Embeds ID3v2 tags and cover image directly into the MP3 file."""
    if not os.path.exists(filepath):
        logger.error(f"Cannot embed metadata, file not found: {filepath}")
        return False

    try:
        from mutagen.mp3 import MP3
        from mutagen.id3 import (
            ID3,
            TIT2,
            TPE1,
            TALB,
            TDRC,
            TRCK,
            APIC,
            ID3NoHeaderError
        )

        try:
            audio = MP3(filepath, ID3=ID3)
            try:
                audio.add_tags()
            except Exception:
                pass
        except ID3NoHeaderError:
            audio = MP3(filepath)
            audio.add_tags()

        # Set Title
        if title:
            audio.tags['TIT2'] = TIT2(encoding=3, text=title)

        # Set Artist
        if artist:
            audio.tags['TPE1'] = TPE1(encoding=3, text=artist)

        # Set Album
        if album:
            audio.tags['TALB'] = TALB(encoding=3, text=album)

        # Set Year
        if year:
            audio.tags['TDRC'] = TDRC(encoding=3, text=str(year))

        # Set Track Number
        if track_num is not None:
            audio.tags['TRCK'] = TRCK(encoding=3, text=str(track_num))

        # Set Embedded Cover Art
        if cover_data:
            # Detect mime type (JPEG vs PNG)
            mime = "image/jpeg"
            if cover_data.startswith(b"\x89PNG"):
                mime = "image/png"

            audio.tags['APIC'] = APIC(
                encoding=3,
                mime=mime,
                type=3,  # 3 is cover front
                desc="Cover",
                data=cover_data
            )

        audio.save(v2_version=3)
        logger.info(f"Successfully embedded ID3 tags for: {title} - {artist}")
        return True
    except Exception as e:
        logger.error(f"Error embedding metadata into {filepath}: {e}")
        return False
