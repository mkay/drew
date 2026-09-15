# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

"""The image being annotated.

A Document owns the base image as a Cairo surface — the form everything
downstream wants: the canvas paints it, the exporter renders onto a copy of
it, and the blur/pixelate filters (later) read pixels out of it. GdkPixbuf
is used only for decoding, because it knows every format GTK does and
applies EXIF orientation for us.

Annotations are kept in draw order: last in the list is drawn on top and
is the first candidate for a click.
"""

from pathlib import Path

import cairo
import gi
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib

from drew.model import Marker, Region


class Document:
    def __init__(self, surface, source_path=None):
        self.surface = surface
        self.width = surface.get_width()
        self.height = surface.get_height()
        #: Where the image came from, or None for stdin. Used for the window
        #: title only — saving never overwrites the input.
        self.source_path = source_path
        self.annotations = []

    def add(self, annotation):
        self.annotations.append(annotation)

    def remove(self, annotation):
        self.annotations.remove(annotation)
        if isinstance(annotation, Marker):
            self.renumber_markers()

    def restack(self, annotation, where):
        """Move `annotation` in draw order: "raise", "lower", "front" or
        "back". Regions are excluded from the ordering — they render in
        their own pass below every shape — so an arrow on top of a rect
        stays there whether a blur sits between them in the list or not."""
        items = self.annotations
        i = items.index(annotation)
        if where == "front":
            j = len(items) - 1
        elif where == "back":
            j = 0
        else:
            step = 1 if where == "raise" else -1
            j = i + step
            # Skip over regions: swapping with one changes nothing visible.
            while 0 <= j < len(items) and isinstance(items[j], Region):
                j += step
            if not 0 <= j < len(items):
                return False
        if j == i:
            return False
        items.insert(j, items.pop(i))
        return True

    def next_marker_number(self):
        return sum(isinstance(a, Marker) for a in self.annotations) + 1

    def renumber_markers(self):
        """Keep markers 1..n in draw order after one was removed."""
        n = 1
        for a in self.annotations:
            if isinstance(a, Marker):
                a.number = n
                n += 1

    def annotation_at(self, x, y, tolerance):
        """Topmost annotation under (x, y), or None."""
        for annotation in reversed(self.annotations):
            if annotation.hit(x, y, tolerance):
                return annotation
        return None

    @classmethod
    def from_path(cls, path):
        path = Path(path)
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
        return cls(_pixbuf_to_surface(pixbuf), source_path=path)

    @classmethod
    def from_bytes(cls, data):
        stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data))
        pixbuf = GdkPixbuf.Pixbuf.new_from_stream(stream, None)
        return cls(_pixbuf_to_surface(pixbuf))

    @property
    def display_name(self):
        """File name, or None for piped input."""
        return self.source_path.name if self.source_path else None


def _pixbuf_to_surface(pixbuf):
    pixbuf = pixbuf.apply_embedded_orientation() or pixbuf
    surface = cairo.ImageSurface(
        cairo.FORMAT_ARGB32, pixbuf.get_width(), pixbuf.get_height()
    )
    cr = cairo.Context(surface)
    Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
    cr.paint()
    surface.flush()
    return surface
