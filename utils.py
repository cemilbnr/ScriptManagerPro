"""Shared helpers: preferences access, path handling, cross-platform file browser."""

import os
import subprocess
import sys

import bpy

ADDON_ID = __package__


def get_prefs(context=None):
    ctx = context or bpy.context
    addon = ctx.preferences.addons.get(ADDON_ID)
    return addon.preferences if addon else None


def get_script_dirs(context=None):
    """Configured library roots that exist on disk, in preference order."""
    prefs = get_prefs(context)
    if prefs is None:
        return []
    dirs = []
    for entry in prefs.script_dirs:
        raw = entry.path.strip()
        if not raw:
            continue
        path = os.path.normpath(bpy.path.abspath(raw))
        if os.path.isdir(path) and path not in dirs:
            dirs.append(path)
    return dirs


def find_root_for(abs_path, context=None):
    """The configured library root that contains abs_path, or ""."""
    for root in get_script_dirs(context):
        if abs_path == root or abs_path.startswith(root + os.sep):
            return root
    return ""


def split_tags(raw):
    """'rig, util' -> ['rig', 'util']."""
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


def same_file(path_a, path_b):
    try:
        return os.path.normcase(os.path.normpath(path_a)) == os.path.normcase(os.path.normpath(path_b))
    except (TypeError, ValueError):
        return False


def find_text_for_path(abs_path):
    """Return the text datablock already loaded from abs_path, if any."""
    for text in bpy.data.texts:
        if text.filepath and same_file(bpy.path.abspath(text.filepath), abs_path):
            return text
    return None


def open_in_file_browser(path):
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def short_error(exc):
    """Last meaningful line of an exception message (tracebacks from ops are long)."""
    lines = [ln.strip() for ln in str(exc).splitlines() if ln.strip()]
    # Operator errors end with a useless "Location: .../ops.py" line.
    lines = [ln for ln in lines if not ln.startswith("Location:")]
    return lines[-1] if lines else str(exc)
