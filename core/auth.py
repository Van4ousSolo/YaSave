import time
import threading
import logging
from typing import Optional, Callable
from yandex_music import Client
from yandex_music.exceptions import DeviceAuthError, UnauthorizedError
from .config import ConfigManager

logger = logging.getLogger(__name__)

class AuthManager:
    def __init__(self):
        self.config = ConfigManager.get_instance()
        self._polling_active = False
        self._polling_thread: Optional[threading.Thread] = None

    def get_client(self, token: Optional[str] = None) -> Optional[Client]:
        tok = token or self.config.token
        if not tok:
            return None
        try:
            client = Client(tok).init()
            return client
        except Exception as e:
            logger.error(f"Failed to initialize client with token: {e}")
            return None

    def validate_token(self, token: str) -> tuple[bool, str]:
        """Returns (is_valid, account_name or error_message)"""
        if not token:
            return False, "Токен пуст"
        try:
            client = Client(token).init()
            # check account
            status = client.account_status()
            account = status.account
            name = account.full_name or account.login or "Пользователь Яндекса"
            has_sub = False
            if hasattr(status, 'plus') and status.plus and status.plus.has_plus:
                has_sub = True
            elif hasattr(account, 'has_plus') and account.has_plus:
                has_sub = True
                
            sub_text = " (Плюс активен)" if has_sub else " (Без подписки)"
            return True, f"{name}{sub_text}"
        except UnauthorizedError:
            return False, "Неверный токен авторизации"
        except Exception as e:
            return False, f"Ошибка проверки: {str(e)}"

    def request_device_flow(self) -> dict:
        """Starts official Yandex OAuth Device Flow.
        Returns dict with: user_code, verification_url, device_code, interval
        """
        client = Client()
        device_code_obj = client.request_device_code(
            device_name="YaSave Android"
        )
        return {
            "user_code": device_code_obj.user_code,
            "verification_url": device_code_obj.verification_url or "https://ya.ru/device",
            "device_code": device_code_obj.device_code,
            "interval": getattr(device_code_obj, 'interval', 5) or 5,
            "expires_in": getattr(device_code_obj, 'expires_in', 300) or 300
        }

    def start_device_polling(
        self,
        device_code: str,
        interval: int = 5,
        on_success: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None
    ):
        """Polls for OAuth token until authorization is approved or expires."""
        self.stop_device_polling()
        self._polling_active = True

        def worker():
            client = Client()
            start_time = time.time()
            max_wait = 360  # 6 minutes

            while self._polling_active and (time.time() - start_time < max_wait):
                time.sleep(interval)
                if not self._polling_active:
                    break

                try:
                    oauth_token = client.poll_device_token(device_code)
                    if oauth_token and oauth_token.access_token:
                        token_str = oauth_token.access_token
                        self.config.token = token_str
                        self._polling_active = False
                        if on_success:
                            on_success(token_str)
                        return
                except DeviceAuthError as e:
                    # Expired or denied
                    err_str = str(e).lower()
                    if "expired" in err_str:
                        self._polling_active = False
                        if on_error:
                            on_error("Время ожидания кода истекло")
                        return
                    elif "denied" in err_str:
                        self._polling_active = False
                        if on_error:
                            on_error("Вход был отклонён пользователем")
                        return
                except Exception as e:
                    logger.debug(f"Polling check error (normal during pending): {e}")

            if self._polling_active:
                self._polling_active = False
                if on_error:
                    on_error("Время ожидания истекло")

        self._polling_thread = threading.Thread(target=worker, daemon=True)
        self._polling_thread.start()

    def stop_device_polling(self):
        self._polling_active = False
        self._polling_thread = None
