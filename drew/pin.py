# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

"""A pinned image: the picture alone, without any chrome, to drag across
the screen and judge how an element would look in another place.

Where the compositor speaks layer-shell (wlroots-based ones, KDE), the pin
is an overlay surface: it stays above every window and moves by its
margins. Elsewhere (GNOME) it is a borderless window the compositor moves,
and staying on top is up to the compositor's own rules.
"""

import gi
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk

try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell as LayerShell
except (ValueError, ImportError):
    LayerShell = None

from drew import export
from drew.i18n import _

#: Each scroll step changes the opacity by this much…
OPACITY_STEP = 0.1
#: …but never below this, so the pin can't vanish.
MIN_OPACITY = 0.2
#: Each zoom key scales by this, like the editor's; a scroll notch by the
#: finer one; within these bounds.
ZOOM_STEP = 1.25
SCROLL_ZOOM_STEP = 1.05
MIN_ZOOM, MAX_ZOOM = 0.1, 8.0
#: Dragging this close to a corner resizes instead of moving — less on a
#: small pin, so there is still somewhere to grab it to move.
CORNER = 16

CSS = """
window.drew-pin {
    background: none;
    box-shadow: none;
    border-radius: 0;
}
"""

_css_installed = False


def _install_css():
    global _css_installed
    if _css_installed:
        return
    provider = Gtk.CssProvider()
    provider.load_from_string(CSS)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _css_installed = True


def layer_shell_supported():
    return LayerShell is not None and LayerShell.is_supported()


def pin_document(app, doc, near=None):
    """Pin the rendered document, on `near`'s monitor if given."""
    texture = Gdk.Texture.new_for_pixbuf(export.render_to_pixbuf(doc))
    Pin(app, texture, Pin.monitor_of(near)).present()


class _SizedPicture(Gtk.Picture):
    """A picture that asks for exactly the size it is given. Gtk.Picture
    asks for its image's own size; a size request can raise that but never
    lower it, and the pin could grow but not shrink."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._size = (0, 0)

    def set_size(self, width, height):
        self._size = (width, height)
        self.queue_resize()

    def do_measure(self, orientation, _for_size):
        size = self._size[orientation == Gtk.Orientation.VERTICAL]
        return size, size, -1, -1


class Pin(Gtk.Window):
    """One pinned image — or, with an `owner`, a twin showing the part of
    the owner's image that lies on another monitor.

    A layer surface only ever draws on its own monitor, and moving one to
    another monitor remaps it — mid-drag, that leaves it invisible (seen on
    Wayfire). So a pin never changes monitors: where it reaches onto
    another, a twin there shows that part, and when the drag ends with the
    centre over there, the twin takes over and the pin goes.
    """

    def __init__(self, app, texture, monitor=None, owner=None):
        super().__init__(application=app, decorated=False, resizable=False,
                         title=_("Pinned Image"))
        _install_css()
        self.add_css_class("drew-pin")
        # Themes, and users' own gtk.css, paint .background on every
        # window, and user CSS outranks ours: without the class there is
        # nothing behind the image, and a faded pin shows what lies below.
        self.remove_css_class("background")

        self._texture = texture
        self._width, self._height = texture.get_width(), texture.get_height()
        self._picture = _SizedPicture(
            paintable=texture, content_fit=Gtk.ContentFit.FILL)
        self.set_child(self._picture)
        self._owner = owner
        #: Monitor → twin showing the part of this pin that lies there.
        self._twins = {}
        #: 1 is the capture's own size; a twin shares its owner's.
        self._zoom = owner._zoom if owner else 1.0
        #: Where the pointer is over this pin, for zooming around it.
        self._pointer = None

        # The capture is in device pixels; shown at the monitor's scale it
        # lines up pixel for pixel with what it was taken from.
        self._fit_scale(monitor.get_scale() if monitor else 1)
        self.connect("realize", self._on_realize)
        self.connect("close-request", self._on_close_request)

        self._layer = layer_shell_supported()
        if self._layer:
            self._init_layer(monitor)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_pressed)
        self.add_controller(click)

        scroll = Gtk.EventControllerScroll(
            flags=Gtk.EventControllerScrollFlags.BOTH_AXES)
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", lambda _c: setattr(self, "_pointer", None))
        self.add_controller(motion)

    @staticmethod
    def monitor_of(near):
        """The editor's monitor; None from the command line, where only the
        compositor knows which monitor the user is on."""
        surface = near.get_surface() if near is not None else None
        if surface is None:
            return None
        return Gdk.Display.get_default().get_monitor_at_surface(surface)

    def _fit_scale(self, scale):
        self._scale = scale or 1
        self._picture.set_size(
            round(self._width * self._zoom / self._scale),
            round(self._height * self._zoom / self._scale))

    def _on_realize(self, _window):
        # The guess from the monitor may be off (no monitor, or the
        # compositor put the surface elsewhere); the surface knows for sure.
        surface = self.get_surface()
        surface.connect("notify::scale",
                        lambda s, _p: self._fit_scale(s.get_scale()))
        self._fit_scale(surface.get_scale())
        if self._layer and self._monitor is None:
            surface.connect("enter-monitor", self._on_enter_monitor)

    def _on_close_request(self, _window):
        for twin in self._twins.values():
            twin.destroy()
        self._twins.clear()
        return False

    # ------------------------------------------------------------ placement

    def _init_layer(self, monitor):
        LayerShell.init_for_window(self)
        LayerShell.set_namespace(self, "drew-pin")
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        # Keys (Esc, arrows) once clicked, without grabbing them up front.
        # A twin takes none: its owner is the one to talk to.
        LayerShell.set_keyboard_mode(
            self, LayerShell.KeyboardMode.NONE if self._owner
            else LayerShell.KeyboardMode.ON_DEMAND)
        # Ignore panels: margins count from the monitor's edges.
        LayerShell.set_exclusive_zone(self, -1)
        self._x = self._y = 0
        self._monitor = monitor
        if monitor is not None:
            LayerShell.set_monitor(self, monitor)
            self._centre_on(monitor)
            self._anchor()
        # Otherwise the compositor picks the monitor, and with no anchors
        # centres the pin on it; once it says which, anchoring takes over
        # at that same spot.

    def _anchor(self):
        LayerShell.set_anchor(self, LayerShell.Edge.TOP, True)
        LayerShell.set_anchor(self, LayerShell.Edge.LEFT, True)
        self._apply_margins()

    def _on_enter_monitor(self, surface, monitor):
        if self._monitor is not None:
            return
        self._monitor = monitor
        self._fit_scale(monitor.get_scale())
        self._centre_on(monitor)
        self._anchor()

    def _centre_on(self, monitor):
        geometry = monitor.get_geometry()
        self._x = (geometry.width - self._width * self._zoom / self._scale) // 2
        self._y = (geometry.height - self._height * self._zoom / self._scale) // 2

    def _apply_margins(self):
        LayerShell.set_margin(self, LayerShell.Edge.LEFT, round(self._x))
        LayerShell.set_margin(self, LayerShell.Edge.TOP, round(self._y))

    def _bounds(self):
        """The pin's rectangle in desktop coordinates."""
        here = self._monitor.get_geometry()
        return (here.x + self._x, here.y + self._y,
                self._width * self._zoom / self._scale,
                self._height * self._zoom / self._scale)

    def _move_by(self, dx, dy, settle=True):
        self._x += dx
        self._y += dy
        self._apply_margins()
        self._update_twins()
        if settle:
            self._settle()

    def _update_twins(self):
        """A twin on every other monitor the pin reaches onto; none on the
        rest."""
        if self._monitor is None:
            return
        x, y, width, height = self._bounds()
        reached = []
        monitors = Gdk.Display.get_default().get_monitors()
        for i in range(monitors.get_n_items()):
            monitor = monitors.get_item(i)
            there = monitor.get_geometry()
            if monitor == self._monitor or not (
                    x < there.x + there.width and there.x < x + width
                    and y < there.y + there.height and there.y < y + height):
                continue
            reached.append(monitor)
            twin = self._twins.get(monitor)
            if twin is None:
                twin = Pin(self.get_application(), self._texture, monitor,
                           owner=self)
                twin._picture.set_opacity(self._picture.get_opacity())
                self._twins[monitor] = twin
            twin._x, twin._y = x - there.x, y - there.y
            twin._apply_margins()
            twin.present()
        for monitor in [m for m in self._twins if m not in reached]:
            self._twins.pop(monitor).destroy()

    def _settle(self):
        """Once the centre rests on another monitor, the twin there takes
        over as the pin."""
        if self._monitor is None:
            return
        x, y, width, height = self._bounds()
        cx, cy = x + width / 2, y + height / 2
        if _contains(self._monitor.get_geometry(), cx, cy):
            return
        heir = next((twin for monitor, twin in self._twins.items()
                     if _contains(monitor.get_geometry(), cx, cy)), None)
        if heir is None:
            return  # in a gap between monitors; stay put
        del self._twins[heir._monitor]
        heir._twins, self._twins = self._twins, {}
        for twin in heir._twins.values():
            twin._owner = heir
        heir._owner = None
        LayerShell.set_keyboard_mode(heir, LayerShell.KeyboardMode.ON_DEMAND)
        # The part still on this monitor gets a twin of its own.
        heir._update_twins()
        self.close()

    def _zoom_by(self, factor, around=None):
        """Scale the pin; `around` (desktop coordinates) stays where it is,
        the centre if not given."""
        zoom = min(MAX_ZOOM, max(MIN_ZOOM, self._zoom * factor))
        self._set_zoom(zoom, around)

    def _set_zoom(self, zoom, around=None, settle=True):
        placed = self._layer and self._monitor is not None
        if placed:
            x, y, width, height = self._bounds()
            ax, ay = around or (x + width / 2, y + height / 2)
            factor = zoom / self._zoom
            here = self._monitor.get_geometry()
            self._x = ax - (ax - x) * factor - here.x
            self._y = ay - (ay - y) * factor - here.y
        for pin in (self, *self._twins.values()):
            pin._zoom = zoom
            pin._fit_scale(pin._scale)
        if placed:
            self._move_by(0, 0, settle=settle)

    def _desktop_point(self, x, y):
        """A point on this pin's surface, in desktop coordinates."""
        here = self._monitor.get_geometry()
        return here.x + self._x + x, here.y + self._y + y

    def _set_opacity(self, opacity):
        for pin in (self, *self._twins.values()):
            pin._picture.set_opacity(opacity)

    # --------------------------------------------------------------- input
    # Input on a twin goes to its owner: the pin is the pair as a whole.

    def _corner_at(self, x, y):
        """The corner ("nw", "se", …) under a point on this surface, if
        it is near enough to resize from."""
        if not self._layer or self._monitor is None:
            return None
        px, py = self._desktop_point(x, y)
        left, top, width, height = self._bounds()
        zone = min(CORNER, width / 4, height / 4)
        vertical = "n" if py < top + zone else \
            "s" if py > top + height - zone else ""
        horizontal = "w" if px < left + zone else \
            "e" if px > left + width - zone else ""
        return vertical + horizontal if vertical and horizontal else None

    def _on_motion(self, _controller, x, y):
        self._pointer = (x, y)
        corner = self._corner_at(x, y)
        self.set_cursor_from_name(f"{corner}-resize" if corner else None)

    def _on_drag_begin(self, _gesture, x, y):
        self._handed_over = False
        #: While resizing: the corner that stays put, in desktop coordinates.
        self._resize_anchor = None
        corner = self._corner_at(x, y)
        if corner:
            left, top, width, height = (self._owner or self)._bounds()
            self._resize_anchor = (left + width if "w" in corner else left,
                                   top + height if "n" in corner else top)

    def _on_drag_update(self, gesture, dx, dy):
        if self._resize_anchor:
            # The aspect is kept: the pin follows whichever way the pointer
            # has moved further, scaled around the opposite corner.
            _ok, x, y = gesture.get_start_point()
            px, py = self._desktop_point(x + dx, y + dy)
            ax, ay = self._resize_anchor
            zoom = max(abs(px - ax) * self._scale / self._width,
                       abs(py - ay) * self._scale / self._height)
            (self._owner or self)._set_zoom(
                min(MAX_ZOOM, max(MIN_ZOOM, zoom)), self._resize_anchor,
                settle=False)
            return
        if self._layer:
            # The offset is measured from where the pointer went down, in
            # surface coordinates. Moving the surface by it brings the
            # pointer back over that spot, so each update carries only what
            # is new since the last one. Twins move along by the same.
            (self._owner or self)._move_by(dx, dy, settle=False)
            return
        # A plain window can only be moved by the compositor. Hand over
        # once the pointer has really moved, so a double-click still
        # reaches us.
        threshold = Gtk.Settings.get_default().get_property(
            "gtk-dnd-drag-threshold")
        if self._handed_over or max(abs(dx), abs(dy)) < threshold:
            return
        self._handed_over = True
        _ok, x, y = gesture.get_start_point()
        self.get_surface().begin_move(
            gesture.get_device(), gesture.get_current_button(), x, y,
            gesture.get_current_event_time())
        gesture.reset()

    def _on_drag_end(self, _gesture, _dx, _dy):
        if self._layer:
            (self._owner or self)._settle()

    def _on_pressed(self, _gesture, n_press, _x, _y):
        if n_press == 2:
            (self._owner or self).close()

    def _on_scroll(self, controller, dx, dy):
        owner = self._owner or self
        state = controller.get_current_event_state()
        # Some stacks turn a Shift+wheel into horizontal scrolling.
        delta = dy or dx
        if state & Gdk.ModifierType.CONTROL_MASK:
            around = None
            if self._layer and self._pointer and self._monitor is not None:
                around = self._desktop_point(*self._pointer)
            owner._zoom_by(SCROLL_ZOOM_STEP ** -delta, around)
            return True
        if state & Gdk.ModifierType.SHIFT_MASK:
            opacity = owner._picture.get_opacity() - delta * OPACITY_STEP
            owner._set_opacity(min(1.0, max(MIN_OPACITY, opacity)))
            return True
        return False

    def _on_key(self, _controller, keyval, _keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if state & Gdk.ModifierType.CONTROL_MASK:
            if keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
                self._zoom_by(ZOOM_STEP)
            elif keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
                self._zoom_by(1 / ZOOM_STEP)
            elif keyval in (Gdk.KEY_0, Gdk.KEY_KP_0):
                self._set_zoom(1.0)
            else:
                return False
            return True
        if not self._layer:
            return False
        step = 10 if state & Gdk.ModifierType.SHIFT_MASK else 1
        nudge = {
            Gdk.KEY_Left: (-step, 0), Gdk.KEY_Right: (step, 0),
            Gdk.KEY_Up: (0, -step), Gdk.KEY_Down: (0, step),
        }.get(keyval)
        if nudge:
            self._move_by(*nudge)
            return True
        return False


def _contains(rect, x, y):
    return (rect.x <= x < rect.x + rect.width
            and rect.y <= y < rect.y + rect.height)
