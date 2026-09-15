# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

"""Annotations as geometry.

Everything the user draws is an object that stays editable until export.
This module is pure geometry and style — no Cairo, no GTK — so it can be
reasoned about (and later tested) without a display. Drawing lives in
render.py, interaction in tools.py.

Coordinates are image pixels. Handles are named points the Select tool can
drag; `drag_handle` is the inverse: given a handle name and a new point,
update the shape.
"""

import itertools
import math
from dataclasses import dataclass, field

_ids = itertools.count(1)


@dataclass
class Style:
    #: RGBA in 0..1.
    stroke: tuple = (0.878, 0.106, 0.141, 1.0)  # GNOME red 3
    width: float = 4.0
    #: None for outline only.
    fill: tuple | None = None
    #: Text size in image pixels.
    font_size: float = 24.0


@dataclass(eq=False)
class Annotation:
    style: Style = field(default_factory=Style)
    id: int = field(default_factory=lambda: next(_ids))

    def bounds(self):
        """(x, y, w, h) enclosing the shape, ignoring stroke width."""
        raise NotImplementedError

    def move(self, dx, dy):
        raise NotImplementedError

    def handles(self):
        """List of (name, x, y)."""
        raise NotImplementedError

    def drag_handle(self, name, x, y):
        raise NotImplementedError

    def hit(self, x, y, tolerance):
        """True if (x, y) is on the shape, within `tolerance` pixels."""
        raise NotImplementedError

    def hit_tolerance(self, base):
        return max(base, self.style.width / 2 + base / 2)

    def is_degenerate(self):
        """True if the shape is too small to be meant — dropped on release."""
        x, y, w, h = self.bounds()
        return w < 3 and h < 3


@dataclass(eq=False)
class Rect(Annotation):
    """Axis-aligned rectangle given by two opposite corners (any order)."""
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0

    def bounds(self):
        x, y = min(self.x1, self.x2), min(self.y1, self.y2)
        return x, y, abs(self.x2 - self.x1), abs(self.y2 - self.y1)

    def normalize(self):
        """Make (x1, y1) the top-left; call after a drag has finished."""
        x, y, w, h = self.bounds()
        self.x1, self.y1, self.x2, self.y2 = x, y, x + w, y + h

    def move(self, dx, dy):
        self.x1 += dx; self.x2 += dx
        self.y1 += dy; self.y2 += dy

    def handles(self):
        x, y, w, h = self.bounds()
        cx, cy = x + w / 2, y + h / 2
        return [
            ("nw", x, y), ("n", cx, y), ("ne", x + w, y),
            ("w", x, cy), ("e", x + w, cy),
            ("sw", x, y + h), ("s", cx, y + h), ("se", x + w, y + h),
        ]

    def drag_handle(self, name, x, y):
        # Handles are named for the normalized rect; normalize first so the
        # names mean what they say even after a corner was dragged across.
        self.normalize()
        if "w" in name: self.x1 = x
        if "e" in name: self.x2 = x
        if "n" in name: self.y1 = y
        if "s" in name: self.y2 = y

    def hit(self, x, y, tolerance):
        bx, by, w, h = self.bounds()
        t = self.hit_tolerance(tolerance)
        inside_outer = bx - t <= x <= bx + w + t and by - t <= y <= by + h + t
        if self.style.fill is not None:
            return inside_outer
        inside_inner = bx + t < x < bx + w - t and by + t < y < by + h - t
        return inside_outer and not inside_inner


@dataclass(eq=False)
class Arrow(Annotation):
    """Straight arrow from tail (x1, y1) to head (x2, y2)."""
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0

    def bounds(self):
        x, y = min(self.x1, self.x2), min(self.y1, self.y2)
        return x, y, abs(self.x2 - self.x1), abs(self.y2 - self.y1)

    def move(self, dx, dy):
        self.x1 += dx; self.x2 += dx
        self.y1 += dy; self.y2 += dy

    def handles(self):
        return [("tail", self.x1, self.y1), ("head", self.x2, self.y2)]

    def drag_handle(self, name, x, y):
        if name == "tail":
            self.x1, self.y1 = x, y
        else:
            self.x2, self.y2 = x, y

    def head_size(self):
        return self.style.width * 3 + 6

    def hit(self, x, y, tolerance):
        t = self.hit_tolerance(tolerance) + self.head_size() / 2
        return _point_segment_distance(x, y, self.x1, self.y1,
                                       self.x2, self.y2) <= t

    def is_degenerate(self):
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1) < 3


@dataclass(eq=False)
class Line(Arrow):
    """Straight line; an Arrow without the head."""

    def head_size(self):
        return 0.0


@dataclass(eq=False)
class Ellipse(Rect):
    """Ellipse inscribed in the rectangle (x1, y1)-(x2, y2)."""

    def hit(self, x, y, tolerance):
        bx, by, w, h = self.bounds()
        rx, ry = w / 2, h / 2
        if rx <= 0 or ry <= 0:
            return False
        # Distance from the outline, approximated by comparing the point's
        # normalized radius with 1 and scaling back by the smaller radius.
        nx, ny = (x - bx - rx) / rx, (y - by - ry) / ry
        r = math.hypot(nx, ny)
        t = self.hit_tolerance(tolerance)
        if self.style.fill is not None:
            return r <= 1 + t / min(rx, ry)
        return abs(r - 1) * min(rx, ry) <= t


@dataclass(eq=False)
class Region(Rect):
    """A rectangle that acts on the image under it rather than drawing on
    top; hit anywhere inside, never styled."""

    def hit(self, x, y, tolerance):
        bx, by, w, h = self.bounds()
        t = tolerance
        return bx - t <= x <= bx + w + t and by - t <= y <= by + h + t


@dataclass(eq=False)
class Spotlight(Region):
    """Everything outside all Spotlight regions is dimmed."""


@dataclass(eq=False)
class Highlighter(Region):
    """A translucent wash of the stroke colour, like a marker pen: what is
    under it stays readable."""


@dataclass(eq=False)
class Blur(Region):
    """The image under the region is blurred or pixelated.

    Strength follows the style's line width so the one slider covers it:
    blur radius and pixel block both grow with it.
    """
    mode: str = "blur"  # "blur" | "pixelate"

    def strength(self):
        return int(self.style.width)


@dataclass(eq=False)
class Text(Annotation):
    """A run of text anchored at its top-left corner.

    The model cannot measure text (that needs Pango), so `width`/`height`
    are a cache the renderer fills in each time it draws or measures the
    text; until then the box is empty and unhittable.
    """
    x: float = 0.0
    y: float = 0.0
    text: str = ""
    width: float = 0.0
    height: float = 0.0

    def padding(self):
        """Space around the glyphs when drawn as a filled chip."""
        return self.style.font_size * 0.3 if self.style.fill is not None else 0.0

    def bounds(self):
        p = self.padding()
        return self.x - p, self.y - p, self.width + 2 * p, self.height + 2 * p

    def move(self, dx, dy):
        self.x += dx
        self.y += dy

    def handles(self):
        return []

    def drag_handle(self, name, x, y):
        pass

    def hit(self, x, y, tolerance):
        bx, by, w, h = self.bounds()
        t = tolerance
        return bx - t <= x <= bx + w + t and by - t <= y <= by + h + t

    def is_degenerate(self):
        return not self.text.strip()


@dataclass(eq=False)
class Marker(Annotation):
    """A numbered disc — ①②③ — for step-by-step callouts."""
    cx: float = 0.0
    cy: float = 0.0
    number: int = 1

    def radius(self):
        return self.style.width * 2 + 8

    def bounds(self):
        r = self.radius()
        return self.cx - r, self.cy - r, 2 * r, 2 * r

    def move(self, dx, dy):
        self.cx += dx
        self.cy += dy

    def handles(self):
        return []

    def drag_handle(self, name, x, y):
        pass

    def hit(self, x, y, tolerance):
        return math.hypot(x - self.cx, y - self.cy) <= self.radius() + tolerance

    def is_degenerate(self):
        return False


def _point_segment_distance(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def constrain_square(x1, y1, x2, y2):
    """Snap the second corner so the box is square, keeping its direction."""
    side = max(abs(x2 - x1), abs(y2 - y1))
    return x1 + math.copysign(side, x2 - x1), y1 + math.copysign(side, y2 - y1)


def constrain_angle(x1, y1, x2, y2, step=math.pi / 4):
    """Snap the end point so the segment lies on a multiple of `step`."""
    length = math.hypot(x2 - x1, y2 - y1)
    angle = round(math.atan2(y2 - y1, x2 - x1) / step) * step
    return x1 + length * math.cos(angle), y1 + length * math.sin(angle)
