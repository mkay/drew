# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

"""Colour / width / fill / text size, in one popover behind one button.

One button rather than a row of controls, to keep the header bar to the
tools and the image. The button itself shows the current colour.
"""

import colorsys
import math

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, GObject, Gtk

from drew.i18n import _

#: GNOME palette, strongest shades: (r, g, b, a) in 0..1.
PALETTE = [
    (0.878, 0.106, 0.141, 1.0),  # red
    (1.000, 0.471, 0.000, 1.0),  # orange
    (0.965, 0.827, 0.176, 1.0),  # yellow
    (0.200, 0.820, 0.478, 1.0),  # green
    (0.208, 0.518, 0.894, 1.0),  # blue
    (0.569, 0.255, 0.675, 1.0),  # purple
    (0.141, 0.122, 0.192, 1.0),  # dark
    (1.000, 1.000, 1.000, 1.0),  # white
]


class Swatch(Gtk.DrawingArea):
    """A coloured disc; with rgba=None, a hue wheel meaning "any colour"."""

    def __init__(self, rgba, size=18):
        super().__init__(content_width=size, content_height=size,
                         valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        self.rgba = rgba
        self.set_draw_func(self._draw)

    def set_rgba(self, rgba):
        self.rgba = rgba
        self.queue_draw()

    def _draw(self, _area, cr, w, h):
        r = min(w, h) / 2 - 1
        cx, cy = w / 2, h / 2
        if self.rgba is None:
            steps = 12
            for i in range(steps):
                a0 = i * 2 * math.pi / steps
                cr.move_to(cx, cy)
                cr.arc(cx, cy, r, a0, a0 + 2 * math.pi / steps + 0.02)
                cr.set_source_rgb(*colorsys.hsv_to_rgb(i / steps, 0.85, 0.95))
                cr.fill()
        else:
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            cr.set_source_rgba(*self.rgba)
            cr.fill()
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.set_source_rgba(0, 0, 0, 0.3)
        cr.set_line_width(1)
        cr.stroke()


class StyleButton(Gtk.MenuButton):
    __gsignals__ = {
        # (property name, new value) — the window forwards it to the canvas.
        "style-changed": (GObject.SignalFlags.RUN_FIRST, None, (str, object)),
    }

    def __init__(self, style):
        super().__init__(tooltip_text=_("Colour and Size"),
                         valign=Gtk.Align.CENTER)
        self._swatch = Swatch(style.stroke)
        self.set_child(self._swatch)
        #: True while show_style() sets widgets; handlers stay quiet.
        self._updating = False

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=6, margin_bottom=6,
                      margin_start=6, margin_end=6)

        palette = Gtk.Box(spacing=4)
        for rgba in PALETTE:
            button = Gtk.Button(child=Swatch(rgba, 22))
            button.add_css_class("flat")
            button.connect("clicked", self._on_colour, rgba)
            palette.append(button)
        custom = Gtk.Button(child=Swatch(None, 22),
                            tooltip_text=_("Custom colour…"))
        custom.add_css_class("flat")
        custom.connect("clicked", self._on_custom)
        palette.append(custom)
        box.append(palette)

        self._width = self._scale(box, _("Line width"), 1, 16, style.width)
        self._width.connect("value-changed",
                            lambda s: self._emit("width", s.get_value()))
        self._size = self._scale(box, _("Text size"), 10, 96, style.font_size)
        self._size.connect("value-changed",
                           lambda s: self._emit("font_size", s.get_value()))

        self._fill = Gtk.CheckButton(label=_("Fill shapes"),
                                     active=style.fill is not None)
        self._fill.connect("toggled", self._on_fill)
        box.append(self._fill)

        self.set_popover(Gtk.Popover(child=box))

    @staticmethod
    def _scale(box, title, lo, hi, value):
        box.append(Gtk.Label(label=title, xalign=0))
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 1)
        scale.set_value(value)
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        scale.set_digits(0)
        box.append(scale)
        return scale

    def _emit(self, name, value):
        if not self._updating:
            self.emit("style-changed", name, value)

    def _on_colour(self, _button, rgba):
        self._swatch.set_rgba(rgba)
        self._emit("stroke", rgba)
        if self._fill.get_active():
            self._emit("fill", rgba)

    def _on_custom(self, _button):
        dialog = Gtk.ColorDialog(with_alpha=True)
        initial = Gdk.RGBA()
        initial.red, initial.green, initial.blue, initial.alpha = self._swatch.rgba
        self.get_popover().popdown()
        dialog.choose_rgba(self.get_root(), initial, None, self._on_custom_done)

    def _on_custom_done(self, dialog, result):
        try:
            rgba = dialog.choose_rgba_finish(result)
        except GLib.Error:
            return  # cancelled
        self._on_colour(None, (rgba.red, rgba.green, rgba.blue, rgba.alpha))

    def _on_fill(self, check):
        self._emit("fill", self._swatch.rgba if check.get_active() else None)

    def show_style(self, style):
        """Reflect a selected shape's style without emitting changes."""
        self._updating = True
        try:
            self._swatch.set_rgba(style.stroke)
            self._width.set_value(style.width)
            self._size.set_value(style.font_size)
            self._fill.set_active(style.fill is not None)
        finally:
            self._updating = False
