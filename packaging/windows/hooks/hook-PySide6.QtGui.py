from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies


hiddenimports, binaries, datas = add_qt6_dependencies(__file__)

# Omit unused plugins before native dependency discovery pulls in QML/Quick/PDF.
# Keep native Windows input, SVG icons and the software OpenGL fallback.
unused_plugins = {"qtvirtualkeyboardplugin.dll", "qpdf.dll"}
binaries = [item for item in binaries if Path(item[0]).name.casefold() not in unused_plugins]
