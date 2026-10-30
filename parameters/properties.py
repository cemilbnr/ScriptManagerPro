"""Parameter PropertyGroups and the WindowManager-level parameter cache.

Parameter sets live in their own collection keyed by script path, separate
from `wm.smp_scripts`, so a Refresh never wipes edited values. They are a
cache: only overrides the user saves persist, under "parameters" in the
script's metadata.json entry.
"""

import os

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from .. import metadata
from . import parsing

# Blender's IntProperty is 32 bit; values outside this range cannot be edited.
_INT_MIN = -2 ** 31
_INT_MAX = 2 ** 31 - 1

# Which typed field on SMP_ParamItem holds the value for a given type.
VALUE_PROP = {
    parsing.TYPE_BOOL: "val_bool",
    parsing.TYPE_INT: "val_int",
    parsing.TYPE_FLOAT: "val_float",
    parsing.TYPE_STRING: "val_string",
}

DEFAULT_PROP = {
    parsing.TYPE_BOOL: "def_bool",
    parsing.TYPE_INT: "def_int",
    parsing.TYPE_FLOAT: "def_float",
    parsing.TYPE_STRING: "def_string",
}


class SMP_ParamItem(PropertyGroup):
    name: StringProperty()
    param_type: StringProperty(default="")
    description: StringProperty(default="")
    line: IntProperty(default=0)
    is_valid: BoolProperty(default=True)
    error: StringProperty(default="")
    warning: StringProperty(default="")

    val_bool: BoolProperty(default=False)
    val_int: IntProperty(default=0)
    val_float: FloatProperty(default=0.0, precision=6)
    val_string: StringProperty(default="")

    def_bool: BoolProperty(default=False)
    def_int: IntProperty(default=0)
    def_float: FloatProperty(default=0.0, precision=6)
    def_string: StringProperty(default="")


class SMP_ParamSet(PropertyGroup):
    """The parsed parameters of one script."""
    path: StringProperty(subtype='FILE_PATH')
    error: StringProperty(default="")  # file level problems, one per line
    params: CollectionProperty(type=SMP_ParamItem)


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------

def set_value(param, value, also_default=False):
    prop = VALUE_PROP.get(param.param_type)
    if prop is None:
        return
    setattr(param, prop, value)
    if also_default:
        setattr(param, DEFAULT_PROP[param.param_type], value)


def get_value(param):
    prop = VALUE_PROP.get(param.param_type)
    if prop is None:
        return None
    value = getattr(param, prop)
    if param.param_type == parsing.TYPE_FLOAT:
        # FloatProperty is single precision, so trim the noise digits that a
        # float32 round-trip introduces before writing the value back out.
        return float(f"{value:.7g}")
    return value


def is_modified(param):
    prop = VALUE_PROP.get(param.param_type)
    if prop is None:
        return False
    return getattr(param, prop) != getattr(param, DEFAULT_PROP[param.param_type])


def reset(param):
    prop = VALUE_PROP.get(param.param_type)
    if prop is not None:
        setattr(param, prop, getattr(param, DEFAULT_PROP[param.param_type]))


def collect_overrides(pset):
    """Values that differ from the ones written in the script file."""
    return {
        p.name: get_value(p)
        for p in pset.params
        if p.is_valid and is_modified(p)
    }


def _in_int_range(value):
    return _INT_MIN <= value <= _INT_MAX


# ---------------------------------------------------------------------------
# Parameter sets
# ---------------------------------------------------------------------------

def find_param_set(wm, path):
    for pset in wm.smp_param_sets:
        if pset.path == path:
            return pset
    return None


def ensure_param_set(wm, path):
    pset = find_param_set(wm, path)
    if pset is None:
        pset = wm.smp_param_sets.add()
        pset.path = path
    return pset


def saved_overrides(item):
    """Overrides persisted in the metadata.json entry of a SMP_ScriptItem."""
    if item is None or not os.path.isdir(item.root):
        return {}
    entry = metadata.load(item.root)["scripts"].get(item.rel_key)
    if isinstance(entry, dict) and isinstance(entry.get("parameters"), dict):
        return entry["parameters"]
    return {}


def scan_param_set(pset, saved=None):
    """Re-read the script from disk and rebuild its parameter list.

    `saved` holds persisted overrides, re-applied when they still match the
    parameter's type. Returns True if the file could be read.
    """
    pset.params.clear()
    pset.error = ""
    saved = saved or {}

    try:
        source = parsing.read_source(pset.path)
    except (OSError, UnicodeDecodeError) as exc:
        pset.error = f"Could not read script: {parsing.describe_read_error(exc)}"
        return False

    parsed_params, errors = parsing.parse_exported_parameters(source)
    pset.error = "\n".join(errors)

    for parsed in parsed_params:
        param = pset.params.add()
        param.name = parsed.name
        param.description = parsed.description
        param.line = parsed.line
        param.warning = parsed.warning

        if not parsed.valid:
            param.is_valid = False
            param.error = parsed.error
            continue

        if parsed.type == parsing.TYPE_INT and not _in_int_range(parsed.value):
            param.is_valid = False
            param.error = "value is outside the editable 32 bit integer range"
            continue

        param.param_type = parsed.type
        set_value(param, parsed.value, also_default=True)

        if parsed.name in saved:
            override = parsing.coerce_value(parsed.type, saved[parsed.name])
            if override is None:
                continue
            if parsed.type == parsing.TYPE_INT and not _in_int_range(override):
                continue
            set_value(param, override)

    return True


_classes = (SMP_ParamItem, SMP_ParamSet)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.smp_param_sets = CollectionProperty(type=SMP_ParamSet)


def unregister():
    try:
        del bpy.types.WindowManager.smp_param_sets
    except AttributeError:
        pass
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
