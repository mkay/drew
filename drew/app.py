# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

import sys
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from drew import APP_ID, APP_NAME, VERSION
from drew.i18n import _
from drew.document import Document
from drew.settings import Settings
from drew.window import Window


class Application(Adw.Application):
    def __init__(self):
        # NON_UNIQUE: every launch is its own process. A screenshot tool is
        # run from scripts with an image on stdin; handing the second launch
        # to an already-running instance would leave that stdin unread.
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE
            | Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.settings = Settings()
        self.set_option_context_parameter_string(_("[FILE | -]"))
        self.set_option_context_summary(
            _("Annotate an image. Pass a file, or - to read it from stdin:\n"
              "  grim -g \"$(slurp)\" - | drew -")
        )
        self.add_main_option(
            "output", ord("o"), GLib.OptionFlags.NONE, GLib.OptionArg.FILENAME,
            _("Where Save writes; - for stdout (saves once, then quits)"),
            _("FILE"),
        )
        self.add_main_option(
            "version", ord("v"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            _("Show the application version"), None,
        )

    def do_startup(self):
        Adw.Application.do_startup(self)
        self._register_icons()
        self._setup_actions()

    def _register_icons(self):
        icons = Path(__file__).parent / "data" / "icons"
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        theme.add_search_path(str(icons))

    def _setup_actions(self):
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._on_about)
        self.add_action(about)

        self.set_accels_for_action("app.quit", ["<Control>q"])
        self.set_accels_for_action("win.open", ["<Control>o"])
        self.set_accels_for_action("win.save", ["<Control>s"])
        self.set_accels_for_action("win.save-as", ["<Control><Shift>s"])
        self.set_accels_for_action("window.close", ["<Control>w"])
        self.set_accels_for_action("win.delete", ["Delete", "BackSpace"])
        self.set_accels_for_action("win.raise", ["Page_Up"])
        self.set_accels_for_action("win.lower", ["Page_Down"])
        self.set_accels_for_action("win.front", ["Home"])
        self.set_accels_for_action("win.back", ["End"])
        self.set_accels_for_action("win.tool('select')", ["v", "1"])
        self.set_accels_for_action("win.tool('arrow')", ["a", "2"])
        self.set_accels_for_action("win.tool('line')", ["l", "3"])
        self.set_accels_for_action("win.tool('rect')", ["r", "4"])
        self.set_accels_for_action("win.tool('ellipse')", ["e", "5"])
        self.set_accels_for_action("win.tool('text')", ["t", "6"])
        self.set_accels_for_action("win.tool('marker')", ["m", "7"])
        self.set_accels_for_action("win.tool('highlighter')", ["h"])
        self.set_accels_for_action("win.tool('spotlight')", ["s"])
        self.set_accels_for_action("win.tool('blur')", ["b"])
        self.set_accels_for_action("win.tool('pixelate')", ["p"])
        self.set_accels_for_action("win.preferences", ["<Control>comma"])
        self.set_accels_for_action("win.copy", ["<Control>c"])
        self.set_accels_for_action("win.undo", ["<Control>z"])
        self.set_accels_for_action("win.redo", ["<Control><Shift>z", "<Control>y"])
        self.set_accels_for_action("win.zoom-in", ["<Control>plus", "<Control>equal"])
        self.set_accels_for_action("win.zoom-out", ["<Control>minus"])
        self.set_accels_for_action("win.zoom-100", ["<Control>1"])
        self.set_accels_for_action("win.zoom-fit", ["<Control>0"])

    def do_command_line(self, cmdline):
        options = cmdline.get_options_dict()
        if options.contains("version"):
            print(f"{APP_NAME} {VERSION}")
            return 0

        # FILENAME options are bytestrings; unpack() would turn one into a
        # list of byte values, so read it out explicitly.
        output = options.lookup_value("output", GLib.VariantType("ay"))
        if output is not None:
            output = output.get_bytestring().decode(errors="surrogateescape")
        args = cmdline.get_arguments()[1:]
        if len(args) > 1:
            print(_("Only one image can be opened."), file=sys.stderr)
            return 1

        doc = None
        if args:
            try:
                doc = self._load(args[0])
            except (GLib.Error, OSError) as e:
                message = getattr(e, "message", None) or str(e)
                print(_("Cannot open {source}: {error}").format(
                    source=args[0], error=message), file=sys.stderr)
                return 1

        Window(self, doc=doc, output=output).present()
        return 0

    @staticmethod
    def _load(source):
        if source != "-":
            return Document.from_path(source)
        if sys.stdin.isatty():
            raise OSError(_("stdin is a terminal, not an image"))
        data = sys.stdin.buffer.read()
        if not data:
            raise OSError(_("nothing on stdin"))
        return Document.from_bytes(data)

    def _on_about(self, *_args):
        about = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=VERSION,
            developer_name="Kreuder",
            license_type=Gtk.License.GPL_3_0_ONLY,
            comments=_("Image annotation for Wayland. Bells and whistles included."),
        )
        about.present(self.get_active_window())
