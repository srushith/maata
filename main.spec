# -*- mode: python ; coding: utf-8 -*-
# Build with:  pyinstaller main.spec   ->  dist\Maata.exe

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Large libraries the app doesn't use; keeps the download small.
    excludes=['torch', 'whisper', 'scipy', 'pyautogui', 'PIL', 'matplotlib',
              'tkinter', 'pandas', 'IPython', 'pytest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Maata',
    icon='assets/icon.ico',
    version='version_info.txt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX compression tends to trigger antivirus false alarms
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
