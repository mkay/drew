# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

"""Turn a Document into image bytes or a file."""

import sys
from datetime import datetime
from pathlib import Path

import cairo
import gi
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, GObject

from drew.render import render

#: Pixbuf writer name and file extension per supported output format.
FORMATS = {
    "png": ("png", ".png"),
    "jpeg": ("jpeg", ".jpg"),
}


def render_to_pixbuf(doc, fmt="png"):
    # JPEG has no alpha, and the encoder rejects RGBA input outright, so
    # render onto an opaque surface (white behind any transparency) and let
    # pixbuf_get_from_surface produce an RGB pixbuf from it.
    opaque = fmt == "jpeg"
    surface = cairo.ImageSurface(
        cairo.FORMAT_RGB24 if opaque else cairo.FORMAT_ARGB32,
        doc.width, doc.height,
    )
    cr = cairo.Context(surface)
    if opaque:
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
    render(cr, doc)
    surface.flush()
    return Gdk.pixbuf_get_from_surface(surface, 0, 0, doc.width, doc.height)


def copy_to_clipboard(doc, clipboard):
    """Put the rendered image on the clipboard.

    The value must be typed as GdkTexture, not the concrete GdkMemoryTexture
    it actually is: GTK finds its PNG/TIFF/JPEG serializers by exact GType,
    and with the subclass it finds none and offers nothing to the compositor.
    """
    texture = Gdk.Texture.new_for_pixbuf(render_to_pixbuf(doc))
    value = GObject.Value(Gdk.Texture, texture)
    clipboard.set_content(Gdk.ContentProvider.new_for_value(value))


def format_for_path(path):
    """Pick the output format from a filename; PNG unless told otherwise."""
    suffix = Path(path).suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return "jpeg"
    return "png"


def save_to_file(doc, path, fmt=None):
    fmt = fmt or format_for_path(path)
    pixbuf = render_to_pixbuf(doc, fmt)
    pixbuf.savev(str(path), FORMATS[fmt][0], [], [])


def save_to_stdout(doc, fmt="png"):
    pixbuf = render_to_pixbuf(doc, fmt)
    ok, data = pixbuf.save_to_bufferv(FORMATS[fmt][0], [], [])
    if not ok:
        raise RuntimeError("encoding failed")
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def pictures_dir():
    pictures = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
    return Path(pictures) if pictures else Path.home()


def default_save_path(settings, fmt="png"):
    """<folder>/<prefix>-YYYYMMDD-HHMMSS.png — never collides with the input."""
    directory = Path(settings.get("save_dir") or pictures_dir())
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return directory / f"{settings.get('filename_prefix')}-{stamp}{FORMATS[fmt][1]}"
