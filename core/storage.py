import os
import sys
import re
import logging
from .config import ConfigManager

logger = logging.getLogger(__name__)

def is_android() -> bool:
    if hasattr(sys, 'getandroidapilevel'):
        return True
    if 'ANDROID_BOOTSTRAP' in os.environ or 'ANDROID_ROOT' in os.environ or 'PYTHON_SERVICE_ARGUMENT' in os.environ:
        return True
    try:
        from kivy.utils import platform
        return platform == 'android'
    except Exception:
        return False

def get_download_directory() -> str:
    config = ConfigManager.get_instance()
    custom_dir = config.download_dir
    if custom_dir and os.path.exists(custom_dir):
        return custom_dir

    if is_android():
        try:
            from android.storage import primary_external_storage_path  # type: ignore
            download_path = os.path.join(primary_external_storage_path(), 'Download')
            if not os.path.exists(download_path):
                os.makedirs(download_path, exist_ok=True)
            return download_path
        except Exception:
            fallback = '/storage/emulated/0/Download'
            if os.path.exists(fallback):
                return fallback
            return '/sdcard/Download'

    # Windows / Desktop
    home_downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    yasave_dir = os.path.join(home_downloads, "YaSave")
    os.makedirs(yasave_dir, exist_ok=True)
    return yasave_dir

def get_cache_dir(sub: str = "") -> str:
    """Writable private cache folder (next to the config file; app storage on Android)."""
    from .config import get_config_path
    path = os.path.join(os.path.dirname(get_config_path()), "cache", sub)
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:
        logger.warning(f"Cache dir {path} unavailable: {e}")
    return path

def sanitize_filename(name: str) -> str:
    # Remove prohibited filename characters: < > : " / \ | ? *
    clean = re.sub(r'[<>:"/\\|?*]', '_', name)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean[:200]
