# PyInstaller recipe for Anon Brain.exe  (build_exe.bat runs this for you)
#
#   py -m PyInstaller anonbrain.spec --noconfirm
#
# Output: dist\Anon Brain\Anon Brain.exe  (+ an _internal folder with everything it needs)

import importlib.util
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

datas = [("assets", "assets")]
binaries = []
hiddenimports = []


def take(pkg):
    if importlib.util.find_spec(pkg) is None:
        print(f"[anonbrain.spec] {pkg} not installed, skipping")
        return
    d, b, h = collect_all(pkg)
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)


# OCR, free voices (Kokoro + espeak), Piper voices, saved keys
for pkg in ("rapidocr_onnxruntime", "kokoro_onnx", "espeakng_loader",
            "phonemizer", "language_tags", "segments", "csvw", "piper", "keyring",
            "win32ctypes"):
    take(pkg)
# wordninja keeps its word list in a "wordninja" folder next to wordninja.py
import wordninja as _wn
_wl = os.path.join(os.path.dirname(_wn.__file__), "wordninja", "wordninja_words.txt.gz")
if os.path.isfile(_wl):
    datas.append((_wl, "wordninja"))
datas += collect_data_files("wordninja")
for dist in ("keyring", "kokoro-onnx", "rapidocr_onnxruntime"):
    try:
        datas += copy_metadata(dist)
    except Exception:
        pass
hiddenimports += ["keyring.backends.Windows", "win32ctypes.core", "win32ctypes.pywin32",
                  "anonbrain.posting.tiktok", "anonbrain.posting.youtube",
                  "anonbrain.posting.instagram"]

# FFmpeg ships inside the app (build_exe.bat puts it in build_tools\ffmpeg)
for tool in ("ffmpeg", "ffprobe"):
    for name in (tool + ".exe", tool):
        p = os.path.join("build_tools", "ffmpeg", name)
        if os.path.isfile(p):
            binaries.append((p, "ffmpeg"))
for f in os.listdir(os.path.join("build_tools", "ffmpeg")) if os.path.isdir(
        os.path.join("build_tools", "ffmpeg")) else []:
    if f.lower().endswith(".dll"):                      # "shared" FFmpeg builds
        binaries.append((os.path.join("build_tools", "ffmpeg", f), "ffmpeg"))

# Big parts of Qt the app never uses
excludes = ["tests", "tkinter", "matplotlib", "IPython", "pytest", "pandas", "scipy", "torch",
            "onnxruntime.transformers", "piper.train", "onnxruntime.tools", "onnxruntime.quantization",
            "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
            "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DExtras", "PySide6.QtCharts",
            "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtQuick3D",
            "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtDesigner",
            "PySide6.QtBluetooth", "PySide6.QtSensors", "PySide6.QtSerialPort",
            "PySide6.QtLocation", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
            "PySide6.QtTextToSpeech", "PySide6.QtHttpServer", "PySide6.QtWebSockets"]

a = Analysis(["app.py"], pathex=["."], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, excludes=excludes, noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Anon Brain",
          icon="assets/icon.ico" if sys.platform == "win32" else None,
          console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="Anon Brain")
