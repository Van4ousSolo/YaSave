import os
import json
import logging

import sys

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "yasave_config.json"

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

def get_config_path() -> str:
    # Check for Android primary storage or user directory
    if is_android():
        try:
            from android.storage import app_storage_path # type: ignore
            return os.path.join(app_storage_path(), CONFIG_FILENAME)
        except Exception:
            return os.path.join('/data/data/org.yasave.yasave/files', CONFIG_FILENAME)
    
    # Desktop / fallback
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, CONFIG_FILENAME)

class ConfigManager:
    _instance = None

    def __init__(self):
        self.config_path = get_config_path()
        self.data = {
            "token": "",
            "user_name": "",
            "has_plus": False,
            "theme": "dark",
            "accent_color": "#FFCC00",
            "bitrate": 320,
            "download_dir": "",
            "spotify_client_id": "",
            "spotify_client_secret": ""
        }
        self.load()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = ConfigManager()
        return cls._instance

    def load(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self.data.update(saved)
            except Exception as e:
                logger.error(f"Error loading config: {e}")

    def save(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving config: {e}")

    @property
    def token(self) -> str:
        return self.data.get("token", "").strip()

    @token.setter
    def token(self, value: str):
        self.data["token"] = value.strip()
        self.save()

    @property
    def theme(self) -> str:
        return self.data.get("theme", "dark")

    @theme.setter
    def theme(self, value: str):
        self.data["theme"] = value
        self.save()

    @property
    def accent_color(self) -> str:
        return self.data.get("accent_color", "#FFCC00")

    @accent_color.setter
    def accent_color(self, value: str):
        self.data["accent_color"] = value
        self.save()

    @property
    def download_dir(self) -> str:
        return self.data.get("download_dir", "")

    @download_dir.setter
    def download_dir(self, value: str):
        self.data["download_dir"] = value
        self.save()

    @property
    def spotify_client_id(self) -> str:
        return (self.data.get("spotify_client_id") or "").strip()

    @property
    def spotify_client_secret(self) -> str:
        return (self.data.get("spotify_client_secret") or "").strip()

    def set_spotify_credentials(self, client_id: str, client_secret: str):
        self.data["spotify_client_id"] = (client_id or "").strip()
        self.data["spotify_client_secret"] = (client_secret or "").strip()
        self.save()

    @property
    def user_name(self) -> str:
        return self.data.get("user_name", "")

    @user_name.setter
    def user_name(self, value: str):
        self.data["user_name"] = value
        self.save()

    @property
    def has_plus(self) -> bool:
        return bool(self.data.get("has_plus", False))

    @has_plus.setter
    def has_plus(self, value: bool):
        self.data["has_plus"] = bool(value)
        self.save()
