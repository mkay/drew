# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from drew import APP_NAME
from drew.i18n import _
from drew import export
from drew.canvas import MARGIN, Canvas
from drew.document import Document
from drew.preferences import PreferencesDialog
from drew.stylebox import StyleButton

#: Tool name, icon, tooltip — in toolbar order.
TOOLS = [
    ("select", "drew-tool-select-symbolic", _("Select (V)")),
    ("arrow", "drew-tool-arrow-symbolic", _("Arrow (A)")),
    ("line", "drew-tool-line-symbolic", _("Line (L)")),
    ("rect", "drew-tool-rect-symbolic", _("Rectangle (R)")),
    ("ellipse", "drew-tool-ellipse-symbolic", _("Ellipse (E)")),
    ("text", "drew-tool-text-symbolic", _("Text (T)")),
    ("marker", "drew-tool-marker-symbolic", _("Numbered Marker (M)")),
    ("highlighter", "drew-tool-highlighter-symbolic", _("Highlighter (H)")),
    ("spotlight", "drew-tool-spotlight-symbolic", _("Spotlight (S)")),
    ("blur", "drew-tool-blur-symbolic", _("Blur (B)")),
    ("pixelate", "drew-tool-pixelate-symbolic", _("Pixelate (P)")),
]

#: Height of the header bar, for sizing the window to the image.
HEADER_HEIGHT = 47
#: Below this width the tools leave the header bar for a bar of their own.
NARROW_WIDTH = 760
#: The window never opens smaller than this, however tiny the image.
MIN_WIDTH, MIN_HEIGHT = 640, 400
#: …nor larger than this share of the monitor.
MAX_SHARE = 0.9


class Window(Adw.ApplicationWindow):
    def __init__(self, app, doc=None, output=None):
        super().__init__(application=app,
                         default_width=MIN_WIDTH, default_height=MIN_HEIGHT)
        self.doc = None
        self.settings = app.settings
        #: Path from `-o`, "-" for stdout, or None → ask / timestamped file.
        self.output = output

        # No title widget: the header is for tools and actions, and on a
        # small screenshot the title would only squeeze them.
        header = Adw.HeaderBar(show_title=False)

        self._tools = Adw.ToggleGroup(valign=Gtk.Align.CENTER)
        self._tools.add_css_class("flat")
        for name, icon, tooltip in TOOLS:
            self._tools.add(Adw.Toggle(name=name, icon_name=icon,
                                       tooltip=tooltip))
        self._tools.connect("notify::active-name", self._on_toggle_changed)
        # Tools and style travel together between header and bottom bar.
        self._toolbox = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        self._toolbox.append(self._tools)
        header.pack_start(self._toolbox)


        save_button = Gtk.Button(icon_name="drew-save-symbolic",
                                 tooltip_text=_("Save (Ctrl+S)"))
        save_button.add_css_class("suggested-action")
        save_button.set_action_name("win.save")
        header.pack_end(save_button)

        copy_button = Gtk.Button(icon_name="drew-copy-symbolic",
                                 tooltip_text=_("Copy to Clipboard (Ctrl+C)"))
        copy_button.set_action_name("win.copy")
        header.pack_end(copy_button)

        menu = Gio.Menu()
        file = Gio.Menu()
        file.append(_("Open…"), "win.open")
        file.append(_("Save As…"), "win.save-as")
        menu.append_section(None, file)
        history = Gio.Menu()
        history.append(_("Undo"), "win.undo")
        history.append(_("Redo"), "win.redo")
        menu.append_section(None, history)
        order = Gio.Menu()
        order.append(_("Bring to Front"), "win.front")
        order.append(_("Raise"), "win.raise")
        order.append(_("Lower"), "win.lower")
        order.append(_("Send to Back"), "win.back")
        menu.append_section(None, order)
        zoom = Gio.Menu()
        zoom.append(_("Zoom In"), "win.zoom-in")
        zoom.append(_("Zoom Out"), "win.zoom-out")
        zoom.append(_("Actual Size"), "win.zoom-100")
        zoom.append(_("Fit to Window"), "win.zoom-fit")
        menu.append_section(None, zoom)
        settings = Gio.Menu()
        settings.append(_("Preferences"), "win.preferences")
        settings.append(_("About Drew"), "app.about")
        menu.append_section(None, settings)
        menu_button = Gtk.MenuButton(icon_name="drew-menu-symbolic",
                                     menu_model=menu, primary=True)
        header.pack_end(menu_button)

        self.canvas = Canvas()
        self.canvas.connect("tool-request", lambda _c, name: self._set_tool(name))
        self.canvas.connect("selection-changed", self._on_selection_changed)
        self.canvas.connect("history-changed", self._on_history_changed)
        self.canvas.connect("zoom-changed", self._on_zoom_changed)

        self.canvas.style = self.settings.style()
        self._style = StyleButton(self.canvas.style)
        self._style.connect("style-changed", self._on_style_changed)
        self._toolbox.append(self._style)
        self._empty = Adw.StatusPage(
            icon_name="drew-image-symbolic",
            title=_("No Image"),
            description=_("Open an image, or pipe one in: grim - | drew -"),
        )
        self._stack = Gtk.Stack()
        self._stack.add_named(self._empty, "empty")
        scrolled = Gtk.ScrolledWindow(child=self.canvas,
                                      hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                      vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        self._stack.add_named(scrolled, "canvas")

        self._toasts = Adw.ToastOverlay(child=self._stack)
        view = Adw.ToolbarView(content=self._toasts)
        view.add_top_bar(header)
        # Narrow windows: the tools get a bar of their own under the image.
        self._bottom = Gtk.CenterBox(margin_top=3, margin_bottom=3,
                                     visible=False)
        self._bottom.add_css_class("toolbar")
        view.add_bottom_bar(self._bottom)
        self.set_content(view)

        self._header = header
        breakpoint = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse(f"max-width: {NARROW_WIDTH}px"))
        breakpoint.connect("apply", lambda *_: self._place_tools(narrow=True))
        breakpoint.connect("unapply", lambda *_: self._place_tools(narrow=False))
        self.add_breakpoint(breakpoint)

        self._add_actions()
        self.set_document(doc)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

    # ----------------------------------------------------------------- state

    def set_document(self, doc):
        self.doc = doc
        self.canvas.set_document(doc)
        has_doc = doc is not None
        self._stack.set_visible_child_name("canvas" if has_doc else "empty")
        self.lookup_action("save").set_enabled(has_doc)
        self.lookup_action("save-as").set_enabled(has_doc)
        self.lookup_action("copy").set_enabled(has_doc)
        for name in ("zoom-in", "zoom-out", "zoom-100", "zoom-fit"):
            self.lookup_action(name).set_enabled(has_doc)
        self._tools.set_sensitive(has_doc)
        self._style.set_sensitive(has_doc)
        if has_doc:
            self.set_title(doc.display_name or APP_NAME)
            self._size_to(doc)
        else:
            self.set_title(APP_NAME)

    def _place_tools(self, narrow):
        parent = self._toolbox.get_parent()
        if narrow and parent is not self._bottom:
            self._header.remove(self._toolbox)
            self._bottom.set_center_widget(self._toolbox)
            self._bottom.set_visible(True)
        elif not narrow and parent is not self._header:
            self._bottom.set_center_widget(None)
            self._bottom.set_visible(False)
            self._header.pack_start(self._toolbox)

    def _size_to(self, doc):
        """Open at the image's own size, so it is shown 1:1 without letterbox.

        Capped to a share of the monitor, and floored so a tiny crop still
        gets a usable window.
        """
        cap_w, cap_h = 10_000, 10_000
        monitors = Gdk.Display.get_default().get_monitors()
        if monitors.get_n_items():
            geometry = monitors.get_item(0).get_geometry()
            cap_w, cap_h = geometry.width * MAX_SHARE, geometry.height * MAX_SHARE
        width = doc.width + 2 * MARGIN
        height = doc.height + 2 * MARGIN + HEADER_HEIGHT
        self.set_default_size(int(max(MIN_WIDTH, min(cap_w, width))),
                              int(max(MIN_HEIGHT, min(cap_h, height))))

    def _toast(self, text):
        self._toasts.add_toast(Adw.Toast(title=text))

    # --------------------------------------------------------------- actions

    def _add_actions(self):
        for name, handler in (
            ("open", self._on_open),
            ("save", self._on_save),
            ("save-as", self._on_save_as),
            ("preferences", self._on_preferences),
            ("copy", self._on_copy),
            ("undo", lambda *_: self.canvas.undo()),
            ("redo", lambda *_: self.canvas.redo()),
            ("zoom-in", lambda *_: self.canvas.zoom_by(1.25)),
            ("zoom-out", lambda *_: self.canvas.zoom_by(1 / 1.25)),
            ("zoom-100", lambda *_: self.canvas.set_zoom(1.0)),
            ("zoom-fit", lambda *_: self.canvas.set_zoom(None)),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

        tool = Gio.SimpleAction.new_stateful(
            "tool", GLib.VariantType("s"), GLib.Variant("s", "select"))
        tool.connect("change-state", self._on_tool_action)
        self.add_action(tool)

        delete = Gio.SimpleAction.new("delete", None)
        delete.connect("activate", lambda *_: self.canvas.delete_selection())
        delete.set_enabled(False)
        self.add_action(delete)

        for name in ("raise", "lower", "front", "back"):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate",
                           lambda _a, _p, where=name: self.canvas.restack_selection(where))
            action.set_enabled(False)
            self.add_action(action)

    # Three things track the active tool — the action (for accelerators),
    # the toggle group (for the toolbar), the canvas (for behaviour). The
    # action is the source of truth; the others follow it.
    def _set_tool(self, name):
        self.lookup_action("tool").change_state(GLib.Variant("s", name))

    def _on_tool_action(self, action, value):
        if action.get_state() == value:
            return
        action.set_state(value)
        name = value.get_string()
        self._tools.set_active_name(name)
        self.canvas.set_tool(name)

    def _on_toggle_changed(self, group, _pspec):
        self._set_tool(group.get_active_name())

    def _on_style_changed(self, _button, key, value):
        self.canvas.apply_style(**{key: value})
        # What was picked last is the default next time.
        self.settings.save_style(self.canvas.style)

    def _on_selection_changed(self, canvas):
        selected = canvas.selection is not None
        for name in ("delete", "raise", "lower", "front", "back"):
            self.lookup_action(name).set_enabled(selected)
        if canvas.selection is not None:
            self._style.show_style(canvas.selection.style)

    def _on_history_changed(self, canvas):
        self.lookup_action("undo").set_enabled(canvas.history.can_undo)
        self.lookup_action("redo").set_enabled(canvas.history.can_redo)

    def _on_zoom_changed(self, _canvas, zoom):
        if self.doc is None:
            return
        name = self.doc.display_name or APP_NAME
        self.set_title(f"{name} · {zoom:.0%}" if zoom else name)

    def _on_copy(self, *_args):
        export.copy_to_clipboard(self.doc, self.get_clipboard())
        self._toast(_("Copied to clipboard"))

    def _on_preferences(self, *_args):
        PreferencesDialog(self.settings).present(self)

    def _on_key(self, _controller, keyval, _keycode, state):
        if self.doc is None:
            return False
        step = 10 if state & Gdk.ModifierType.SHIFT_MASK else 1
        nudge = {
            Gdk.KEY_Left: (-step, 0), Gdk.KEY_Right: (step, 0),
            Gdk.KEY_Up: (0, -step), Gdk.KEY_Down: (0, step),
        }.get(keyval)
        if nudge and self.canvas.selection is not None:
            self.canvas.nudge_selection(*nudge)
            return True
        if keyval == Gdk.KEY_Escape and self.canvas.selection is not None:
            self.canvas.select(None)
            return True
        return False

    def _on_open(self, *_args):
        dialog = Gtk.FileDialog(title=_("Open Image"))
        images = Gtk.FileFilter(name=_("Images"))
        images.add_mime_type("image/*")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(images)
        dialog.set_filters(filters)
        dialog.open(self, None, self._on_open_done)

    def _on_open_done(self, dialog, result):
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return  # cancelled
        try:
            self.set_document(Document.from_path(file.get_path()))
        except GLib.Error as e:
            self._toast(_("Could not open image: {error}").format(error=e.message))

    def _on_save(self, *_args):
        if self.output == "-":
            # stdout is a one-shot sink: write and leave, like a pipe expects.
            export.save_to_stdout(self.doc)
            self.close()
            return
        path = self.output or export.default_save_path(self.settings)
        self._save_to(path)

    def _on_save_as(self, *_args):
        dialog = Gtk.FileDialog(title=_("Save Image"))
        initial = self.output if self.output and self.output != "-" \
            else export.default_save_path(self.settings)
        dialog.set_initial_file(Gio.File.new_for_path(str(initial)))
        dialog.save(self, None, self._on_save_as_done)

    def _on_save_as_done(self, dialog, result):
        try:
            file = dialog.save_finish(result)
        except GLib.Error:
            return  # cancelled
        path = file.get_path()
        if self._save_to(path):
            # Subsequent Ctrl+S goes to the same place.
            self.output = path

    def _save_to(self, path):
        try:
            export.save_to_file(self.doc, path)
        except GLib.Error as e:
            self._toast(_("Could not save: {error}").format(error=e.message))
            return False
        self._toast(_("Saved to {path}").format(path=path))
        return True
