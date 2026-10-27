"""
Packs android/aar/AndroidManifest.xml into android/build/yasave-media.aar.

The .aar carries only a manifest (service declaration + permissions); the Java
classes are compiled from android/src via android.add_src. Run before buildozer
(the GitHub workflow does it automatically).
"""
import io
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "android", "aar", "AndroidManifest.xml")
OUT = os.path.join(ROOT, "android", "build", "yasave-media.aar")


def empty_jar() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as jar:
        jar.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\n\r\n")
    return buf.getvalue()


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as aar:
        aar.write(SRC, "AndroidManifest.xml")
        aar.writestr("classes.jar", empty_jar())
        aar.writestr("R.txt", "")
        aar.writestr("META-INF/com/android/build/gradle/aar-metadata.properties",
                     "aarFormatVersion=1.0\naarMetadataVersion=1.0\nminCompileSdk=1\n")
    print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes)")


if __name__ == "__main__":
    main()
