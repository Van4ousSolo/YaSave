[app]

# (str) Title of your application
title = YaSave

# (str) Package name
package.name = yasave

# (str) Package domain (needed for android/ios packaging)
package.domain = org.yasave

# (str) Source code where the main.py lives
source.dir = .

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,png,jpg,kv,atlas,json,html,css,js,svg,ttf,woff,woff2

# (list) List of inclusions using pattern matching (commented out to include all files recursively matching include_exts)
# source.include_patterns = assets/*,core/*,web/*

# (str) Application versioning
version = 2.0.0

# (list) Application requirements
# comma separated e.g. requirements = sqlite3,kivy
requirements = python3,bottle,requests,urllib3,certifi,mutagen,yt-dlp,pillow,charset-normalizer,idna,yandex-music

# (str) p4a bootstrap: webview provides native Android WebView container for modern liquid glass
p4a.bootstrap = webview
p4a.port = 58231

# (str) Presplash of the application
presplash.filename = %(source.dir)s/assets/cover.jpg

# (str) Icon of the application
icon.filename = %(source.dir)s/assets/icon.png

# (str) Supported orientation (one of landscape, sensorLandscape, portrait or all)
orientation = portrait

# (list) Permissions
android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE

# (int) Target Android API, should be as high as possible.
android.api = 34

# (int) Minimum API your APK / AAB will support.
android.minapi = 21

# (str) Android NDK version to use
android.ndk = 25b

# (bool) If True, then skip trying to update the Android sdk
# This can be useful to avoid excess Internet downloads or save time
# when an update is due and you just want to test/build your package
android.skip_update = False

# (bool) If True, then automatically accept all SDK license
# agreements. This is intended for automation only
android.accept_sdk_license = True

# (list) The Android archs to build for, choices: armeabi-v7a, arm64-v8a, x86, x86_64
# arm64-v8a covers 99%+ modern Android smartphones and builds significantly faster
android.archs = arm64-v8a

# (bool) enables Android auto backup feature (Android API >=23)
android.allow_backup = True

# (list) List of service to declare
#services = NAME:ENTRYPOINT_TO_PY,NAME2:ENTRYPOINT2_TO_PY

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 1
