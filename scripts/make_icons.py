#!/usr/bin/env python3
"""Generate the app icons from assets/icon.svg.

Usage: uv run python scripts/make_icons.py

Writes, all committed (the Windows release build can't run iconutil):

  assets/MergeMail365.icns              macOS app bundle (needs iconutil)
  assets/MergeMail365.ico               Windows executable
  src/mail_merge/web/static/icon.svg    favicon (a copy of the master)
  src/mail_merge/web/static/icon-32.png favicon for browsers without SVG ones

Rendering uses rsvg-convert (Homebrew: brew install librsvg); set
RSVG_CONVERT to use another path. The macOS icon follows Apple's grid: the
tile is 824 px wide on a 1024 px canvas, with transparent margins, so it lines
up with other apps in the Dock. Windows and the favicon use the full tile.
"""

import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / "assets" / "icon.svg"
ICNS = ROOT / "assets" / "MergeMail365.icns"
ICO = ROOT / "assets" / "MergeMail365.ico"
STATIC = ROOT / "src" / "mail_merge" / "web" / "static"

RSVG = os.environ.get("RSVG_CONVERT", "rsvg-convert")

# iconset file name -> pixel size, as iconutil expects them
ICONSET = {
    "icon_16x16.png": 16, "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32, "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128, "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256, "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512, "icon_512x512@2x.png": 1024,
}
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def macos_svg(master: str) -> str:
    """The master's drawing scaled onto Apple's 1024 grid (824 px tile)."""
    inner = re.search(r"<svg[^>]*>(.*)</svg>", master, re.S)
    if not inner:
        sys.exit(f"{MASTER}: no <svg> element")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" '
        'width="1024" height="1024">'
        f'<g transform="translate(100 100) scale(8.24)">{inner.group(1)}</g></svg>'
    )


def render(svg: Path, size: int, out: Path) -> None:
    subprocess.run([RSVG, "-w", str(size), "-h", str(size), "-o", str(out), str(svg)], check=True)


def write_ico(pngs: list[tuple[int, bytes]], out: Path) -> None:
    """An ICO file whose images are PNGs (supported since Windows Vista)."""
    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries = b""
    for size, data in pngs:
        dim = 0 if size >= 256 else size  # 0 means 256
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    out.write_bytes(header + entries + b"".join(data for _, data in pngs))


def main() -> None:
    if not shutil.which(RSVG):
        sys.exit(f"{RSVG} not found: install librsvg (brew install librsvg) or set RSVG_CONVERT")
    if not shutil.which("iconutil"):
        sys.exit("iconutil not found: the .icns can only be made on macOS")

    master = MASTER.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)

        mac = tmp / "macos.svg"
        mac.write_text(macos_svg(master), encoding="utf-8")
        iconset = tmp / "MergeMail365.iconset"
        iconset.mkdir()
        for name, size in ICONSET.items():
            render(mac, size, iconset / name)
        subprocess.run(["iconutil", "-c", "icns", "-o", str(ICNS), str(iconset)], check=True)

        pngs = []
        for size in ICO_SIZES:
            png = tmp / f"ico-{size}.png"
            render(MASTER, size, png)
            pngs.append((size, png.read_bytes()))
        write_ico(pngs, ICO)

    shutil.copyfile(MASTER, STATIC / "icon.svg")
    render(MASTER, 32, STATIC / "icon-32.png")
    for path in (ICNS, ICO, STATIC / "icon.svg", STATIC / "icon-32.png"):
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
