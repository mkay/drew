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
    """One popover for every adjustable property.

    Rows are built once and shown or hidden by `show_for()`, so the popover
    only ever offers what the selected shape — or the tool about to draw
    one — actually uses.
    """
    __gsignals__ = {
        # (property name, new value) — the window forwards it to the canvas.
        "style-changed": (GObject.SignalFlags.RUN_FIRST, None, (str, object)),
    }

    #: Slider rows: property → (label, lo, hi, step, digits).
    SLIDERS = {
        "width": (_("Line width"), 1, 16, 1, 0),
        "font_size": (_("Text size"), 10, 96, 1, 0),
        "marker_size": (_("Marker size"), 8, 48, 1, 0),
        "opacity": (_("Opacity"), 0.1, 0.9, 0.05, 2),
        "dim": (_("Dim"), 0.1, 0.95, 0.05, 2),
        "blur": (_("Blur radius"), 1, 40, 1, 0),
        "block": (_("Block size"), 2, 64, 1, 0),
    }

    def __init__(self, style):
        super().__init__(tooltip_text=_("Colour and Size"),
                         valign=Gtk.Align.CENTER)
        self._swatch = Swatch(style.stroke)
        self.set_child(self._swatch)
        #: True while show_for() sets widgets; handlers stay quiet.
        self._updating = False
        #: Row widgets by property name, for show/hide.
        self._rows = {}

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
        self._rows["stroke"] = palette

        self._scales = {}
        for prop, (label, lo, hi, step, digits) in self.SLIDERS.items():
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            row.append(Gtk.Label(label=label, xalign=0))
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,
                                             lo, hi, step)
            scale.set_value(getattr(style, prop))
            scale.set_draw_value(True)
            scale.set_value_pos(Gtk.PositionType.RIGHT)
            scale.set_digits(digits)
            scale.connect("value-changed",
                          lambda s, prop=prop: self._emit(prop, s.get_value()))
            row.append(scale)
            box.append(row)
            self._rows[prop] = row
            self._scales[prop] = scale

        self._fill = Gtk.CheckButton(label=_("Fill"),
                                     active=style.fill is not None)
        self._fill.connect("toggled", self._on_fill)
        box.append(self._fill)
        self._rows["fill"] = self._fill

        self.set_popover(Gtk.Popover(child=box))
        self.show_for(("stroke", "width", "fill"), style)

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

    def show_for(self, props, style):
        """Show only the rows in `props`, with values from `style`, without
        emitting changes."""
        self._updating = True
        try:
            for name, row in self._rows.items():
                row.set_visible(name in props)
            self._swatch.set_rgba(style.stroke)
            for prop, scale in self._scales.items():
                scale.set_value(getattr(style, prop))
            self._fill.set_active(style.fill is not None)
        finally:
            self._updating = False
