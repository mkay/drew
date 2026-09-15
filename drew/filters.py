# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

"""Blur and pixelate a region of a Cairo surface, via Pillow.

Results are cached per annotation (in a weak dict, so the model objects
stay plain data that undo can deep-copy), keyed by everything that affects
them, so dragging a region only recomputes when it actually changes.
"""

import weakref

import cairo
from PIL import Image, ImageFilter

from drew.model import Pixelate

_cache = weakref.WeakKeyDictionary()


def region_surface(source, blur, image_w, image_h):
    """Filtered copy of `source` under `blur`, plus where to paint it.

    Returns (surface, x, y) or None when the region is empty.
    """
    x, y, w, h = (int(round(v)) for v in blur.bounds())
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(image_w, x + w), min(image_h, y + h)
    if x1 <= x0 or y1 <= y0:
        return None
    key = (type(blur), blur.strength(), x0, y0, x1, y1)
    cached = _cache.get(blur)
    if cached is not None and cached[0] == key:
        return cached[1], x0, y0

    image = _crop(source, x0, y0, x1 - x0, y1 - y0)
    if isinstance(blur, Pixelate):
        image = _pixelate(image, blur.strength())
    else:
        image = image.filter(ImageFilter.GaussianBlur(blur.strength()))
    surface = _to_surface(image)
    _cache[blur] = (key, surface)
    return surface, x0, y0


def _crop(source, x, y, w, h):
    source.flush()
    stride = source.get_stride()
    data = source.get_data()
    # Cairo ARGB32 is premultiplied BGRA in memory on little-endian hosts;
    # Pillow's "BGRa" raw mode unpremultiplies on the way in.
    full = Image.frombuffer("RGBA", (source.get_width(), source.get_height()),
                            data, "raw", "BGRa", stride, 1)
    return full.crop((x, y, x + w, y + h))


def _pixelate(image, block):
    block = max(2, block)
    w, h = image.size
    small = image.resize((max(1, w // block), max(1, h // block)),
                         Image.Resampling.BOX)
    return small.resize((w, h), Image.Resampling.NEAREST)


def _to_surface(image):
    w, h = image.size
    stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_ARGB32, w)
    raw = image.tobytes("raw", "BGRa", stride)
    return cairo.ImageSurface.create_for_data(bytearray(raw),
                                              cairo.FORMAT_ARGB32, w, h, stride)
