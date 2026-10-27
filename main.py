import os
import sys
import time
import socket
import threading
import webbrowser
import logging

# On Android stdout goes to logcat (tag "python"); every line starts with "YaSave"
# so it can be filtered:  adb logcat | findstr YaSave
logging.basicConfig(
    level=logging.INFO,
    format="YaSave %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
for _noisy in ("urllib3", "yandex_music", "charset_normalizer"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

from core import applog
applog.install()  # last 200 lines, shown in Settings -> "Диагностика плеера"

from server import start_server

PORT = 58231
HOST = "127.0.0.1"

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

def request_android_permissions():
    try:
        from android.permissions import request_permissions, Permission
        request_permissions([
            Permission.INTERNET,
            Permission.WRITE_EXTERNAL_STORAGE,
            Permission.READ_EXTERNAL_STORAGE
        ])
    except Exception as e:
        print(f"Android permissions request: {e}")

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((HOST, port)) == 0

def run_app():
    # 1. Android native execution with p4a webview bootstrap
    if is_android():
        # Must run on this (main) thread: worker threads cannot find app classes via JNI
        from core import android_bridge
        android_bridge.preload()
        request_android_permissions()
        # On Android with p4a webview bootstrap, native Java container
        # automatically connects to http://127.0.0.1:58231
        start_server(HOST, PORT)
        return

    # 2. Windows / Desktop execution
    if not is_port_in_use(PORT):
        server_thread = threading.Thread(target=start_server, args=(HOST, PORT), daemon=True)
        server_thread.start()
        time.sleep(0.3)

    url = f"http://{HOST}:{PORT}"

    # 3. Open desktop window or browser
    if "--browser" in sys.argv:
        print(f"Opening YaSave in browser: {url}")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            sys.exit(0)
    else:
        try:
            import webview
            window = webview.create_window(
                title="YaSave — Liquid Glass Downloader",
                url=url,
                width=460,
                height=860,
                min_size=(380, 600),
                background_color="#070a12"
            )
            webview.start(debug=False)
        except Exception as e:
            print(f"WebView initialization fallback: {e}")
            webbrowser.open(url)
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                sys.exit(0)

if __name__ == '__main__':
    run_app()

