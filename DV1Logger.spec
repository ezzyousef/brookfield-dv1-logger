# -*- mode: python ; coding: utf-8 -*-
# Build with .\build.ps1, or:  python -m PyInstaller DV1Logger.spec --noconfirm
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = [
    "matplotlib.backends.backend_qtagg",
    "matplotlib.backends.backend_agg",
    "xlsxwriter",
    "openpyxl",
    "serial.tools.list_ports",
    "selftest",
] + collect_submodules("labkit")
# originpro is optional: include it when installed so the built app can drive Origin directly.
try:
    import originpro                        # noqa: F401
    hiddenimports += collect_submodules("originpro") + ["win32com.client", "pythoncom", "pywintypes"]
except ImportError:
    pass

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "IPython", "jupyter", "notebook",
              "pytest", "sphinx", "pandas.tests", "matplotlib.backends.backend_tkagg",
              "matplotlib.backends.backend_webagg"],
    noarchive=False,
    optimize=0,
)
# onedir, not onefile: onefile re-extracts its entire bundled runtime to a
# fresh %TEMP% folder on EVERY launch, which is a well-documented cause of
# flaky/slow startup (antivirus real-time scanning the newly-written
# payload each time). onedir extracts once, at install time.
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DV1Logger',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app_icon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='DV1Logger',
)
