# Drew

Image annotation for Wayland. Bells and whistles included.

![Drew Icon](data/de.singular.drew.svg)

Open an image or pipe one in and add arrows, shapes, text, numbered markers, spotlight, blur and pixelate. Everything stays movable and resizable until you save.

Drew captures nothing itself — it takes its image from grim, wl-paste or any other tool. Built with GTK4 and libadwaita.

## Usage

    drew image.png
    grim -g "$(slurp)" - | drew -              # read from stdin
    grim - | drew - -o shot.png                # Ctrl+S writes here
    grim - | drew - -o - | wl-copy             # Ctrl+S writes to stdout and quits

Without `-o`, Ctrl+S writes `~/Pictures/screenshot-YYYYMMDD-HHMMSS.png` — folder and prefix are configurable in Preferences (Ctrl+,); Ctrl+Shift+S asks. The input file is never overwritten.

## Tools

| Key | Tool |
|-----|------|
| V / 1 | Select — click to select, drag to move, drag a handle to resize, double-click text to edit |
| A / 2 | Arrow (Shift snaps to 45°) |
| L / 3 | Line |
| R / 4 | Rectangle (Shift for square) |
| E / 5 | Ellipse (Shift for circle) |
| T / 6 | Text |
| M / 7 | Numbered marker — stays active so you can drop 1, 2, 3 in a row |
| H | Highlighter — translucent wash in the current colour, marker-pen style |
| S | Spotlight — everything outside the region is dimmed; several regions combine |
| B | Blur — strength follows the line width slider |
| P | Pixelate — block size follows the line width slider |

Delete removes the selection, Esc deselects, arrow keys nudge (Shift = 10 px). Page Up / Page Down raise or lower the selected shape one step, Home / End bring it to the front or send it to the back; the same is in the right-click menu on a shape. Ctrl+Z / Ctrl+Shift+Z undo and redo, Ctrl+C copies the annotated image to the clipboard. Ctrl+scroll zooms around the pointer, Ctrl+plus/minus step, Ctrl+1 is actual size, Ctrl+0 fits the window again; middle-drag pans. Colour, line width, text size and fill live behind the swatch button; changing them restyles the selected shape. Fill turns rectangles and ellipses solid and puts text on a rounded chip.

## Building

    meson setup builddir
    meson compile -C builddir
    meson install -C builddir

Runs from the source tree without installing: `python -m drew` after `meson setup` has generated `drew/__init__.py` — copy it from `builddir/drew/__init__.py` or run the installed launcher.

Dependencies: Python 3, PyGObject, GTK 4, libadwaita ≥ 1.7, gdk-pixbuf, pycairo, Pillow.

Icons are [Phosphor Icons](https://phosphoricons.com/) (MIT), bundled under `drew/data/icons/`; `scripts/extract-phosphor.py` regenerates them from the Phosphor release zip.

## License

GPL-3.0-only. Phosphor Icons are MIT.
