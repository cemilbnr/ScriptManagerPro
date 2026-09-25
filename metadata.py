"""Per-library metadata: favorites, tags, display names.

Stored inside the script library itself (<scripts>/.script_manager/metadata.json)
so it travels with the folder between machines. Writes are atomic. The layout is
versioned so a future release can add per-script version history without
breaking existing files.
"""

import json
import os
import shutil
import time

META_DIR = ".script_manager"
META_FILE = "metadata.json"
BACKUP_DIR = "backups"
LEGACY_FILE = os.path.join("Manager_preferences", "preferences.json")


def _meta_path(script_dir):
    return os.path.join(script_dir, META_DIR, META_FILE)


def load(script_dir):
    path = _meta_path(script_dir)
    data = None
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            data = None
    if data is None:
        data = _migrate_legacy(script_dir)
    if not isinstance(data, dict):
        data = {}
    return {
        "version": 1,
        "scripts": dict(data.get("scripts", {})),
        # Library-level tag registry: lets a tag exist before any script uses it.
        "tags": list(data.get("tags", [])),
    }


def _migrate_legacy(script_dir):
    """v0.x kept {filename: {favorite, tags, custom_display_name}} in Manager_preferences/."""
    legacy = os.path.join(script_dir, LEGACY_FILE)
    if not os.path.isfile(legacy):
        return None
    try:
        with open(legacy, "r", encoding="utf-8") as fh:
            old = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    scripts = {}
    for name, entry in old.items():
        if isinstance(entry, dict):
            scripts[name] = {
                "favorite": bool(entry.get("favorite", False)),
                "tags": entry.get("tags", ""),
                "display_name": entry.get("custom_display_name", ""),
            }
    return {"version": 1, "scripts": scripts, "folders": {}}


def save(script_dir, data):
    path = _meta_path(script_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def script_entry(data, key):
    return data["scripts"].setdefault(key, {"favorite": False, "tags": "", "display_name": ""})


def make_backup(script_dir, abs_path, keep):
    """Copy the on-disk file into .script_manager/backups/ before it gets overwritten."""
    if not os.path.isfile(abs_path):
        return
    rel = os.path.relpath(abs_path, script_dir)
    backup_root = os.path.join(script_dir, META_DIR, BACKUP_DIR, os.path.dirname(rel))
    os.makedirs(backup_root, exist_ok=True)
    base = os.path.basename(abs_path)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(abs_path, os.path.join(backup_root, f"{base}.{stamp}.bak"))
    _prune(backup_root, base, keep)


def _prune(backup_root, base, keep):
    try:
        entries = sorted(
            f for f in os.listdir(backup_root)
            if f.startswith(base + ".") and f.endswith(".bak")
        )
    except OSError:
        return
    stale = entries[:-keep] if keep > 0 else entries
    for name in stale:
        try:
            os.remove(os.path.join(backup_root, name))
        except OSError:
            pass
