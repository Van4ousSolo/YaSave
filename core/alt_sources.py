import os
import re
import time
import base64
import json
import logging
import threading
import unicodedata
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional, Callable, Tuple

import requests
import yt_dlp

from .config import ConfigManager
from .storage import get_download_directory, sanitize_filename
from .metadata import embed_metadata, fetch_cover_bytes

logger = logging.getLogger(__name__)

# Sources that can be searched. 'all' expands to every available one.
ALL_SOURCES = ("yandex", "youtube", "soundcloud", "spotify")

# Per-source result limits (raw results before dedupe/ranking)
YT_LIMIT = 15
YT_UNCENSORED_LIMIT = 10
SC_LIMIT = 15
SP_LIMIT = 20
YM_LIMIT = 20
MAX_RESULTS = 40

SOURCE_TIMEOUT = 25  # seconds per source in parallel search


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower().replace("ё", "е")
    text = re.sub(r"[^\w\s+]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _fmt_duration(sec: int) -> str:
    sec = int(sec or 0)
    if sec <= 0:
        return "--:--"
    return f"{sec // 60}:{sec % 60:02d}"


# Markers that suggest an uncensored / original release
BOOST_MARKERS = [
    ("uncensored", 14), ("explicit", 12), ("dirty", 8), ("18+", 10),
    ("без цензуры", 14), ("нецензур", 10), ("uncut", 6), ("original", 5), ("оригинал", 5),
]

# Markers that suggest a variant the user probably does not want.
# Only applied when the marker is NOT part of the user's query.
PENALTY_MARKERS = [
    ("clean", 18), ("censored", 18), ("radio edit", 18), ("edited", 10),
    ("speed up", 20), ("sped up", 20), ("speedup", 20), ("slowed", 20), ("reverb", 12),
    ("nightcore", 22), ("cover", 22), ("кавер", 22), ("karaoke", 28), ("караоке", 28),
    ("instrumental", 25), ("минус", 25), ("remix", 10), ("ремикс", 10),
    ("snippet", 25), ("сниппет", 25), ("live", 8), ("концерт", 8), ("8d", 15),
    ("tribute", 25), ("originally performed", 30), ("made popular", 30), ("in the style of", 30),
    ("parody", 22), ("parodie", 22), ("пародия", 22), ("lullaby", 25), ("rockabye baby", 30),
]


def score_candidate(cand: Dict[str, Any], query: str, ref_duration: int = 0) -> Tuple[float, List[str]]:
    """Unified relevance score for a mixed-source result list."""
    q_norm = _normalize(query)
    title_norm = _normalize(cand.get("title", ""))
    artist_norm = _normalize(cand.get("artist") or cand.get("channel") or "")
    full_norm = f"{artist_norm} {title_norm}".strip()
    tags: List[str] = []

    # 1. Fuzzy text match (0..60)
    ratio_full = SequenceMatcher(None, q_norm, full_norm).ratio() if q_norm else 0
    ratio_title = SequenceMatcher(None, q_norm, title_norm).ratio() if q_norm else 0
    q_tokens = set(q_norm.split())
    hay_tokens = set(full_norm.split())
    overlap = len(q_tokens & hay_tokens) / len(q_tokens) if q_tokens else 0
    score = 60 * max(ratio_full, ratio_title, overlap * 0.95)

    # 2. Uncensored markers boost
    raw_title = f" {(cand.get('title') or '').lower()} "
    boost = 0
    for marker, weight in BOOST_MARKERS:
        if marker in raw_title:
            boost += weight
    if cand.get("is_explicit"):
        boost += 14
        tags.append("explicit")
    score += min(boost, 28)

    # 3. Penalties for unwanted variants (unless requested)
    # Checked in title and artist: karaoke / tribute labels often sit in the artist name
    q_low = f" {query.lower()} "
    raw_all = f"{raw_title} {(cand.get('artist') or '').lower()} "
    for marker, weight in PENALTY_MARKERS:
        pattern = r"(?<![\w])" + re.escape(marker) + r"(?![\w])"
        if re.search(pattern, raw_all) and marker not in q_low:
            score -= weight

    # 4. Short snippets
    dur = int(cand.get("duration") or 0)
    if dur > 0:
        if dur < 60:
            score -= 35
            tags.append("snippet")
        elif dur < 90:
            score -= 12
        elif dur > 900:
            score -= 20  # mixes / full albums

    # 5. Duration match against the original Yandex track
    if ref_duration and dur:
        diff = abs(dur - ref_duration)
        if diff <= 5:
            score += 40
            tags.append("duration_match")
        elif diff <= 10:
            score += 28
            tags.append("duration_match")
        elif diff <= 20:
            score += 8
        elif diff > 40:
            score -= 15

    # 6. Official catalog sources get a small edge
    if cand.get("source") == "Yandex Music" or cand.get("match_audio"):
        score += 4
    if (cand.get("channel") or "").endswith(" - Topic"):
        score += 4

    return round(score, 2), tags


# ---------------------------------------------------------------------------
# Small TTL cache (protects Spotify / Deezer / iTunes / YouTube from repeat calls)
# ---------------------------------------------------------------------------

class TTLCache:
    def __init__(self, ttl: float, maxsize: int = 256):
        self.ttl = ttl
        self.maxsize = maxsize
        self._data: Dict[Any, Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            if time.time() > item[0]:
                self._data.pop(key, None)
                return None
            return item[1]

    def set(self, key, value):
        with self._lock:
            if len(self._data) >= self.maxsize:
                # Drop the entry that expires first
                oldest = min(self._data, key=lambda k: self._data[k][0])
                self._data.pop(oldest, None)
            self._data[key] = (time.time() + self.ttl, value)

    def clear(self):
        with self._lock:
            self._data.clear()


_catalog_cache = TTLCache(ttl=3600, maxsize=300)      # metadata search results
_match_cache = TTLCache(ttl=6 * 3600, maxsize=500)    # catalog track -> YouTube audio


def _cache_key(*parts) -> Tuple:
    return tuple(_normalize(str(p)) if isinstance(p, str) else p for p in parts)


# ---------------------------------------------------------------------------
# Spotify (metadata only, audio is matched on YouTube)
# ---------------------------------------------------------------------------

# Public client_credentials keys shipped with spotDL (read-only catalog access).
# They are shared by many users, so 429 is common: in that case we fall back
# to Deezer / iTunes instead of waiting.
DEFAULT_SPOTIFY_CLIENT_ID = "5f573c9620494bae87890c0f08a60293"
DEFAULT_SPOTIFY_CLIENT_SECRET = "212476d9b0f3472eaa762d90b19b0ba8"

SPOTIFY_COOLDOWN = 300        # seconds to skip Spotify after a failure
SPOTIFY_MAX_COOLDOWN = 900    # cap for Retry-After from 429
SPOTIFY_TIMEOUT = 8


class SpotifyUnavailable(RuntimeError):
    """Spotify can't be used right now (token, 401/403/429, region, timeout)."""


class SpotifyClient:
    _token: Optional[str] = None
    _token_expires: float = 0.0
    _token_owner: Optional[str] = None   # client id the token belongs to
    _down_until: float = 0.0
    last_error: str = ""
    _lock = threading.Lock()

    @classmethod
    def has_user_keys(cls) -> bool:
        cfg = ConfigManager.get_instance()
        return bool(cfg.spotify_client_id and cfg.spotify_client_secret)

    @classmethod
    def credentials(cls) -> Tuple[str, str]:
        """User keys take priority; otherwise the built-in ones."""
        cfg = ConfigManager.get_instance()
        if cfg.spotify_client_id and cfg.spotify_client_secret:
            return cfg.spotify_client_id, cfg.spotify_client_secret
        return DEFAULT_SPOTIFY_CLIENT_ID, DEFAULT_SPOTIFY_CLIENT_SECRET

    @classmethod
    def reset(cls):
        with cls._lock:
            cls._token = None
            cls._token_expires = 0.0
            cls._token_owner = None
            cls._down_until = 0.0
            cls.last_error = ""

    @classmethod
    def is_down(cls) -> bool:
        return time.time() < cls._down_until

    @classmethod
    def _mark_down(cls, reason: str, seconds: float = SPOTIFY_COOLDOWN) -> SpotifyUnavailable:
        cls._down_until = time.time() + min(max(seconds, 30), SPOTIFY_MAX_COOLDOWN)
        cls.last_error = reason
        logger.warning(f"Spotify unavailable for {int(cls._down_until - time.time())}s: {reason}")
        return SpotifyUnavailable(reason)

    @classmethod
    def get_token(cls, force: bool = False) -> str:
        cid, secret = cls.credentials()
        with cls._lock:
            if (not force and cls._token and cls._token_owner == cid
                    and time.time() < cls._token_expires - 30):
                return cls._token
            auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
            try:
                resp = requests.post(
                    "https://accounts.spotify.com/api/token",
                    data={"grant_type": "client_credentials"},
                    headers={"Authorization": f"Basic {auth}"},
                    timeout=SPOTIFY_TIMEOUT,
                )
            except requests.RequestException as e:
                raise cls._mark_down(f"нет связи со Spotify ({type(e).__name__})")
            if resp.status_code != 200:
                if resp.status_code == 429:
                    raise cls._mark_down("лимит запросов Spotify (429)", float(resp.headers.get("Retry-After") or SPOTIFY_COOLDOWN))
                if cls.has_user_keys():
                    raise cls._mark_down("Spotify отклонил ключи из Настроек (проверьте Client ID / Secret)")
                raise cls._mark_down(f"Spotify не выдал токен ({resp.status_code})")
            data = resp.json()
            cls._token = data["access_token"]
            cls._token_owner = cid
            cls._token_expires = time.time() + int(data.get("expires_in", 3600))
            return cls._token

    @classmethod
    def _api_get(cls, path: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
        if cls.is_down():
            raise SpotifyUnavailable(cls.last_error or "Spotify временно недоступен")
        for attempt in range(2):
            token = cls.get_token(force=attempt > 0)
            try:
                resp = requests.get(
                    f"https://api.spotify.com/v1/{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=SPOTIFY_TIMEOUT,
                )
            except requests.RequestException as e:
                raise cls._mark_down(f"нет связи со Spotify ({type(e).__name__})")
            if resp.status_code == 401 and attempt == 0:
                continue  # expired token: refresh once
            if resp.status_code == 429:
                raise cls._mark_down("лимит запросов Spotify (429)", float(resp.headers.get("Retry-After") or SPOTIFY_COOLDOWN))
            if resp.status_code in (401, 403, 451):
                raise cls._mark_down(f"Spotify недоступен ({resp.status_code})")
            if resp.status_code >= 500:
                raise cls._mark_down(f"ошибка сервера Spotify ({resp.status_code})", 60)
            return resp
        raise cls._mark_down("Spotify не принимает токен")

    @classmethod
    def _track_to_candidate(cls, t: Dict[str, Any]) -> Dict[str, Any]:
        artists = ", ".join(a.get("name", "") for a in t.get("artists", []) if a.get("name"))
        album = t.get("album") or {}
        images = album.get("images") or []
        dur = int((t.get("duration_ms") or 0) // 1000)
        year = (album.get("release_date") or "")[:4] or None
        return {
            "id": f"sp_{t.get('id')}",
            "title": t.get("name", ""),
            "artist": artists,
            "channel": artists,
            "album": album.get("name"),
            "year": year,
            "duration": dur,
            "duration_str": _fmt_duration(dur),
            "url": (t.get("external_urls") or {}).get("spotify") or f"https://open.spotify.com/track/{t.get('id')}",
            "source": "Spotify",
            "meta_source": "Spotify",
            "audio_source": "YouTube",
            "match_audio": True,
            "is_explicit": bool(t.get("explicit")),
            "thumbnail": images[-1]["url"] if images else None,
            "cover_url": images[0]["url"] if images else None,
        }

    @classmethod
    def search(cls, query: str, limit: int = SP_LIMIT) -> List[Dict[str, Any]]:
        key = _cache_key("spotify", query, limit)
        cached = _catalog_cache.get(key)
        if cached is not None:
            return [dict(c) for c in cached]
        resp = cls._api_get("search", {"q": query, "type": "track", "limit": min(limit, 50)})
        if resp.status_code != 200:
            raise SpotifyUnavailable(f"Spotify: ошибка поиска ({resp.status_code})")
        items = ((resp.json().get("tracks") or {}).get("items")) or []
        out = [cls._track_to_candidate(t) for t in items if t]
        _catalog_cache.set(key, out)
        return [dict(c) for c in out]

    @classmethod
    def get_track(cls, track_id: str) -> Optional[Dict[str, Any]]:
        key = ("spotify_track", track_id)
        cached = _catalog_cache.get(key)
        if cached is not None:
            return dict(cached)
        resp = cls._api_get(f"tracks/{track_id}")
        if resp.status_code != 200:
            return None
        cand = cls._track_to_candidate(resp.json())
        _catalog_cache.set(key, cand)
        return dict(cand)

    @staticmethod
    def resolve_oembed(url: str) -> Optional[Dict[str, Any]]:
        """Works without any keys: returns at least the track title and cover."""
        try:
            resp = requests.get("https://open.spotify.com/oembed", params={"url": url}, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                return {"title": data.get("title", ""), "cover_url": data.get("thumbnail_url")}
        except Exception as e:
            logger.error(f"Spotify oEmbed error: {e}")
        return None


SPOTIFY_TRACK_RE = re.compile(r"open\.spotify\.com/(?:intl-\w+/)?track/([A-Za-z0-9]+)")


# ---------------------------------------------------------------------------
# Metadata fallback: Deezer -> iTunes (no keys needed)
# ---------------------------------------------------------------------------

CATALOG_TIMEOUT = 8


def _deezer_search(query: str, limit: int) -> List[Dict[str, Any]]:
    resp = requests.get("https://api.deezer.com/search", params={"q": query, "limit": limit}, timeout=CATALOG_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):  # Deezer reports quota errors with HTTP 200
        raise RuntimeError(f"Deezer: {data['error'].get('message') or data['error']}")
    out = []
    for t in data.get("data") or []:
        if not t.get("id") or t.get("readable") is False:
            continue
        album = t.get("album") or {}
        artist = (t.get("artist") or {}).get("name") or ""
        dur = int(t.get("duration") or 0)
        out.append({
            "id": f"dz_{t['id']}",
            "title": t.get("title") or t.get("title_short") or "",
            "artist": artist,
            "channel": artist,
            "album": album.get("title"),
            "year": None,
            "duration": dur,
            "duration_str": _fmt_duration(dur),
            "url": t.get("link") or f"https://www.deezer.com/track/{t['id']}",
            "source": "Deezer",
            "meta_source": "Deezer",
            "audio_source": "YouTube",
            "match_audio": True,
            "is_explicit": bool(t.get("explicit_lyrics")),
            "thumbnail": album.get("cover_medium") or album.get("cover"),
            "cover_url": album.get("cover_xl") or album.get("cover_big") or album.get("cover_medium"),
        })
    return out


def _itunes_search(query: str, limit: int) -> List[Dict[str, Any]]:
    resp = requests.get(
        "https://itunes.apple.com/search",
        params={"term": query, "entity": "song", "media": "music", "limit": limit},
        timeout=CATALOG_TIMEOUT,
    )
    resp.raise_for_status()
    out = []
    for t in resp.json().get("results") or []:
        if t.get("wrapperType") != "track" or not t.get("trackId"):
            continue
        dur = int((t.get("trackTimeMillis") or 0) // 1000)
        art = t.get("artworkUrl100") or ""
        out.append({
            "id": f"it_{t['trackId']}",
            "title": t.get("trackName") or "",
            "artist": t.get("artistName") or "",
            "channel": t.get("artistName") or "",
            "album": t.get("collectionName"),
            "year": (t.get("releaseDate") or "")[:4] or None,
            "duration": dur,
            "duration_str": _fmt_duration(dur),
            "url": t.get("trackViewUrl") or "",
            "source": "iTunes",
            "meta_source": "iTunes",
            "audio_source": "YouTube",
            "match_audio": True,
            "is_explicit": t.get("trackExplicitness") == "explicit",
            "thumbnail": art.replace("100x100bb", "200x200bb") if art else None,
            "cover_url": art.replace("100x100bb", "1000x1000bb") if art else None,
        })
    return out


FALLBACK_PROVIDERS = (("Deezer", _deezer_search), ("iTunes", _itunes_search))


def catalog_fallback_search(query: str, limit: int = SP_LIMIT) -> List[Dict[str, Any]]:
    """Catalog metadata without Spotify. Tries Deezer, then iTunes. Cached."""
    key = _cache_key("fallback", query, limit)
    cached = _catalog_cache.get(key)
    if cached is not None:
        return [dict(c) for c in cached]
    errors = []
    for name, func in FALLBACK_PROVIDERS:
        try:
            items = func(query, limit)
        except Exception as e:
            logger.error(f"{name} search error: {e}")
            errors.append(f"{name}: {e}")
            continue
        if items:
            _catalog_cache.set(key, items)
            return [dict(c) for c in items]
    if errors and len(errors) == len(FALLBACK_PROVIDERS):
        raise RuntimeError("Каталоги недоступны: " + "; ".join(errors))
    return []


# ---------------------------------------------------------------------------
# yt-dlp based sources
# ---------------------------------------------------------------------------

def _ydl_flat_search(search_term: str) -> List[Dict[str, Any]]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "socket_timeout": 12,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        result = ydl.extract_info(search_term, download=False) or {}
    return [e for e in (result.get("entries") or []) if e]


def _split_artist_title(raw_title: str, fallback_artist: str) -> Tuple[str, str]:
    for sep in (" - ", " – ", " — "):
        if sep in raw_title:
            a, t = raw_title.split(sep, 1)
            return a.strip(), t.strip()
    return fallback_artist, raw_title


def _search_youtube(query: str) -> List[Dict[str, Any]]:
    # Uncensored suffix in the query's language (English suffix on a Cyrillic query returns nothing)
    suffix = "без цензуры" if re.search(r"[а-яё]", query, re.I) else "uncensored explicit"
    terms = [f"ytsearch{YT_LIMIT}:{query}", f"ytsearch{YT_UNCENSORED_LIMIT}:{query} {suffix}"]
    entries: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        for fut in [pool.submit(_ydl_flat_search, t) for t in terms]:
            try:
                entries.extend(fut.result())
            except Exception as e:
                logger.error(f"YouTube search error: {e}")

    out = []
    for e in entries:
        vid = e.get("id")
        if not vid:
            continue
        dur = int(e.get("duration") or 0)
        channel = e.get("channel") or e.get("uploader") or "YouTube"
        raw_title = e.get("title") or "Без названия"
        artist = channel[:-8] if channel.endswith(" - Topic") else channel
        is_topic = channel.endswith(" - Topic")
        out.append({
            "id": f"yt_{vid}",
            "title": raw_title,
            "artist": artist,
            "channel": channel,
            "duration": dur,
            "duration_str": _fmt_duration(dur),
            "url": f"https://www.youtube.com/watch?v={vid}",
            "source": "YouTube Music" if is_topic else "YouTube",
            "is_explicit": False,
            "thumbnail": (e.get("thumbnails") or [{}])[-1].get("url") if e.get("thumbnails") else None,
        })
    return out


def _search_soundcloud(query: str) -> List[Dict[str, Any]]:
    out = []
    for e in _ydl_flat_search(f"scsearch{SC_LIMIT}:{query}"):
        url = e.get("webpage_url") or e.get("url")
        if not url:
            continue
        dur = int(e.get("duration") or 0)
        channel = e.get("uploader") or "SoundCloud"
        out.append({
            "id": f"sc_{e.get('id') or abs(hash(url))}",
            "title": e.get("title") or "SoundCloud Track",
            "artist": channel,
            "channel": channel,
            "duration": dur,
            "duration_str": _fmt_duration(dur),
            "url": url,
            "source": "SoundCloud",
            "is_explicit": False,
            "thumbnail": e.get("thumbnail"),
        })
    return out


def _search_yandex(query: str) -> List[Dict[str, Any]]:
    from .yandex_api import YandexDownloader
    tracks = YandexDownloader().search_tracks(query, limit=YM_LIMIT)
    out = []
    for t in tracks:
        out.append({
            "id": f"ym_{t['id']}",
            "ym_id": t["id"],
            "title": t["title"],
            "artist": t["artist"],
            "channel": t["artist"],
            "album": t.get("album"),
            "duration": t["duration"],
            "duration_str": t["duration_str"],
            "url": t.get("url"),
            "source": "Yandex Music",
            "is_explicit": t.get("explicit", False),
            "thumbnail": t.get("thumb_url"),
        })
    return out


def _spotify_embed_track(track_id: str) -> Optional[Dict[str, Any]]:
    """Keyless metadata for a Spotify link from the public embed page."""
    key = ("spotify_embed", track_id)
    cached = _catalog_cache.get(key)
    if cached is not None:
        return dict(cached)
    try:
        resp = requests.get(
            f"https://open.spotify.com/embed/track/{track_id}",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=SPOTIFY_TIMEOUT,
        )
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', resp.text, re.S)
        if resp.status_code != 200 or not m:
            return None

        e = json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
        images = ((e.get("visualIdentity") or {}).get("image")) or []
        images = sorted((i for i in images if i.get("url")), key=lambda i: i.get("maxWidth") or 0)
        cand = SpotifyClient._track_to_candidate({
            "id": track_id,
            "name": e.get("name") or e.get("title") or "",
            "artists": e.get("artists") or [],
            "duration_ms": e.get("duration") or 0,
            "explicit": e.get("isExplicit"),
            "album": {"images": [{"url": i["url"]} for i in reversed(images)]},
        })
    except Exception as ex:
        logger.error(f"Spotify embed parse error: {ex}")
        return None
    _catalog_cache.set(key, cand)
    return dict(cand)


def _search_spotify_link(query: str, track_id: str) -> List[Dict[str, Any]]:
    try:
        track = SpotifyClient.get_track(track_id)
        if track:
            return [track]
    except SpotifyUnavailable as e:
        logger.info(f"Spotify API down for link, using embed page: {e}")
    track = _spotify_embed_track(track_id)
    if track:
        return [track]
    # Last resort: title from oEmbed, metadata from Deezer / iTunes
    info = SpotifyClient.resolve_oembed(query)
    if info and info.get("title"):
        return catalog_fallback_search(info["title"])
    return []


def _search_spotify(query: str) -> List[Dict[str, Any]]:
    """Spotify catalog; on any Spotify failure falls back to Deezer / iTunes."""
    m = SPOTIFY_TRACK_RE.search(query)
    if m:
        return _search_spotify_link(query, m.group(1))
    try:
        return SpotifyClient.search(query)
    except SpotifyUnavailable as e:
        logger.info(f"Spotify unavailable, metadata fallback: {e}")
    except Exception as e:
        SpotifyClient._mark_down(f"ошибка Spotify ({type(e).__name__})", 60)
        logger.error(f"Spotify search error: {e}")
    return catalog_fallback_search(query)


SOURCE_FUNCS: Dict[str, Callable[[str], List[Dict[str, Any]]]] = {
    "yandex": _search_yandex,
    "youtube": _search_youtube,
    "soundcloud": _search_soundcloud,
    "spotify": _search_spotify,
}


# ---------------------------------------------------------------------------
# Public manager
# ---------------------------------------------------------------------------

class AlternativeSourcesManager:

    @staticmethod
    def search_candidates(
        query: str,
        source: str = "all",
        ref_duration: int = 0,
        score_query: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Searches the selected source(s) in parallel, merges results into one list
        and ranks them with a unified relevance score.
        Returns {"candidates": [...], "sources": {name: {"count": n} | {"error": str}}}.
        """
        query = (query or "").strip()
        if not query:
            return {"candidates": [], "sources": {}}

        if source == "all":
            selected = list(ALL_SOURCES)
        elif source in SOURCE_FUNCS:
            selected = [source]
        else:
            selected = ["youtube"]

        # Spotify link in the box: search other sources by its resolved title
        search_query = query
        if SPOTIFY_TRACK_RE.search(query):
            try:
                sp = _search_spotify(query)
                if sp:
                    search_query = f"{sp[0].get('artist', '')} {sp[0]['title']}".strip()
                    ref_duration = ref_duration or sp[0].get("duration", 0)
            except Exception as e:
                logger.error(f"Spotify link resolve error: {e}")

        results: List[Dict[str, Any]] = []
        status: Dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=len(selected)) as pool:
            futures = {pool.submit(SOURCE_FUNCS[s], query if s == "spotify" else search_query): s for s in selected}
            for fut in as_completed(futures):
                name = futures[fut]
                try:
                    items = fut.result(timeout=SOURCE_TIMEOUT)
                    results.extend(items)
                    status[name] = {"count": len(items)}
                    # Spotify answered with fallback metadata (Deezer / iTunes)
                    if name == "spotify":
                        fb = next((c["meta_source"] for c in items if c.get("meta_source") not in (None, "Spotify")), None)
                        if fb:
                            status[name]["fallback"] = fb
                            status[name]["reason"] = SpotifyClient.last_error
                except Exception as e:
                    logger.error(f"Search error in {name}: {e}")
                    status[name] = {"error": str(e)}

        # Dedupe by id; catalog entries also by artist + title + duration
        # (Deezer / iTunes often list the same recording on several albums)
        seen = set()
        unique = []
        for c in results:
            keys = [c["id"]]
            if c.get("match_audio"):
                keys.append(("cat", _normalize(c.get("artist", "")), _normalize(c.get("title", "")), int(c.get("duration") or 0)))
            if any(k in seen for k in keys):
                continue
            seen.update(keys)
            unique.append(c)

        rank_query = score_query or search_query
        for c in unique:
            c["score"], c["match_tags"] = score_candidate(c, rank_query, ref_duration)
            # Explicit flag shown in UI: catalog flag or textual marker
            low = (c.get("title") or "").lower()
            if any(m in low for m in ("uncensored", "explicit", "dirty", "18+", "без цензуры")):
                c["is_explicit"] = True

        unique.sort(key=lambda c: c["score"], reverse=True)
        return {"candidates": unique[:MAX_RESULTS], "sources": status}

    @staticmethod
    def match_audio(artist: str, title: str, duration: int = 0) -> Optional[Dict[str, Any]]:
        """
        Best YouTube audio for catalog metadata (Spotify / Deezer / iTunes results).
        Ranked by the same relevance score, where the exact catalog duration weighs most.
        Cached, so preview + download do not search twice.
        """
        key = _cache_key("match", artist, title, int(duration or 0))
        cached = _match_cache.get(key)
        if cached is not None:
            return dict(cached)
        query = f"{artist} {title}".strip()
        cands = _search_youtube(query)
        if not cands:
            return None
        for c in cands:
            c["score"], c["match_tags"] = score_candidate(c, query, duration)
        cands.sort(key=lambda c: c["score"], reverse=True)
        best = cands[0]
        _match_cache.set(key, best)
        return dict(best)

    @staticmethod
    def match_audio_url(artist: str, title: str, duration: int = 0) -> Optional[str]:
        best = AlternativeSourcesManager.match_audio(artist, title, duration)
        return best["url"] if best else None

    @staticmethod
    def resolve_audio_page(candidate: Dict[str, Any]) -> str:
        """Returns a yt-dlp compatible page URL with the audio for a candidate."""
        url = candidate.get("url", "")
        if candidate.get("match_audio") or candidate.get("source") == "Spotify" or "open.spotify.com" in url:
            matched = AlternativeSourcesManager.match_audio_url(
                candidate.get("artist", ""), candidate.get("title", ""), int(candidate.get("duration") or 0)
            )
            if not matched:
                raise RuntimeError("Не удалось подобрать аудио на YouTube для этого трека")
            return matched
        return url

    @staticmethod
    def get_preview_audio_url(candidate: Dict[str, Any]) -> Optional[str]:
        """Direct streamable audio URL for in-app preview."""
        if candidate.get("ym_id"):
            from .yandex_api import YandexDownloader
            return YandexDownloader().get_stream_url(str(candidate["ym_id"]), preview=True)

        page_url = AlternativeSourcesManager.resolve_audio_page(candidate)
        ydl_opts = {
            "format": "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio/best",
            "quiet": True,
            "skip_download": True,
            "no_warnings": True,
            "socket_timeout": 12,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(page_url, download=False)
            return info.get("url")

    @staticmethod
    def _metadata_for(candidate: Dict[str, Any], ym_track_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if ym_track_info and ym_track_info.get("title"):
            return ym_track_info
        artist = candidate.get("artist") or ""
        title = candidate.get("title") or "Track"
        if candidate.get("source") in ("YouTube", "SoundCloud"):
            artist, title = _split_artist_title(title, artist)
        return {
            "title": title,
            "artist": artist or "Unknown",
            "album": candidate.get("album"),
            "year": candidate.get("year"),
            "cover_url": candidate.get("cover_url") or candidate.get("thumbnail"),
        }

    @staticmethod
    def download_alternative(
        candidate: Dict[str, Any],
        ym_track_info: Optional[Dict[str, Any]] = None,
        target_dir: Optional[str] = None,
        on_progress: Optional[Callable[[float, float, float, str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None
    ) -> str:
        """
        Downloads the chosen alternative and embeds metadata.
        Yandex Music results are downloaded natively in 320 kbps with their own tags.
        Other sources get the original Yandex track tags (if a track was selected),
        otherwise the candidate's own metadata.
        """
        if candidate.get("ym_id"):
            from .yandex_api import YandexDownloader
            dl = YandexDownloader()
            info = dl.get_track_info(str(candidate["ym_id"]))
            return dl.download_track(info, target_dir=target_dir, on_progress=on_progress, on_status=on_status)

        meta = AlternativeSourcesManager._metadata_for(candidate, ym_track_info)
        save_folder = target_dir or get_download_directory()
        os.makedirs(save_folder, exist_ok=True)

        filename_base = f"{sanitize_filename(meta['artist'])} - {sanitize_filename(meta['title'])}"
        out_path = os.path.join(save_folder, f"{filename_base}.mp3")
        temp_prefix = f"yasave_tmp_{int(time.time() * 1000)}"
        temp_out = os.path.join(save_folder, f"{temp_prefix}.%(ext)s")

        if on_status and candidate.get("match_audio"):
            on_status("Подбор аудио на YouTube по длительности...")
        download_url = AlternativeSourcesManager.resolve_audio_page(candidate)

        if on_status:
            src_name = candidate.get("audio_source") or candidate.get("source") or "источника"
            on_status(f"Загрузка аудио из {src_name}...")

        def progress_hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                speed = d.get("speed") or 0
                speed_str = f"{(speed / (1024 * 1024)):.1f} МБ/с" if speed else ""
                percent = (downloaded / total * 100) if total else 0.0
                if on_progress:
                    on_progress(percent, round(downloaded / 1048576, 2), round(total / 1048576, 2) if total else 0.0, speed_str)
            elif d["status"] == "finished" and on_progress:
                on_progress(100.0, 0, 0, "")

        ydl_opts = {
            "format": "bestaudio[ext=mp3]/bestaudio/best",
            "outtmpl": temp_out,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [progress_hook],
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([download_url])

        downloaded_file = None
        for f in os.listdir(save_folder):
            if f.startswith(temp_prefix) and not f.endswith(".part"):
                downloaded_file = os.path.join(save_folder, f)
                break
        if not downloaded_file:
            raise RuntimeError("Не удалось обнаружить скачанный временный файл.")

        if os.path.exists(out_path):
            os.remove(out_path)
        os.rename(downloaded_file, out_path)

        if on_status:
            on_status("Запись обложки и тегов (ID3v2)...")
        cover_data = fetch_cover_bytes(meta["cover_url"]) if meta.get("cover_url") else None
        embed_metadata(
            filepath=out_path,
            title=meta["title"],
            artist=meta["artist"],
            album=meta.get("album"),
            year=meta.get("year"),
            cover_data=cover_data,
        )
        if on_status:
            on_status("Трек успешно скачан!")
        return out_path
