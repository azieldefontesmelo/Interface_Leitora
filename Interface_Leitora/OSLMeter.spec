# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['interface_OSL.py'],
    pathex=[],
    binaries=[],
    datas=[('interface_OSL.kv', '.'), ('assets/UI', 'assets/UI')],
    hiddenimports=['openpyxl', 'openpyxl.cell._writer'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='OSLMeter_V4.1',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon='assets/UI/iconeOSL.ico',
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
