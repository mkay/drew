# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

"""Persistent preferences: a small JSON file under XDG_CONFIG_HOME.

Kept as a plain file rather than GSettings so the app runs straight from
a source tree and from a package alike, with nothing to compile or
install first.
"""

import json
import os
from pathlib import Path

DEFAULTS = {
    #: Folder Save writes into; "" means the XDG Pictures folder.
    "save_dir": "",
    #: File name stem before the timestamp.
    "filename_prefix": "screenshot",
    #: Drawing style at startup — the last one used. Keys mirror
    #: model.Style; stroke is a list and fill a bool for JSON's sake.
    "stroke": [0.878, 0.106, 0.141, 1.0],
    "width": 4.0,
    "fill": False,
    "font_size": 24.0,
    "marker_size": 16.0,
    "opacity": 0.45,
    "dim": 0.6,
    "blur": 8.0,
    "block": 12.0,
}
STYLE_KEYS = ("stroke", "width", "fill", "font_size", "marker_size",
              "opacity", "dim", "blur", "block")


class Settings:
    def __init__(self):
        config_home = Path(os.environ.get("XDG_CONFIG_HOME",
                                          Path.home() / ".config"))
        self.path = config_home / "drew" / "settings.json"
        self._values = dict(DEFAULTS)
        self._load()

    def _load(self):
        try:
            with open(self.path) as f:
                stored = json.load(f)
        except (OSError, ValueError):
            return
        for key, default in DEFAULTS.items():
            if key not in stored:
                continue
            value = stored[key]
            if _same_kind(value, default):
                self._values[key] = value

    def style(self):
        """The stored drawing style as a model Style."""
        from drew.model import Style
        values = {key: self.get(key) for key in STYLE_KEYS}
        stroke = tuple(values.pop("stroke"))
        fill = stroke if values.pop("fill") else None
        return Style(stroke=stroke, fill=fill, **values)

    def save_style(self, style):
        for key in STYLE_KEYS:
            self._values[key] = getattr(style, key)
        self._values["stroke"] = list(style.stroke)
        self._values["fill"] = style.fill is not None
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._values, f, indent=2)

    def get(self, key):
        return self._values[key]

    def set(self, key, value):
        if self._values[key] == value:
            return
        self._values[key] = value
        self.save()


def _same_kind(value, default):
    """Type check for a stored value: JSON has one number type, so an int is
    fine where we store a float — but a bool is never a number."""
    if isinstance(default, bool) or isinstance(value, bool):
        return isinstance(value, bool) and isinstance(default, bool)
    if isinstance(default, float):
        return isinstance(value, (int, float))
    if isinstance(default, list):
        return (isinstance(value, list) and len(value) == len(default)
                and all(isinstance(v, (int, float)) for v in value))
    return isinstance(value, type(default))
