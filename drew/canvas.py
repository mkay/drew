# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

"""The drawing area: shows the document fitted to the available space and
routes pointer and key input to the active tool.

Keeps the view transform (scale + offset) in one place so tools map widget
coordinates to image coordinates with `to_image()` and never re-derive it.
"""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk

from drew.history import History
from drew.i18n import _
from drew.model import Style, Text
from drew.render import measure_text, render
from drew.tools import HIT_PX, TOOLS

#: Space between the image and the widget edge, in logical pixels.
MARGIN = 6
#: Selection handle size, in logical pixels.
HANDLE_PX = 9
ZOOM_MIN, ZOOM_MAX = 0.1, 8.0
ZOOM_STEP = 1.25


def _context_menu():
    menu = Gio.Menu()
    order = Gio.Menu()
    order.append(_("Bring to Front"), "win.front")
    order.append(_("Raise"), "win.raise")
    order.append(_("Lower"), "win.lower")
    order.append(_("Send to Back"), "win.back")
    menu.append_section(None, order)
    edit = Gio.Menu()
    edit.append(_("Delete"), "win.delete")
    menu.append_section(None, edit)
    return menu


class Canvas(Gtk.DrawingArea):
    __gsignals__ = {
        # A tool asks to become active (shape tools hand back to Select).
        "tool-request": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "history-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # Zoom factor, or 0 when fitting to the window.
        "zoom-changed": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
    }

    def __init__(self):
        super().__init__(hexpand=True, vexpand=True, focusable=True)
        self.doc = None
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        #: Style applied to newly created shapes.
        self.style = Style()
        self.selection = None
        self.history = History()
        #: None = fit to window; otherwise an explicit scale factor.
        self.zoom = None
        self.tool = TOOLS["select"](self)
        self.set_draw_func(self._draw)

        drag = Gtk.GestureDrag(button=Gdk.BUTTON_PRIMARY)
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)
        self._drag_origin = (0.0, 0.0)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        self.add_controller(motion)

        click = Gtk.GestureClick(button=Gdk.BUTTON_PRIMARY)
        click.connect("pressed", self._on_click)
        self.add_controller(click)

        right = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        right.connect("pressed", self._on_right_click)
        self.add_controller(right)
        self._menu = Gtk.PopoverMenu.new_from_model(_context_menu())
        self._menu.set_parent(self)
        self._menu.set_has_arrow(False)

        scroll = Gtk.EventControllerScroll(
            flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)

        pan = Gtk.GestureDrag(button=Gdk.BUTTON_MIDDLE)
        pan.connect("drag-begin", self._on_pan_begin)
        pan.connect("drag-update", self._on_pan_update)
        self.add_controller(pan)
        self._pan_origin = (0.0, 0.0)
        self._pointer = (0.0, 0.0)

        # Inline text editor: a popover anchored at the text's position.
        self._entry = Gtk.Entry(width_chars=24)
        self._entry.connect("activate", lambda *_: self._editor.popdown())
        self._entry.connect("changed", self._on_entry_changed)
        self._editor = Gtk.Popover(child=self._entry, has_arrow=False,
                                   position=Gtk.PositionType.BOTTOM)
        self._editor.set_parent(self)
        self._editor.connect("closed", self._on_editor_closed)
        self._editing = None

    # --------------------------------------------------------------- public

    def set_document(self, doc):
        self.doc = doc
        self.select(None)
        if doc is not None:
            self.history.reset(doc.annotations)
        self.emit("history-changed")
        self.set_zoom(None)

    def set_tool(self, name):
        self.tool = TOOLS[name](self)
        self.set_cursor_from_name(self.tool.cursor)

    def request_tool(self, name):
        self.emit("tool-request", name)

    def select(self, annotation):
        if annotation is self.selection:
            return
        self.selection = annotation
        self.emit("selection-changed")
        self.queue_draw()

    def changed(self):
        """Something in the document moved; repaint."""
        self.queue_draw()

    def commit(self):
        """A change is complete: record it for undo and repaint."""
        self.history.commit(self.doc.annotations)
        self.emit("history-changed")
        self.queue_draw()

    def undo(self):
        self._restore(self.history.undo())

    def redo(self):
        self._restore(self.history.redo())

    def _restore(self, annotations):
        if annotations is None:
            return
        selected_id = self.selection.id if self.selection else None
        self.doc.annotations = annotations
        self.doc.renumber_markers()
        self.select(next((a for a in annotations if a.id == selected_id), None))
        self.emit("history-changed")
        self.queue_draw()

    def apply_style(self, **changes):
        """Change the current style, and the selected shape's if any."""
        for key, value in changes.items():
            setattr(self.style, key, value)
            if self.selection is not None:
                setattr(self.selection.style, key, value)
        if isinstance(self.selection, Text):
            measure_text(self.selection)
        if self.selection is not None:
            self.commit()
        self.queue_draw()

    def edit_text(self, text):
        self._editing = text
        self._entry.set_text(text.text)
        wx, wy = self.to_widget(text.x, text.y)
        rect = Gdk.Rectangle()
        rect.x, rect.y = int(wx), int(wy)
        rect.width, rect.height = 1, max(1, int(text.height * self.scale))
        self._editor.set_pointing_to(rect)
        self._editor.popup()
        self._entry.grab_focus()

    def _on_entry_changed(self, entry):
        if self._editing is None:
            return
        self._editing.text = entry.get_text()
        measure_text(self._editing)
        self.queue_draw()

    def _on_editor_closed(self, _popover):
        text, self._editing = self._editing, None
        if text is not None and text.is_degenerate() and text in self.doc.annotations:
            self.doc.remove(text)
            if self.selection is text:
                self.select(None)
        self.commit()
        self.grab_focus()

    def delete_selection(self):
        if self.selection is None:
            return
        self.doc.remove(self.selection)
        self.select(None)
        self.commit()

    def restack_selection(self, where):
        if self.selection is None:
            return
        if self.doc.restack(self.selection, where):
            self.commit()

    def nudge_selection(self, dx, dy):
        if self.selection is None:
            return
        self.selection.move(dx, dy)
        self.commit()

    # ----------------------------------------------------------------- zoom

    def set_zoom(self, zoom, anchor=None):
        """Set the scale factor, or None to fit; keep `anchor` (widget
        coordinates) over the same image point."""
        if zoom is not None:
            zoom = max(ZOOM_MIN, min(ZOOM_MAX, zoom))
        image_point = self.to_image(*anchor) if anchor else None
        self.zoom = zoom
        if self.doc is not None and zoom is not None:
            self.set_content_width(int(self.doc.width * zoom) + 2 * MARGIN)
            self.set_content_height(int(self.doc.height * zoom) + 2 * MARGIN)
        else:
            self.set_content_width(0)
            self.set_content_height(0)
        self.emit("zoom-changed", zoom or 0.0)
        if image_point is not None:
            # Content size changes on the next layout; scroll after it.
            self._scroll_to(image_point, anchor)
        self.queue_draw()

    def zoom_by(self, factor, anchor=None):
        self.set_zoom(self.scale * factor, anchor)

    def _scrolled(self):
        parent = self.get_parent()
        while parent is not None and not isinstance(parent, Gtk.ScrolledWindow):
            parent = parent.get_parent()
        return parent

    def _scroll_to(self, image_point, anchor):
        scrolled = self._scrolled()
        if scrolled is None:
            return

        def apply():
            self._fit(self.get_width(), self.get_height())
            wx, wy = self.to_widget(*image_point)
            hadj, vadj = scrolled.get_hadjustment(), scrolled.get_vadjustment()
            hadj.set_value(hadj.get_value() + wx - anchor[0])
            vadj.set_value(vadj.get_value() + wy - anchor[1])
            return False
        GLib.idle_add(apply)

    def _on_scroll(self, controller, _dx, dy):
        if not controller.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK:
            return False
        if self.doc is None:
            return False
        # Anchor on the pointer; the controller does not give a position,
        # so read it from the last motion event.
        self.zoom_by(ZOOM_STEP ** -dy, self._pointer)
        return True

    def _on_pan_begin(self, _gesture, x, y):
        scrolled = self._scrolled()
        if scrolled is None:
            return
        self._pan_origin = (scrolled.get_hadjustment().get_value(),
                            scrolled.get_vadjustment().get_value())

    def _on_pan_update(self, _gesture, dx, dy):
        scrolled = self._scrolled()
        if scrolled is None:
            return
        ox, oy = self._pan_origin
        scrolled.get_hadjustment().set_value(ox - dx)
        scrolled.get_vadjustment().set_value(oy - dy)

    def to_image(self, x, y):
        """Widget coordinates → image coordinates."""
        return (x - self.offset_x) / self.scale, (y - self.offset_y) / self.scale

    def to_widget(self, x, y):
        return x * self.scale + self.offset_x, y * self.scale + self.offset_y

    # ---------------------------------------------------------------- input

    def _mods(self, gesture):
        return gesture.get_current_event_state()

    def _on_drag_begin(self, gesture, x, y):
        if self.doc is None:
            return
        self.grab_focus()
        self._drag_origin = (x, y)
        self.tool.press(*self.to_image(x, y), self._mods(gesture))

    def _on_drag_update(self, gesture, dx, dy):
        if self.doc is None:
            return
        ox, oy = self._drag_origin
        self.tool.drag(*self.to_image(ox + dx, oy + dy), self._mods(gesture))

    def _on_drag_end(self, gesture, dx, dy):
        if self.doc is None:
            return
        ox, oy = self._drag_origin
        if self.tool.release(*self.to_image(ox + dx, oy + dy), self._mods(gesture)):
            self.commit()
        self.queue_draw()

    def _on_click(self, gesture, n_press, x, y):
        if n_press == 2 and isinstance(self.selection, Text):
            self.edit_text(self.selection)

    def _on_right_click(self, _gesture, _n, x, y):
        if self.doc is None:
            return
        hit = self.doc.annotation_at(*self.to_image(x, y), HIT_PX / self.scale)
        if hit is None:
            return
        self.select(hit)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        self._menu.set_pointing_to(rect)
        self._menu.popup()

    def _on_motion(self, _controller, x, y):
        self._pointer = (x, y)
        if self.doc is None:
            return
        self.set_cursor_from_name(self.tool.cursor_at(*self.to_image(x, y)))

    # ------------------------------------------------------------- painting

    def _fit(self, width, height):
        if self.zoom is not None:
            self.scale = self.zoom
        else:
            # Scale down to fit, never up: a small screenshot shown at 1:1
            # stays crisp and its pixels stay honest for blur/pixelate.
            avail_w = max(1, width - 2 * MARGIN)
            avail_h = max(1, height - 2 * MARGIN)
            self.scale = min(1.0, avail_w / self.doc.width,
                             avail_h / self.doc.height)
        # Centred while smaller than the viewport; once larger, the widget
        # itself is larger (content size) and the scrolled window pans it.
        self.offset_x = max(MARGIN, (width - self.doc.width * self.scale) / 2)
        self.offset_y = max(MARGIN, (height - self.doc.height * self.scale) / 2)

    def _draw(self, _area, cr, width, height):
        if self.doc is None:
            return
        self._fit(width, height)
        cr.save()
        cr.translate(self.offset_x, self.offset_y)
        cr.scale(self.scale, self.scale)
        cr.rectangle(0, 0, self.doc.width, self.doc.height)
        cr.clip()
        render(cr, self.doc)
        cr.restore()
        if self.selection is not None:
            self._draw_handles(cr, self.selection)

    def _draw_handles(self, cr, annotation):
        # Drawn in widget space so handles keep their size at any zoom.
        half = HANDLE_PX / 2
        cr.set_line_width(1.0)
        for _name, x, y in annotation.handles():
            wx, wy = self.to_widget(x, y)
            cr.rectangle(round(wx - half) + 0.5, round(wy - half) + 0.5,
                         HANDLE_PX, HANDLE_PX)
            cr.set_source_rgb(1, 1, 1)
            cr.fill_preserve()
            cr.set_source_rgb(0.2, 0.2, 0.2)
            cr.stroke()
