# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for bundling MergeMail365 as a standalone app.

To hard-code Azure AD credentials into the built app, set these environment
variables before running PyInstaller:

    MERGEMAIL365_CLIENT_ID=your-client-id \\
    MERGEMAIL365_TENANT_ID=your-tenant-id \\
    uv run pyinstaller mergemail365.spec

When set, the corresponding fields in the UI are pre-filled and read-only.
When not set, users can enter them manually (or they are loaded from the
config file as usual).
"""

import os
import sys

from PyInstaller.utils.hooks import copy_metadata

block_cipher = None

# Optional: hard-code Azure AD credentials into the standalone app.
# Set via environment variables at build time.
FIXED_CLIENT_ID = os.environ.get("MERGEMAIL365_CLIENT_ID", "")
FIXED_TENANT_ID = os.environ.get("MERGEMAIL365_TENANT_ID", "")

# Locate source files
src_dir = os.path.join("src", "mail_merge")
web_dir = os.path.join(src_dir, "web")

# App icons, generated from assets/icon.svg by scripts/make_icons.py
icon_icns = os.path.join("assets", "MergeMail365.icns")
icon_ico = os.path.join("assets", "MergeMail365.ico")

# Package metadata, so the log can record which versions are bundled
# (mail_merge.diagnostics.log_environment).  pythonnet is Windows-only.
_metadata = []
for _dist in ("mergemail365", "pywebview", "pythonnet", "msal", "requests"):
    try:
        _metadata += copy_metadata(_dist)
    except Exception:
        pass

# Write a runtime hook that injects the hard-coded values as CLI arguments.
# PyInstaller runtime hooks run before the main script.
_runtime_hook = os.path.join("build", "_rt_hook_credentials.py")
os.makedirs("build", exist_ok=True)
with open(_runtime_hook, "w") as f:
    f.write(
        "import sys\n"
        f"_client_id = {FIXED_CLIENT_ID!r}\n"
        f"_tenant_id = {FIXED_TENANT_ID!r}\n"
        "if _client_id:\n"
        "    sys.argv.extend(['--client-id', _client_id])\n"
        "if _tenant_id:\n"
        "    sys.argv.extend(['--tenant-id', _tenant_id])\n"
    )

a = Analysis(
    [os.path.join(web_dir, "__init__.py")],
    pathex=[os.path.join(os.getcwd(), "src")],
    binaries=[],
    datas=[
        (os.path.join(web_dir, "templates"), os.path.join("mail_merge", "web", "templates")),
        (os.path.join(web_dir, "static"), os.path.join("mail_merge", "web", "static")),
        *_metadata,
    ],
    hiddenimports=[
        "mail_merge",
        "mail_merge.web",
        "mail_merge.web.app",
        "mail_merge.api",
        "mail_merge.auth",
        "mail_merge.config",
        "mail_merge.console",
        "mail_merge.diagnostics",
        "mail_merge.excel",
        "mail_merge.report",
        "mail_merge.sender",
        "mail_merge.template",
        "mail_merge._paths",
        "flask",
        "msal",
        "openpyxl",
        "requests",
        "email_validator",
        "rich",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[_runtime_hook],
    excludes=[],
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
    name="mergemail365",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window in desktop mode
    icon=icon_ico if sys.platform == "win32" else None,  # macOS: the BUNDLE's
    disable_windowed_traceback=False,
    argv_emulation=True,  # macOS: support dropping files onto the app
    target_arch=None,  # Set to 'universal2' for macOS Intel+ARM builds
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
    name="mergemail365",
)

# macOS .app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="MergeMail365.app",
        icon=icon_icns,
        bundle_identifier="is.murdoch.mergemail365",
        info_plist={
            "CFBundleName": "MergeMail365",
            "CFBundleDisplayName": "MergeMail365",
            "CFBundleVersion": "0.1.0",
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
        },
    )
