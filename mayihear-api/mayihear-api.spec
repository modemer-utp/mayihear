# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['run.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('agents/prompts/*.prompt', 'agents/prompts'),
    ],
    hiddenimports=[
        'api.main',
        'api.controllers.transcription_controller',
        'api.controllers.insights_controller',
        'api.controllers.meeting_act_controller',
        'google.genai',
        'google.genai.types',
        'grpc',
        'grpc._cython.cygrpc',
        'langchain_google_genai',
        'langchain_core.callbacks',
        'langgraph.graph',
        'pydantic.v1',
        'docx',
        'anyio._backends._asyncio',
        'anyio._backends._trio',
        'multipart',
        'python_multipart',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'tkinter',
        'PyQt5',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='mayihear-api',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='mayihear-api',
)
