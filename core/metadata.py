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


def measure_audio_bitrate(filepath: str) -> dict:
    """
    Real bitrate of a downloaded file.
    MP3: from the frame headers via mutagen (exact for CBR, average for VBR).
    Other / unreadable files: estimated from size and duration.
    """
    result = {"kbps": 0, "mode": "", "codec": "", "method": ""}
    try:
        size = os.path.getsize(filepath)
    except OSError:
        return result
    length = 0.0
    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(filepath)
        if audio is not None and audio.info:
            length = float(getattr(audio.info, "length", 0) or 0)
            bitrate = int(getattr(audio.info, "bitrate", 0) or 0)
            result["codec"] = type(audio).__name__.lower()
            mode = getattr(audio.info, "bitrate_mode", None)
            if mode is not None:
                result["mode"] = str(mode).split(".")[-1]  # CBR / VBR / ABR / UNKNOWN
            if bitrate:
                result["kbps"] = round(bitrate / 1000)
                result["method"] = "file_header"
                return result
    except Exception as e:
        logger.debug(f"mutagen bitrate read failed for {filepath}: {e}")
    if length > 0:
        result["kbps"] = round(size * 8 / length / 1000)
        result["method"] = "size_estimate"
    return result


def embed_metadata_any(filepath: str, title: str, artist: str, album=None, year=None, cover_data=None) -> bool:
    """Tags by container: MP3 (ID3v2), FLAC (Vorbis comments + picture), M4A (MP4 atoms)."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".mp3":
        return embed_metadata(filepath, title, artist, album, year, cover_data)
    mime = "image/png" if cover_data and cover_data.startswith(b"\x89PNG") else "image/jpeg"
    try:
        if ext == ".flac":
            from mutagen.flac import FLAC, Picture
            audio = FLAC(filepath)
            audio["title"] = title or ""
            audio["artist"] = artist or ""
            if album:
                audio["album"] = album
            if year:
                audio["date"] = str(year)
            if cover_data:
                pic = Picture()
                pic.type = 3
                pic.mime = mime
                pic.desc = "Cover"
                pic.data = cover_data
                audio.clear_pictures()
                audio.add_picture(pic)
            audio.save()
        elif ext in (".m4a", ".mp4"):
            from mutagen.mp4 import MP4, MP4Cover
            audio = MP4(filepath)
            audio["\xa9nam"] = [title or ""]
            audio["\xa9ART"] = [artist or ""]
            if album:
                audio["\xa9alb"] = [album]
            if year:
                audio["\xa9day"] = [str(year)]
            if cover_data:
                fmt = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
                audio["covr"] = [MP4Cover(cover_data, imageformat=fmt)]
            audio.save()
        else:
            logger.warning(f"No tag writer for {ext}")
            return False
        logger.info(f"Embedded tags ({ext}) for: {title} - {artist}")
        return True
    except Exception as e:
        logger.error(f"Error embedding metadata into {filepath}: {e}")
        return False
