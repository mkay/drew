# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from drew.i18n import _
from drew.export import pictures_dir


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, settings):
        super().__init__(title=_("Preferences"))
        self.settings = settings

        page = Adw.PreferencesPage()
        self.add(page)
        group = Adw.PreferencesGroup(title=_("Saving"))
        page.add(group)

        self._folder_row = Adw.ActionRow(title=_("Folder"),
                                         activatable=True)
        self._folder_row.add_suffix(
            Gtk.Image(icon_name="drew-folder-symbolic"))
        self._folder_row.connect("activated", self._on_pick_folder)
        group.add(self._folder_row)
        self._show_folder()

        prefix = Adw.EntryRow(title=_("File name prefix"),
                              text=settings.get("filename_prefix"))
        prefix.connect("changed", self._on_prefix_changed)
        group.add(prefix)

    def _show_folder(self):
        folder = self.settings.get("save_dir") or str(pictures_dir())
        self._folder_row.set_subtitle(folder)

    def _on_pick_folder(self, _row):
        dialog = Gtk.FileDialog(title=_("Choose Folder"))
        current = self.settings.get("save_dir") or str(pictures_dir())
        dialog.set_initial_folder(Gio.File.new_for_path(current))
        dialog.select_folder(self.get_root(), None, self._on_folder_picked)

    def _on_folder_picked(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:
            return  # cancelled
        self.settings.set("save_dir", folder.get_path())
        self._show_folder()

    def _on_prefix_changed(self, row):
        # A stray "/" would turn the prefix into a path; drop it silently.
        prefix = row.get_text().replace("/", "").strip()
        self.settings.set("filename_prefix", prefix or "screenshot")
