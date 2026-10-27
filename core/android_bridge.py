"""
Android glue through pyjnius.

IMPORTANT: app classes (org.kivy.*, org.yasave.*) must be resolved on the MAIN
Python thread. pyjnius autoclass() uses plain JNI FindClass; on a thread created
by Python (threading.Thread, the HTTP server) FindClass uses the system class
loader and fails with
    ClassNotFoundException ... DexPathList[[directory "."]]
even though the class is in the APK. preload() is called from main.py before the
server starts; afterwards autoclass() returns the cached class on any thread.

Status checks and settings shortcuts use only framework classes, so they keep
working even if our own Java classes failed to load.
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("yasave.android")

APP_CLASSES = (
    "org.kivy.android.PythonActivity",
    "org.yasave.media.YaSavePlayer",
    "org.yasave.media.YaSaveMediaService",
)
FRAMEWORK_CLASSES = (
    "android.content.Context",
    "android.content.Intent",
    "android.net.Uri",
    "android.os.Build$VERSION",
    "android.provider.Settings",
)
CHANNEL_ID = "yasave_playback"
POST_NOTIFICATIONS = "android.permission.POST_NOTIFICATIONS"

_classes: Dict[str, Any] = {}
_errors: Dict[str, str] = {}
_notif_requested_once = False


def is_android() -> bool:
    from .storage import is_android as _is
    return _is()


def preload():
    """Resolve app + framework classes on the main thread (see module docstring)."""
    if not is_android():
        return
    try:
        from jnius import autoclass  # type: ignore
    except Exception as e:
        _errors["jnius"] = str(e)
        logger.error(f"preload: pyjnius unavailable: {e}")
        return
    for name in APP_CLASSES + FRAMEWORK_CLASSES:
        try:
            _classes[name] = autoclass(name)
            logger.info(f"preload: {name} ok")
        except Exception as e:
            _errors[name] = f"{type(e).__name__}: {e}"
            logger.error(f"preload: {name} FAILED: {e}")


def jclass(name: str):
    if name in _classes:
        return _classes[name]
    from jnius import autoclass  # type: ignore
    try:
        cls = autoclass(name)  # framework classes resolve on any thread
        _classes[name] = cls
        return cls
    except Exception as first:
        # Fallback: resolve inside a Java callback on the UI thread. The native frame then
        # belongs to org.jnius.NativeInvocationHandler (an app class), so FindClass uses
        # the app ClassLoader.
        try:
            cls = _autoclass_on_ui_thread(name)
            _classes[name] = cls
            logger.info(f"jclass: {name} resolved via UI thread")
            return cls
        except Exception as e:
            hint = _errors.get(name, "")
            logger.error(f"jclass: {name} not found ({first}); UI-thread fallback: {e}")
            raise RuntimeError(f"класс {name} не загружен: {first}" + (f" (при старте: {hint})" if hint else "")) from e


def _autoclass_on_ui_thread(name: str, timeout: float = 5.0):
    import threading
    from jnius import autoclass  # type: ignore
    from android.runnable import run_on_ui_thread  # type: ignore
    box: Dict[str, Any] = {}
    done = threading.Event()

    @run_on_ui_thread
    def _load():
        try:
            box["cls"] = autoclass(name)
        except Exception as e:  # pragma: no cover - Android only
            box["err"] = e
        finally:
            done.set()

    _load()
    if not done.wait(timeout):
        raise TimeoutError("UI thread did not respond")
    if "err" in box:
        raise box["err"]
    return box["cls"]


def class_errors() -> Dict[str, str]:
    return dict(_errors)


def activity():
    act = jclass("org.kivy.android.PythonActivity").mActivity
    if act is None:
        raise RuntimeError("PythonActivity.mActivity = null")
    return act


def sdk_int() -> int:
    try:
        return int(jclass("android.os.Build$VERSION").SDK_INT)
    except Exception:
        return 0


def _service(name_const: str, cls_name: str):
    from jnius import cast  # type: ignore
    Context = jclass("android.content.Context")
    return cast(cls_name, activity().getSystemService(getattr(Context, name_const)))


def _check(fn) -> Dict[str, Any]:
    try:
        return {"value": fn()}
    except Exception as e:
        logger.warning(f"status check failed: {e}")
        return {"value": None, "reason": f"{type(e).__name__}: {e}"[:200]}


def system_status() -> Dict[str, Any]:
    """Tri-state checks: value True / False, or None + reason when it could not be determined."""
    if not is_android():
        return {"android": False}
    sdk = sdk_int()
    act = activity()
    pkg = act.getPackageName()

    def notif_permission():
        if sdk < 33:
            return True  # not a runtime permission before Android 13
        return act.checkSelfPermission(POST_NOTIFICATIONS) == 0

    def notifications_enabled():
        nm = _service("NOTIFICATION_SERVICE", "android.app.NotificationManager")
        enabled = bool(nm.areNotificationsEnabled()) if sdk >= 24 else True
        if enabled and sdk >= 26:
            ch = nm.getNotificationChannel(CHANNEL_ID)
            if ch is not None and ch.getImportance() == 0:  # IMPORTANCE_NONE: channel switched off
                return False
        return enabled

    def battery():
        if sdk < 23:
            return True
        pm = _service("POWER_SERVICE", "android.os.PowerManager")
        return bool(pm.isIgnoringBatteryOptimizations(pkg))

    return {
        "android": True,
        "sdk": sdk,
        "notification_permission": _check(notif_permission),
        "notifications_enabled": _check(notifications_enabled),
        "battery_unrestricted": _check(battery),
        "class_errors": class_errors(),
    }


def _start(intent) -> bool:
    try:
        Intent = jclass("android.content.Intent")
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        activity().startActivity(intent)
        logger.info(f"settings: opened {intent.getAction() or intent.getComponent()}")
        return True
    except Exception as e:
        logger.warning(f"settings: cannot open {intent}: {e}")
        return False


def open_settings(which: str) -> bool:
    Intent = jclass("android.content.Intent")
    Settings = jclass("android.provider.Settings")
    Uri = jclass("android.net.Uri")
    pkg = activity().getPackageName()
    pkg_uri = Uri.parse(f"package:{pkg}")

    def details():
        i = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
        i.setData(pkg_uri)
        return i

    candidates = []
    if which == "notifications" and sdk_int() >= 26:
        i = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
        i.putExtra(Settings.EXTRA_APP_PACKAGE, pkg)
        candidates.append(i)
    elif which == "battery" and sdk_int() >= 23:
        i = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
        i.setData(pkg_uri)
        candidates += [i, Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)]
    elif which == "autostart":
        # vivo / iQOO (Origin OS, Funtouch) background & autostart managers
        for comp_pkg, comp_cls in (
            ("com.vivo.permissionmanager", "com.vivo.permissionmanager.activity.BgStartUpManagerActivity"),
            ("com.iqoo.secure", "com.iqoo.secure.ui.phoneoptimize.BgStartUpManager"),
            ("com.iqoo.secure", "com.iqoo.secure.ui.phoneoptimize.AddWhiteListActivity"),
        ):
            i = Intent()
            i.setClassName(comp_pkg, comp_cls)
            candidates.append(i)
    candidates.append(details())
    return any(_start(i) for i in candidates)


def request_notification_permission() -> str:
    """
    Android 13+: runtime request; if it was already denied permanently
    (no rationale after a request), open the app's notification settings.
    """
    global _notif_requested_once
    if not is_android():
        return "not_android"
    if sdk_int() < 33:
        return "not_needed"
    act = activity()
    if act.checkSelfPermission(POST_NOTIFICATIONS) == 0:
        return "granted"
    if _notif_requested_once and not act.shouldShowRequestPermissionRationale(POST_NOTIFICATIONS):
        logger.info("permission: permanently denied -> notification settings")
        open_settings("notifications")
        return "opened_settings"
    from android.permissions import request_permissions  # type: ignore
    request_permissions([POST_NOTIFICATIONS])
    _notif_requested_once = True
    logger.info("permission: POST_NOTIFICATIONS requested")
    return "requested"


def share_text(subject: str, text: str) -> bool:
    Intent = jclass("android.content.Intent")
    i = Intent(Intent.ACTION_SEND)
    i.setType("text/plain")
    i.putExtra(Intent.EXTRA_SUBJECT, subject)
    i.putExtra(Intent.EXTRA_TEXT, text)
    from jnius import autoclass, cast  # type: ignore
    title = cast("java.lang.CharSequence", autoclass("java.lang.String")(subject))
    return _start(Intent.createChooser(i, title))
