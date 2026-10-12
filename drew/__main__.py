# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

import ctypes
import locale
import sys

# gtk4-layer-shell must be loaded before libwayland-client — before GTK is
# imported — or it can't hook in. Pinned images use it to float above other
# windows; without it they fall back to a plain borderless window.
try:
    ctypes.CDLL("libgtk4-layer-shell.so.0")
except OSError:
    pass

from drew import LOCALEDIR
from drew.i18n import GETTEXT_DOMAIN
from drew.app import Application


def main():
    # Honour the user's locale, and point the C library at our catalogues so
    # anything translated below the Python layer resolves too.
    try:
        locale.setlocale(locale.LC_ALL, "")
        locale.bindtextdomain(GETTEXT_DOMAIN, LOCALEDIR)
        locale.textdomain(GETTEXT_DOMAIN)
    except (locale.Error, AttributeError):
        # An unsupported LANG shouldn't stop the app from starting.
        pass

    app = Application()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
