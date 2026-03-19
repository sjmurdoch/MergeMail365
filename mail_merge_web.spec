# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for bundling mail-merge web UI as a standalone app."""

import os
import sys

block_cipher = None

# Locate source files
src_dir = os.path.join("src", "mail_merge")
web_dir = os.path.join(src_dir, "web")

a = Analysis(
    [os.path.join(web_dir, "__init__.py")],
    pathex=[os.path.join(os.getcwd(), "src")],
    binaries=[],
    datas=[
        (os.path.join(web_dir, "templates"), os.path.join("mail_merge", "web", "templates")),
        (os.path.join(web_dir, "static"), os.path.join("mail_merge", "web", "static")),
    ],
    hiddenimports=[
        "mail_merge",
        "mail_merge.web",
        "mail_merge.web.app",
        "mail_merge.api",
        "mail_merge.auth",
        "mail_merge.config",
        "mail_merge.console",
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
    runtime_hooks=[],
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
    name="mail-merge-web",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window in desktop mode
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
    name="mail-merge-web",
)

# macOS .app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Mail Merge.app",
        icon=None,
        bundle_identifier="com.mail-merge.web",
        info_plist={
            "CFBundleName": "Mail Merge",
            "CFBundleDisplayName": "Mail Merge",
            "CFBundleVersion": "0.1.0",
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
        },
    )
