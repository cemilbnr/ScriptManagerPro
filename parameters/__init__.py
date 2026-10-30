"""Optional editable `# @PARAM` script parameters (off by default).

Turned on with "Editable Script Parameters" in the add-on preferences. While it
is off nothing here touches the disk and the Play button runs scripts exactly
as before. While it is on, a run with overridden values executes a patched copy
written to <library>/.script_manager/temp/ with `bpy.ops.script.python_file_run`,
deleted right after — the original .py file is never modified.
"""

if "properties" in locals():
    import importlib
    for _mod in (parsing, properties, operators, ui):
        importlib.reload(_mod)

from . import parsing, properties, operators, ui

_modules = (properties, operators, ui)


def register():
    for mod in _modules:
        mod.register()


def unregister():
    for mod in reversed(_modules):
        mod.unregister()
