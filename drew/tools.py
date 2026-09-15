# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

"""Pointer interaction, one state machine per tool.

A tool gets press/drag/release in image coordinates plus the modifier
state, and mutates the canvas's document and selection. Shape tools hand
back to Select as soon as the shape exists, so "draw it, then nudge it"
needs no mode switch.
"""

import copy
import math

import gi
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk

from drew.model import (Arrow, Blur, Ellipse, Highlighter, Line, Marker,
                        Rect, Spotlight, Text, constrain_angle,
                        constrain_square)

#: Radius around a handle, in widget pixels, that counts as grabbing it.
HANDLE_GRAB_PX = 8
#: Distance from a shape's outline, in widget pixels, that counts as a hit.
HIT_PX = 6

_RESIZE_CURSORS = {
    "n": "n-resize", "s": "s-resize", "e": "e-resize", "w": "w-resize",
    "nw": "nw-resize", "ne": "ne-resize", "sw": "sw-resize", "se": "se-resize",
}


class Tool:
    cursor = "default"

    def __init__(self, canvas):
        self.canvas = canvas

    @property
    def doc(self):
        return self.canvas.doc

    def press(self, x, y, mods):
        pass

    def drag(self, x, y, mods):
        pass

    def release(self, x, y, mods):
        """Return True if the document changed, so the canvas commits."""
        return False

    def cursor_at(self, x, y):
        return self.cursor


class SelectTool(Tool):
    def __init__(self, canvas):
        super().__init__(canvas)
        self._mode = None       # "move" | "resize" | None
        self._handle = None
        self._last = self._press = (0.0, 0.0)

    def _handle_at(self, x, y):
        selected = self.canvas.selection
        if selected is None:
            return None
        radius = HANDLE_GRAB_PX / self.canvas.scale
        for name, hx, hy in selected.handles():
            if math.hypot(hx - x, hy - y) <= radius:
                return name
        return None

    def press(self, x, y, mods):
        self._last = self._press = (x, y)
        handle = self._handle_at(x, y)
        if handle is not None:
            self._mode, self._handle = "resize", handle
            return
        hit = self.doc.annotation_at(x, y, HIT_PX / self.canvas.scale)
        self.canvas.select(hit)
        self._mode = "move" if hit is not None else None

    def drag(self, x, y, mods):
        selected = self.canvas.selection
        if selected is None or self._mode is None:
            return
        if self._mode == "move":
            lx, ly = self._last
            selected.move(x - lx, y - ly)
            self._last = (x, y)
        else:
            selected.drag_handle(self._handle, x, y)
        self.canvas.changed()

    def release(self, x, y, mods):
        selected = self.canvas.selection
        if self._mode == "resize" and isinstance(selected, Rect):
            selected.normalize()
        changed = self._mode is not None and (x, y) != self._press
        self._mode = self._handle = None
        return changed

    def cursor_at(self, x, y):
        handle = self._handle_at(x, y)
        if handle is not None:
            return _RESIZE_CURSORS.get(handle, "move")
        if self.doc.annotation_at(x, y, HIT_PX / self.canvas.scale):
            return "move"
        return "default"


class ShapeTool(Tool):
    """Drag out a new shape from press point to release point."""
    cursor = "crosshair"
    #: Annotation class to create.
    shape = None

    def __init__(self, canvas):
        super().__init__(canvas)
        self._current = None
        self._origin = (0.0, 0.0)

    def press(self, x, y, mods):
        self._origin = (x, y)
        self._current = self.shape(style=copy.deepcopy(self.canvas.style),
                                   x1=x, y1=y, x2=x, y2=y)
        self.doc.add(self._current)
        self.canvas.select(self._current)

    def drag(self, x, y, mods):
        if self._current is None:
            return
        ox, oy = self._origin
        if mods & Gdk.ModifierType.SHIFT_MASK:
            x, y = self.constrain(ox, oy, x, y)
        self._current.x2, self._current.y2 = x, y
        self.canvas.changed()

    def release(self, x, y, mods):
        shape = self._current
        self._current = None
        if shape is None:
            return
        if shape.is_degenerate():
            self.doc.remove(shape)
            self.canvas.select(None)
            self.canvas.changed()
            return False
        if isinstance(shape, Rect):
            shape.normalize()
        self.canvas.request_tool("select")
        return True

    @staticmethod
    def constrain(ox, oy, x, y):
        return x, y


class RectTool(ShapeTool):
    shape = Rect
    constrain = staticmethod(constrain_square)


class EllipseTool(RectTool):
    shape = Ellipse


class HighlighterTool(RectTool):
    shape = Highlighter


class SpotlightTool(RectTool):
    shape = Spotlight


class BlurTool(RectTool):
    shape = Blur


class PixelateTool(RectTool):
    @staticmethod
    def shape(**kwargs):
        return Blur(mode="pixelate", **kwargs)


class ArrowTool(ShapeTool):
    shape = Arrow
    constrain = staticmethod(constrain_angle)


class LineTool(ArrowTool):
    shape = Line


class TextTool(Tool):
    """Click to place text; the canvas opens an editor for it."""
    cursor = "text"

    def press(self, x, y, mods):
        text = Text(style=copy.deepcopy(self.canvas.style), x=x, y=y)
        self.doc.add(text)
        self.canvas.select(text)

    def release(self, x, y, mods):
        # The editor commits (or removes the empty text) when it closes.
        self.canvas.edit_text(self.canvas.selection)
        self.canvas.request_tool("select")
        return False


class MarkerTool(Tool):
    """Click to drop the next number; drag to place it before letting go.

    Stays active after a click: markers come in runs (1, 2, 3, …), so
    handing back to Select after each one would be a chore.
    """
    cursor = "crosshair"

    def __init__(self, canvas):
        super().__init__(canvas)
        self._current = None

    def press(self, x, y, mods):
        self._current = Marker(style=copy.deepcopy(self.canvas.style),
                               cx=x, cy=y,
                               number=self.doc.next_marker_number())
        self.doc.add(self._current)
        self.canvas.select(self._current)

    def drag(self, x, y, mods):
        if self._current is not None:
            self._current.cx, self._current.cy = x, y
            self.canvas.changed()

    def release(self, x, y, mods):
        self._current = None
        return True


TOOLS = {
    "select": SelectTool,
    "arrow": ArrowTool,
    "line": LineTool,
    "rect": RectTool,
    "ellipse": EllipseTool,
    "text": TextTool,
    "marker": MarkerTool,
    "highlighter": HighlighterTool,
    "spotlight": SpotlightTool,
    "blur": BlurTool,
    "pixelate": PixelateTool,
}
