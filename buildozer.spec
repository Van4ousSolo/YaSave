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
# Not app code: CI config, local caches, native sources (added via add_src / add_assets)
source.exclude_dirs = .github,cache,android,bin,.venv,venv,tools

# (list) List of inclusions using pattern matching (commented out to include all files recursively matching include_exts)
# source.include_patterns = assets/*,core/*,web/*

# (str) Application versioning
version = 2.0.0

# (list) Application requirements
# Fully expanded dependency graph with all sub-dependencies:
# - Web framework: bottle
# - HTTP & Yandex Auth: requests, urllib3, certifi, charset-normalizer, idna, PySocks, typing_extensions
# - API & Music: yandex-music
# - Metadata & Cover Art: mutagen, pillow
# - Uncensored / Audio engine: yt-dlp
# yt-dlp is pinned: the CI cache (.buildozer) would otherwise keep an old copy forever.
# Bump the version here when YouTube / SoundCloud extraction breaks.
requirements = python3,bottle,requests,urllib3,certifi,charset-normalizer,idna,PySocks,typing_extensions,yandex-music,mutagen,pillow,yt-dlp==2026.10.26

# (str) p4a bootstrap: webview provides native Android WebView container for modern liquid glass
p4a.bootstrap = webview
p4a.port = 58231

# (str) Presplash of the application (shown on top of presplash_color while Python boots)
presplash.filename = %(source.dir)s/assets/presplash.png

# (str) Presplash background color: same dark tone as the web splash, no white flash
android.presplash_color = #0a0c12

# (list) Extra APK assets. Overrides the default p4a webview loader page
# (white screen with purple bars) with a dark one identical to the app splash.
android.add_assets = android/_load.html:_load.html,assets/icon.png:_yasave_icon.png
# Native player: Java sources (MediaSession, MediaStyle notification, foreground service)
android.add_src = android/src
# Manifest-only .aar that declares YaSaveMediaService (built by tools/make_media_aar.py in CI).
# p4a puts .aar files into libs/ and references them by name, so Gradle needs a flatDir repo.
android.add_aars = android/build/yasave-media.aar
android.add_gradle_repositories = flatDir { dirs 'libs' }
# Thin outline notification icons (vector drawables) -> res/drawable
android.add_resources = android/res/drawable:drawable

# (str) Icon of the application
icon.filename = %(source.dir)s/assets/icon.png

# (str) Supported orientation (one of landscape, sensorLandscape, portrait or all)
orientation = portrait

# (list) Permissions
# FOREGROUND_SERVICE* + POST_NOTIFICATIONS + WAKE_LOCK: player in the shade / lock screen;
# REQUEST_IGNORE_BATTERY_OPTIMIZATIONS: "allow background" button for aggressive OEMs (vivo)
android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE,FOREGROUND_SERVICE,FOREGROUND_SERVICE_MEDIA_PLAYBACK,POST_NOTIFICATIONS,WAKE_LOCK,REQUEST_IGNORE_BATTERY_OPTIMIZATIONS

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
