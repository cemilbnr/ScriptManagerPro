"""Script Manager Pro — organize, edit and run external Python scripts in Blender.

Scripts stay on disk: they are executed with `bpy.ops.script.python_file_run`,
never imported or appended into the .blend, and the add-on uses no exec()/eval().
The library folders are only read when the user presses Refresh (or saves a new
script into them) — no scanning happens on startup or file load.

Extension metadata lives in blender_manifest.toml.
"""

if "utils" in locals():
    import importlib
    for _mod in (utils, metadata, properties, scanner, preferences, operators, ui):
        importlib.reload(_mod)

from . import utils, metadata, properties, scanner, preferences, operators, ui

_modules = (properties, preferences, operators, ui)


def register():
    for mod in _modules:
        mod.register()


def unregister():
    for mod in reversed(_modules):
        mod.unregister()
