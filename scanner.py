"""Builds the WindowManager caches: folder (library) list, scripts, tag categories."""

import os

import bpy

from . import metadata, utils

SKIP_DIRS = {"__pycache__", "Manager_preferences"}

# root -> tags stored in that library's metadata (the "empty tag" registry)
_registry_cache = {}

# True while build_categories() populates rows, so setting item.name there
# does not fire the rename-update callback.
_building = False


def is_building():
    return _building


def _migrate_legacy_prefs(prefs):
    """v1.x had a single script_dir; move it into the script_dirs collection."""
    if prefs is None:
        return
    legacy = prefs.script_dir.strip()
    if legacy and len(prefs.script_dirs) == 0:
        entry = prefs.script_dirs.add()
        entry["path"] = legacy  # raw assignment: skips the update callback (no rescan loop)
        prefs.script_dir = ""


def scan(context=None):
    """Rescan all libraries and rebuild the UI caches. Returns the script count."""
    ctx = context or bpy.context
    wm = ctx.window_manager
    _migrate_legacy_prefs(utils.get_prefs(ctx))

    wm.smp_scripts.clear()
    _registry_cache.clear()

    total = 0
    for root in utils.get_script_dirs(ctx):
        meta = metadata.load(root)
        _registry_cache[root] = [t for t in meta.get("tags", []) if isinstance(t, str)]

        scripts = []  # (rel_dir, file name, absolute path)
        for walk_root, dirs, files in os.walk(root):
            dirs[:] = sorted(
                (d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS),
                key=str.lower,
            )
            rel_dir = os.path.relpath(walk_root, root)
            rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
            for fname in sorted(files, key=str.lower):
                if fname.endswith(".py"):
                    scripts.append((rel_dir, fname, os.path.join(walk_root, fname)))

        scripts.sort(key=lambda s: (
            [p.lower() for p in s[0].split("/")] if s[0] else [],
            s[1].lower(),
        ))
        for rel_dir, fname, abs_path in scripts:
            key = f"{rel_dir}/{fname}" if rel_dir else fname
            entry = meta["scripts"].get(key, {})
            item = wm.smp_scripts.add()
            item.name = fname
            item.root = root
            item.rel_key = key
            item.rel_dir = rel_dir
            item.path = abs_path
            item.favorite = bool(entry.get("favorite", False))
            item.tags = entry.get("tags", "")
            item.display_name = entry.get("display_name", "")
        total += len(scripts)

    build_folders(ctx)
    build_categories(ctx)
    return total


def build_folders(context=None):
    """Rebuild the folder list: 'All Folders' plus one row per configured library."""
    ctx = context or bpy.context
    wm = ctx.window_manager
    folders = wm.smp_folders

    previous = None
    if 0 <= wm.smp_active_folder < len(folders):
        active = folders[wm.smp_active_folder]
        previous = (active.kind, active.value)

    folders.clear()

    item = folders.add()
    item.kind = 'ALL'
    item.name = "All Folders"
    item.value = ""
    item.count = len(wm.smp_scripts)

    for root in utils.get_script_dirs(ctx):
        item = folders.add()
        item.kind = 'DIR'
        item.name = os.path.basename(root.rstrip(os.sep)) or root
        item.value = root
        item.count = sum(1 for s in wm.smp_scripts if s.root == root)

    index = 0
    if previous is not None:
        for i, folder in enumerate(folders):
            if (folder.kind, folder.value) == previous:
                index = i
                break
    # Assigning triggers the update callback, which rebuilds the categories.
    wm.smp_active_folder = index


def scope_root(wm):
    """The library root the UI is focused on, or "" when 'All Folders' is active."""
    if 0 <= wm.smp_active_folder < len(wm.smp_folders):
        item = wm.smp_folders[wm.smp_active_folder]
        if item.kind == 'DIR':
            return item.value
    return ""


def scope_roots(context=None):
    ctx = context or bpy.context
    root = scope_root(ctx.window_manager)
    return [root] if root else utils.get_script_dirs(ctx)


def in_scope(wm, item):
    root = scope_root(wm)
    return not root or item.root == root


def registry_tags(root):
    return _registry_cache.get(root, [])


def set_registry_tags(root, tags):
    _registry_cache[root] = list(tags)


def build_categories(context=None):
    """Rebuild the tag list (All / Favorites / tags / Untagged) for the folder scope.

    Keeps the current selection when the same category still exists, so counts
    can refresh after a favorite/tag edit without the view jumping. Tags from
    the per-library registry appear even when no script uses them yet.
    """
    global _building
    ctx = context or bpy.context
    wm = ctx.window_manager
    cats = wm.smp_categories

    previous = None
    if 0 <= wm.smp_active_category < len(cats):
        active = cats[wm.smp_active_category]
        previous = (active.kind, active.value)

    _building = True
    try:
        cats.clear()
        scripts = [s for s in wm.smp_scripts if in_scope(wm, s)]

        def add(kind, name, value, count):
            item = cats.add()
            item.kind = kind
            item.name = name
            item.value = value
            item.count = count

        add('ALL', "All Scripts", "", len(scripts))
        add('FAV', "Favorites", "", sum(1 for s in scripts if s.favorite))

        tag_map = {}  # casefolded tag -> (display text, count)
        root = scope_root(wm)
        for reg_root in ([root] if root else list(_registry_cache)):
            for tag in _registry_cache.get(reg_root, []):
                key = tag.casefold()
                if key not in tag_map:
                    tag_map[key] = (tag, 0)

        untagged = 0
        for script in scripts:
            tags = utils.split_tags(script.tags)
            if not tags:
                untagged += 1
            for tag in tags:
                key = tag.casefold()
                display, count = tag_map.get(key, (tag, 0))
                tag_map[key] = (display, count + 1)

        for key in sorted(tag_map):
            display, count = tag_map[key]
            add('TAG', display, key, count)
        if untagged:
            add('UNTAGGED', "Untagged", "", untagged)

        index = 0
        if previous is not None:
            for i, cat in enumerate(cats):
                if (cat.kind, cat.value) == previous:
                    index = i
                    break
        wm.smp_active_category = index
    finally:
        _building = False


def active_category(wm):
    if 0 <= wm.smp_active_category < len(wm.smp_categories):
        return wm.smp_categories[wm.smp_active_category]
    return None


def category_matches(cat, item):
    kind = cat.kind
    if kind == 'FAV':
        return item.favorite
    if kind == 'UNTAGGED':
        return not utils.split_tags(item.tags)
    if kind == 'TAG':
        return cat.value in {t.casefold() for t in utils.split_tags(item.tags)}
    return True  # 'ALL' and anything unknown


def purge_root(context, root):
    """Drop a removed library from the caches without touching the disk."""
    ctx = context or bpy.context
    wm = ctx.window_manager
    for i in range(len(wm.smp_scripts) - 1, -1, -1):
        if wm.smp_scripts[i].root == root:
            wm.smp_scripts.remove(i)
    _registry_cache.pop(root, None)
    build_folders(ctx)
    build_categories(ctx)


def _replace_tag(raw, old_casefold, new):
    """Rename a tag inside a comma-separated tag string, deduplicating."""
    result, seen = [], set()
    for tag in utils.split_tags(raw):
        renamed = new if tag.casefold() == old_casefold else tag
        key = renamed.casefold()
        if key not in seen:
            seen.add(key)
            result.append(renamed)
    return ", ".join(result)


def apply_tag_rename(old_value, new_name):
    """Deferred worker for the double-click tag rename in the tag list.

    Renames the tag in every in-scope library that actually knows it (registry
    or scripts) and in the cached items; renaming onto an existing tag merges
    them. Runs from a timer, so the UI callback never rebuilds its own list.
    """
    ctx = bpy.context
    wm = ctx.window_manager
    new = new_name.strip().strip(",").strip()
    if not new:
        build_categories(ctx)  # revert the edit in the UI
        return None

    for root in scope_roots(ctx):
        data = metadata.load(root)
        had_registry = any(t.casefold() == old_value for t in data["tags"])
        had_script = any(
            isinstance(entry, dict)
            and old_value in {t.casefold() for t in utils.split_tags(entry.get("tags", ""))}
            for entry in data["scripts"].values()
        )
        if not (had_registry or had_script):
            continue  # this library never knew the tag; leave it untouched
        tags = [t for t in data["tags"] if t.casefold() != old_value]
        if new.casefold() not in {t.casefold() for t in tags}:
            tags.append(new)
        data["tags"] = tags
        for entry in data["scripts"].values():
            if isinstance(entry, dict) and entry.get("tags"):
                entry["tags"] = _replace_tag(entry["tags"], old_value, new)
        metadata.save(root, data)
        set_registry_tags(root, tags)

    for item in wm.smp_scripts:
        if in_scope(wm, item) and item.tags:
            item.tags = _replace_tag(item.tags, old_value, new)

    build_categories(ctx)
    for i, cat in enumerate(wm.smp_categories):
        if cat.kind == 'TAG' and cat.value == new.casefold():
            wm.smp_active_category = i
            break
    return None
