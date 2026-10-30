"""Parameter operators and the patched run used by the Play button.

A run with overrides writes a patched copy of the script to
<library>/.script_manager/temp/<rel_key>, runs that copy with
`bpy.ops.script.python_file_run` and deletes it straight after. The copy sets
`__file__` to the original path, so code that locates files or imports modules
next to the script behaves as in a normal run. The original file is never
modified and the add-on still uses no exec()/eval().
"""

import os

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from .. import metadata, utils
from ..operators import _find_item
from . import parsing, properties

TEMP_DIR = "temp"  # inside <library>/.script_manager/


def is_enabled(context=None):
    prefs = utils.get_prefs(context)
    return bool(prefs and getattr(prefs, "enable_parameters", False))


def _item_for_file(context, path):
    """The list item for `path`, matched like the file system does (case etc.)."""
    item = _find_item(context, path)
    if item is not None:
        return item
    for item in context.window_manager.smp_scripts:
        if utils.same_file(item.path, path):
            return item
    return None


def _overrides_for(context, path):
    """Overrides to apply when running `path`: the loaded set, else the saved ones."""
    pset = properties.find_param_set(context.window_manager, path)
    if pset is not None:
        return properties.collect_overrides(pset)
    return properties.saved_overrides(_find_item(context, path))


def _temp_path(context, path):
    item = _find_item(context, path)
    root = item.root if item else utils.find_root_for(path, context)
    if not root:
        return "", ""
    rel_key = item.rel_key if item else os.path.relpath(path, root).replace(os.sep, "/")
    return root, os.path.join(root, metadata.META_DIR, TEMP_DIR, *rel_key.split("/"))


def _cleanup(root, tmp):
    try:
        if os.path.isfile(tmp):
            os.remove(tmp)
    except OSError:
        pass
    # Remove the now empty mirror folders, up to and including temp/ itself.
    stop = os.path.join(root, metadata.META_DIR)
    folder = os.path.dirname(tmp)
    while folder and folder != stop and folder.startswith(root):
        try:
            os.rmdir(folder)
        except OSError:
            break
        folder = os.path.dirname(folder)


def patched_run(operator, context, path):
    """Run `path` with its parameter overrides.

    Returns None when there is nothing to apply (feature off, no overrides),
    so the caller carries on with its normal run; otherwise the operator result.
    """
    if not is_enabled(context):
        return None
    item = _item_for_file(context, path)
    if item is not None:
        path = item.path  # the spelling the parameter sets are keyed by
    overrides = _overrides_for(context, path)
    if not overrides:
        return None

    name = os.path.basename(path)
    try:
        source = parsing.read_source(path)
    except (OSError, UnicodeDecodeError) as exc:
        operator.report({'ERROR'}, f"Could not read {name}: {parsing.describe_read_error(exc)}")
        return {'CANCELLED'}
    patched, applied = parsing.apply_overrides(source, overrides)
    if not applied:
        return None
    patched = parsing.inject_file_path(patched, path)

    root, tmp = _temp_path(context, path)
    if not tmp:
        operator.report({'ERROR'}, f"{name} is not inside a configured script folder")
        return {'CANCELLED'}

    _cleanup(root, tmp)  # stale copy left behind by a crash
    try:
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(patched)
    except OSError as exc:
        # Never fall back to the file's own values: the user asked for others.
        operator.report({'ERROR'}, f"Could not write the patched copy of {name}: {exc}")
        _cleanup(root, tmp)
        return {'CANCELLED'}

    try:
        bpy.ops.script.python_file_run(filepath=tmp)
    except RuntimeError as exc:
        operator.report({'ERROR'}, f"{name}: {utils.short_error(exc)}")
        return {'CANCELLED'}
    finally:
        _cleanup(root, tmp)
    operator.report({'INFO'}, f"Ran {name} with {len(applied)} parameter override(s)")
    return {'FINISHED'}


def rescan_after_save(context, path):
    """Re-read a loaded parameter set after its file was saved, keeping edits."""
    if not is_enabled(context):
        return
    item = _item_for_file(context, path)
    pset = properties.find_param_set(context.window_manager, item.path if item else path)
    if pset is not None:
        properties.scan_param_set(pset, properties.collect_overrides(pset))


class _ParamsOperator:
    path: StringProperty(options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return is_enabled(context)


class SMP_OT_params_load(_ParamsOperator, Operator):
    bl_idname = "smp.params_load"
    bl_label = "Load Parameters"
    bl_description = "Read this script from disk and list its @PARAM parameters"

    def execute(self, context):
        item = _find_item(context, self.path)
        if item is None:
            return {'CANCELLED'}
        pset = properties.ensure_param_set(context.window_manager, self.path)
        if not properties.scan_param_set(pset, properties.saved_overrides(item)):
            self.report({'ERROR'}, pset.error)
            return {'CANCELLED'}

        invalid = sum(1 for p in pset.params if not p.is_valid)
        message = f"{len(pset.params) - invalid} parameter(s) found in {item.name}"
        if invalid or pset.error:
            self.report({'WARNING'}, f"{message}; see the panel for problems")
        else:
            self.report({'INFO'}, message)
        return {'FINISHED'}


class SMP_OT_params_reset(_ParamsOperator, Operator):
    bl_idname = "smp.params_reset"
    bl_label = "Reset Parameters"
    bl_description = "Restore the value(s) written in the script file"

    param_name: StringProperty(options={'HIDDEN'})  # empty = all

    def execute(self, context):
        pset = properties.find_param_set(context.window_manager, self.path)
        if pset is None:
            return {'CANCELLED'}
        for param in pset.params:
            if param.is_valid and (not self.param_name or param.name == self.param_name):
                properties.reset(param)
        return {'FINISHED'}


class SMP_OT_params_save(_ParamsOperator, Operator):
    bl_idname = "smp.params_save"
    bl_label = "Save Parameters"
    bl_description = "Remember these parameter values across Blender sessions"

    def execute(self, context):
        item = _find_item(context, self.path)
        pset = properties.find_param_set(context.window_manager, self.path)
        if item is None or pset is None or not os.path.isdir(item.root):
            return {'CANCELLED'}
        overrides = properties.collect_overrides(pset)
        data = metadata.load(item.root)
        entry = metadata.script_entry(data, item.rel_key)
        if overrides:
            entry["parameters"] = overrides
        else:
            entry.pop("parameters", None)
        metadata.save(item.root, data)
        self.report({'INFO'}, f"Saved {len(overrides)} parameter override(s) for {item.name}")
        return {'FINISHED'}


_classes = (
    SMP_OT_params_load,
    SMP_OT_params_reset,
    SMP_OT_params_save,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
