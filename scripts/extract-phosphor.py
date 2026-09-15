#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only
"""Extract the icons Drew uses from the Phosphor Icons release zip.

    scripts/extract-phosphor.py ~/Downloads/phosphor-icons.zip

Takes the glyph outlines from the bundled Phosphor-Bold SVG font rather
than the loose SVGs: those are stroke-based, and GTK's symbolic recolouring
forces a fill onto every path, which turns a stroked outline into a blob.
The font glyphs are filled paths, which recolour cleanly.

Phosphor Icons are MIT licensed — https://phosphoricons.com
"""

import re
import sys
import zipfile
from pathlib import Path

#: Drew icon name → Phosphor glyph name (bold weight).
ICONS = {
    "tool-select": "cursor",
    "tool-arrow": "arrow-up-right",
    "tool-line": "line-segment",
    "tool-rect": "rectangle",
    "tool-ellipse": "circle",
    "tool-text": "text-t",
    "tool-marker": "number-circle-one",
    "tool-highlighter": "highlighter",
    "tool-spotlight": "flashlight",
    "tool-blur": "drop-half",
    "tool-pixelate": "grid-four",
    "save": "floppy-disk",
    "copy": "copy",
    "menu": "list",
    "folder": "folder-open",
    "image": "image",
}

FONT = "Fonts/bold/Phosphor-Bold.svg"
OUT = Path(__file__).resolve().parent.parent / "drew/data/icons/hicolor/scalable/actions"

# Font units: 1024/em, ascent 960, y up. Map onto Phosphor's 256 box, y down.
TRANSFORM = "matrix(0.25 0 0 -0.25 0 240)"

TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" fill="currentColor" '
    'viewBox="0 0 256 256"><path transform="{transform}" d="{d}"/></svg>\n'
)


def main(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        font = zf.read(FONT).decode()
    glyphs = {}
    for match in re.finditer(r'<glyph [^>]*glyph-name="([^"]+)"[^>]*\sd="([^"]*)"', font):
        for name in match.group(1).split(","):
            glyphs[name.strip()] = match.group(2)

    OUT.mkdir(parents=True, exist_ok=True)
    missing = []
    for ours, theirs in ICONS.items():
        d = glyphs.get(f"{theirs}-bold")
        if d is None:
            missing.append(theirs)
            continue
        (OUT / f"drew-{ours}-symbolic.svg").write_text(
            TEMPLATE.format(transform=TRANSFORM, d=d))
    if missing:
        sys.exit(f"not in font: {', '.join(missing)}")
    print(f"wrote {len(ICONS)} icons to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "Downloads/phosphor-icons.zip")
