# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

"""Draw a document onto a Cairo context, in image coordinates.

This is the single rendering path: the canvas calls it (under a scale
transform) to paint the screen, and the exporter calls it onto an image
surface to produce the file. Anything that appears in one and not the
other is a bug here, not in the callers.

Selection handles are deliberately not drawn here — they are UI, and the
canvas draws them on top.
"""

import math

import cairo
import gi
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo

from drew.filters import region_surface
from drew.model import (Arrow, Blur, Crop, Ellipse, Highlighter, Line,
                        Marker, Rect, Spotlight, Text)

FONT_FAMILY = "Sans Bold"


def render(cr, doc):
    """Image, then blur/pixelate regions, then the dim layer with holes for
    highlights, then everything drawn on top in z order. Regions act on the
    image, so they always sit below the shapes regardless of list order.

    The crop frame is not drawn: the exporter sizes its surface to it, and
    the canvas shades what lies outside as `draw_crop_shade` does."""
    cr.set_source_surface(doc.surface, 0, 0)
    cr.paint()
    for a in doc.annotations:
        if isinstance(a, Blur):
            _draw_blur(cr, a, doc)
    spots = [a for a in doc.annotations if isinstance(a, Spotlight)]
    if spots:
        _draw_dim(cr, spots, doc)
    for a in doc.annotations:
        if not isinstance(a, (Blur, Spotlight, Crop)):
            draw_annotation(cr, a)


def draw_crop_shade(cr, doc):
    """Darken what the crop frame leaves out and outline the frame. UI, not
    output — the canvas calls it after `render`."""
    crop = doc.crop
    if crop is None:
        return
    cr.save()
    cr.new_path()
    cr.rectangle(0, 0, doc.width, doc.height)
    cr.rectangle(*crop.bounds())
    cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    cr.set_source_rgba(0, 0, 0, 0.5)
    cr.fill()
    cr.restore()


def _draw_blur(cr, a, doc):
    result = region_surface(doc.surface, a, doc.width, doc.height)
    if result is None:
        return
    surface, x, y = result
    cr.save()
    cr.set_source_surface(surface, x, y)
    cr.paint()
    cr.restore()


def _draw_highlighter(cr, a):
    r, g, b = a.style.stroke[:3]
    cr.rectangle(*a.bounds())
    cr.set_source_rgba(r, g, b, a.style.opacity)
    # Multiply keeps dark text dark under a light wash, as a real marker does.
    cr.set_operator(cairo.OPERATOR_MULTIPLY)
    cr.fill()


def _draw_dim(cr, highlights, doc):
    # Build the dim layer in a group and punch the holes out with CLEAR, so
    # overlapping highlights don't double up the way even-odd filling would.
    cr.save()
    cr.push_group()
    cr.set_source_rgba(0, 0, 0, highlights[0].style.dim)
    cr.paint()
    cr.set_operator(cairo.OPERATOR_CLEAR)
    for h in highlights:
        cr.rectangle(*h.bounds())
        cr.fill()
    cr.pop_group_to_source()
    cr.set_operator(cairo.OPERATOR_OVER)
    cr.paint()
    cr.restore()


def draw_annotation(cr, a):
    cr.save()
    # Pango leaves a current point behind; a following arc() would draw a
    # line from it. Every shape starts from a clean path.
    cr.new_path()
    _DRAWERS[type(a)](cr, a)
    cr.restore()


def _draw_rect(cr, a):
    x, y, w, h = a.bounds()
    cr.rectangle(x, y, w, h)
    if a.style.fill is not None:
        cr.set_source_rgba(*a.style.fill)
        cr.fill_preserve()
    cr.set_source_rgba(*a.style.stroke)
    cr.set_line_width(a.style.width)
    cr.set_line_join(1)  # ROUND
    cr.stroke()


def _draw_ellipse(cr, a):
    x, y, w, h = a.bounds()
    if w <= 0 or h <= 0:
        return
    cr.save()
    cr.translate(x + w / 2, y + h / 2)
    cr.scale(w / 2, h / 2)
    cr.arc(0, 0, 1, 0, 2 * math.pi)
    cr.restore()  # restore before stroking so the pen is not scaled
    if a.style.fill is not None:
        cr.set_source_rgba(*a.style.fill)
        cr.fill_preserve()
    cr.set_source_rgba(*a.style.stroke)
    cr.set_line_width(a.style.width)
    cr.stroke()


def _draw_arrow(cr, a):
    width = a.style.width
    head = a.head_size()
    angle = math.atan2(a.y2 - a.y1, a.x2 - a.x1)
    length = math.hypot(a.x2 - a.x1, a.y2 - a.y1)

    cr.set_source_rgba(*a.style.stroke)
    cr.set_line_width(width)
    cr.set_line_cap(1)  # ROUND

    # Shaft stops short of the tip so the round cap stays inside the head.
    shaft = max(0.0, length - head * 0.8)
    sx = a.x1 + shaft * math.cos(angle)
    sy = a.y1 + shaft * math.sin(angle)
    cr.move_to(a.x1, a.y1)
    cr.line_to(sx, sy)
    cr.stroke()
    if head <= 0:
        return

    # Filled triangular head, base perpendicular to the shaft.
    spread = math.pi / 7
    bx1 = a.x2 - head * math.cos(angle - spread)
    by1 = a.y2 - head * math.sin(angle - spread)
    bx2 = a.x2 - head * math.cos(angle + spread)
    by2 = a.y2 - head * math.sin(angle + spread)
    cr.move_to(a.x2, a.y2)
    cr.line_to(bx1, by1)
    cr.line_to(bx2, by2)
    cr.close_path()
    cr.fill()


def _contrast(rgba):
    """Black or white, whichever reads better on `rgba`."""
    r, g, b = rgba[:3]
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return (0, 0, 0, 0.85) if luminance > 0.6 else (1, 1, 1, 0.9)


def _text_layout(cr, text, size):
    layout = PangoCairo.create_layout(cr)
    layout.set_font_description(
        Pango.FontDescription(f"{FONT_FAMILY} {size:.0f}px"))
    layout.set_text(text, -1)
    return layout


def measure_text(a):
    """Fill in a Text's cached width/height without drawing it."""
    cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
    _, logical = _text_layout(cr, a.text, a.style.font_size).get_pixel_extents()
    a.width, a.height = logical.width, logical.height


def _draw_text(cr, a):
    layout = _text_layout(cr, a.text, a.style.font_size)
    _, logical = layout.get_pixel_extents()
    a.width, a.height = logical.width, logical.height
    if a.style.fill is not None:
        # Filled: a rounded chip behind the glyphs, glyphs in the contrast
        # colour. No halo needed — the chip is the background.
        x, y, w, h = a.bounds()
        _rounded_rect(cr, x, y, w, h, a.padding())
        cr.set_source_rgba(*a.style.fill)
        cr.fill()
        cr.move_to(a.x, a.y)
        cr.set_source_rgba(*_contrast(a.style.fill))
        PangoCairo.show_layout(cr, layout)
        return
    cr.move_to(a.x, a.y)
    PangoCairo.layout_path(cr, layout)
    # A halo in the contrasting colour keeps text legible on any background.
    cr.set_source_rgba(*_contrast(a.style.stroke))
    cr.set_line_width(max(2.0, a.style.font_size / 8))
    cr.set_line_join(1)  # ROUND
    cr.stroke_preserve()
    cr.set_source_rgba(*a.style.stroke)
    cr.fill()


def _rounded_rect(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _draw_marker(cr, a):
    r = a.radius()
    cr.arc(a.cx, a.cy, r, 0, 2 * math.pi)
    cr.set_source_rgba(*a.style.stroke)
    cr.fill_preserve()
    cr.set_source_rgba(*_contrast(a.style.stroke))
    cr.set_line_width(max(1.5, r / 10))
    cr.stroke()
    layout = _text_layout(cr, str(a.number), r * 1.25)
    _, logical = layout.get_pixel_extents()
    cr.move_to(a.cx - logical.width / 2 - logical.x,
               a.cy - logical.height / 2 - logical.y)
    PangoCairo.show_layout(cr, layout)


_DRAWERS = {
    Highlighter: _draw_highlighter,
    Rect: _draw_rect,
    Ellipse: _draw_ellipse,
    Arrow: _draw_arrow,
    Line: _draw_arrow,
    Text: _draw_text,
    Marker: _draw_marker,
}
