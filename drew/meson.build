configure_file(
  input: '__init__.py.in',
  output: '__init__.py',
  configuration: conf,
  install: true,
  install_dir: moduledir,
)

drew_sources = [
  '__main__.py',
  'app.py',
  'canvas.py',
  'document.py',
  'export.py',
  'filters.py',
  'history.py',
  'i18n.py',
  'model.py',
  'preferences.py',
  'render.py',
  'settings.py',
  'stylebox.py',
  'tools.py',
  'window.py',
]

install_data(drew_sources, install_dir: moduledir)

# Tool icons — kept inside the package data dir and added as an icon
# search path at startup, so the source tree and the install behave alike.
install_subdir(
  'data' / 'icons',
  install_dir: moduledir / 'data',
)
