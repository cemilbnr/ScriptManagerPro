"""Operators: scanning, running, tagging and Text Editor integration.

Scripts are always executed straight from disk via `bpy.ops.script.python_file_run`
— nothing is imported or appended into the .blend, and the add-on itself contains
no exec()/eval(). Scripts also get a real `__file__`/`__main__` environment and
run in the caller's actual context (the old versions temporarily flipped the area
to a Text Editor, which broke context-sensitive scripts).
"""

import os

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty
from bpy.types import Operator

from . import metadata, scanner, utils


def _find_item(context, path):
    for item in context.window_manager.smp_scripts:
        if item.path == path:
            return item
    return None


def _active_external_text(context):
    space = context.space_data
    if space and space.type == 'TEXT_EDITOR' and space.text and space.text.filepath:
        return space.text
    return None


def _save_text(operator, context, text):
    """Write `text` back to its file, backing up the old version first."""
    abs_path = os.path.normpath(bpy.path.abspath(text.filepath))
    prefs = utils.get_prefs(context)
    root = utils.find_root_for(abs_path, context)
    if prefs and prefs.backup_on_save and root:
        try:
            metadata.make_backup(root, abs_path, prefs.backup_keep)
        except OSError as exc:
            operator.report({'WARNING'}, f"Backup failed: {exc}")
    try:
        bpy.ops.text.save()
        return True
    except RuntimeError:
        pass
    # Fallback for contexts where text.save cannot run.
    try:
        with open(abs_path, "w", encoding="utf-8") as fh:
            fh.write(text.as_string())
        return True
    except OSError as exc:
        operator.report({'ERROR'}, f"Could not save: {exc}")
        return False


class SMP_OT_refresh(Operator):
    bl_idname = "smp.refresh"
    bl_label = "Refresh Script List"
    bl_description = "Rescan all script folders and rebuild the lists"

    def execute(self, context):
        dirs = utils.get_script_dirs(context)
        count = scanner.scan(context)
        if not dirs:
            self.report({'WARNING'}, "Add a valid script folder in the add-on preferences first")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Found {count} script(s) in {len(dirs)} folder(s)")
        return {'FINISHED'}


class SMP_OT_run_script(Operator):
    bl_idname = "smp.run_script"
    bl_label = "Run Script"
    bl_description = "Run this file straight from disk (nothing is imported into the .blend)"
    bl_options = {'REGISTER', 'UNDO'}

    path: StringProperty()

    def execute(self, context):
        if not os.path.isfile(self.path):
            self.report({'ERROR'}, f"File not found: {self.path}")
            return {'CANCELLED'}
        name = os.path.basename(self.path)
        try:
            bpy.ops.script.python_file_run(filepath=self.path)
        except RuntimeError as exc:
            self.report({'ERROR'}, f"{name}: {utils.short_error(exc)}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Ran {name}")
        return {'FINISHED'}


class SMP_OT_open_in_editor(Operator):
    bl_idname = "smp.open_in_editor"
    bl_label = "Open in Text Editor"
    bl_description = (
        "Open the script in a Text Editor. Reuses an existing Text Editor area, "
        "otherwise splits the current area and turns the right half into one"
    )

    path: StringProperty()

    def execute(self, context):
        if not os.path.isfile(self.path):
            self.report({'ERROR'}, f"File not found: {self.path}")
            return {'CANCELLED'}

        text = utils.find_text_for_path(self.path)
        if text is None:
            try:
                text = bpy.data.texts.load(self.path)
            except RuntimeError as exc:
                self.report({'ERROR'}, utils.short_error(exc))
                return {'CANCELLED'}

        area = self._get_editor_area(context)
        if area is None:
            self.report({'ERROR'}, "Could not create a Text Editor area")
            return {'CANCELLED'}

        space = area.spaces.active
        space.text = text
        space.show_line_numbers = True
        space.show_syntax_highlight = True
        space.show_region_ui = True  # keep the Script Manager sidebar available
        self.report({'INFO'}, f"Opened {text.name}")
        return {'FINISHED'}

    def _get_editor_area(self, context):
        # Called from a Text Editor sidebar: use that editor directly.
        if context.area and context.area.type == 'TEXT_EDITOR':
            return context.area
        # Reuse an existing editor on this screen instead of splitting again.
        for area in context.screen.areas:
            if area.type == 'TEXT_EDITOR':
                return area
        return self._split_current_area(context)

    def _split_current_area(self, context):
        window, area = context.window, context.area
        if window is None or area is None:
            return None
        before = {a.as_pointer() for a in window.screen.areas}
        try:
            with context.temp_override(window=window, area=area):
                bpy.ops.screen.area_split(direction='VERTICAL', factor=0.5)
        except RuntimeError:
            return None
        new_areas = [a for a in window.screen.areas if a.as_pointer() not in before]
        if not new_areas:
            return None
        # 'VERTICAL' yields side-by-side halves; the right one becomes the editor.
        editor = new_areas[0] if new_areas[0].x >= area.x else area
        editor.type = 'TEXT_EDITOR'
        return editor


class SMP_OT_toggle_favorite(Operator):
    bl_idname = "smp.toggle_favorite"
    bl_label = "Toggle Favorite"
    bl_description = "Add or remove this script from favorites"

    path: StringProperty()

    def execute(self, context):
        item = _find_item(context, self.path)
        if item is None:
            return {'CANCELLED'}
        item.favorite = not item.favorite
        if os.path.isdir(item.root):
            data = metadata.load(item.root)
            metadata.script_entry(data, item.rel_key)["favorite"] = item.favorite
            metadata.save(item.root, data)
        scanner.build_categories(context)  # keep the Favorites count fresh
        return {'FINISHED'}


class SMP_OT_edit_script_meta(Operator):
    bl_idname = "smp.edit_script_meta"
    bl_label = "Script Settings"
    bl_description = "Edit the display name and tags of this script"

    path: StringProperty(options={'HIDDEN'})
    display_name: StringProperty(
        name="Display Name",
        description="Shown instead of the file name (leave empty to use the file name)",
    )
    tags: StringProperty(
        name="Tags",
        description="Comma separated; each tag becomes a group in the tag list",
    )

    def invoke(self, context, event):
        item = _find_item(context, self.path)
        if item is None:
            return {'CANCELLED'}
        self.display_name = item.display_name
        self.tags = item.tags
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        layout = self.layout
        layout.label(text=os.path.basename(self.path), icon='FILE_SCRIPT')
        layout.prop(self, "display_name")
        layout.prop(self, "tags")

    def execute(self, context):
        item = _find_item(context, self.path)
        if item is None:
            return {'CANCELLED'}
        item.display_name = self.display_name.strip()
        item.tags = ", ".join(utils.split_tags(self.tags))
        if os.path.isdir(item.root):
            data = metadata.load(item.root)
            entry = metadata.script_entry(data, item.rel_key)
            entry["display_name"] = item.display_name
            entry["tags"] = item.tags
            metadata.save(item.root, data)
        scanner.build_categories(context)  # tags may have appeared/disappeared
        return {'FINISHED'}


class SMP_OT_add_tag(Operator):
    bl_idname = "smp.add_tag"
    bl_label = "New Tag"
    bl_description = "Create an empty tag; assign scripts to it via their settings"

    tag_name: StringProperty(name="Tag Name", default="")

    def invoke(self, context, event):
        self.tag_name = ""
        return context.window_manager.invoke_props_dialog(self, width=280)

    def execute(self, context):
        tag = self.tag_name.strip().strip(",").strip()
        if not tag:
            self.report({'WARNING'}, "Tag name is empty")
            return {'CANCELLED'}
        roots = scanner.scope_roots(context)
        if not roots:
            self.report({'ERROR'}, "No valid script folder configured")
            return {'CANCELLED'}
        for root in roots:
            data = metadata.load(root)
            if tag.casefold() not in {t.casefold() for t in data["tags"]}:
                data["tags"].append(tag)
                metadata.save(root, data)
            scanner.set_registry_tags(root, data["tags"])
        scanner.build_categories(context)
        wm = context.window_manager
        for i, cat in enumerate(wm.smp_categories):
            if cat.kind == 'TAG' and cat.value == tag.casefold():
                wm.smp_active_category = i
                break
        return {'FINISHED'}


class SMP_OT_remove_tag(Operator):
    bl_idname = "smp.remove_tag"
    bl_label = "Remove Tag"
    bl_description = "Delete the selected tag and remove it from every script in scope"

    tag: StringProperty(options={'HIDDEN'})      # casefolded value
    display: StringProperty(options={'HIDDEN'})  # original spelling for messages

    def _resolve(self, context):
        if self.tag:
            return True
        cat = scanner.active_category(context.window_manager)
        if cat is None or cat.kind != 'TAG':
            return False
        self.tag = cat.value
        self.display = cat.name
        return True

    def _single_folder_scope(self, context):
        # Deleting is destructive, so it must target one library at a time.
        if len(scanner.scope_roots(context)) > 1:
            self.report({'WARNING'}, 'Select a single folder in the "Folders" panel to remove a tag')
            return False
        return True

    def invoke(self, context, event):
        if not self._single_folder_scope(context):
            return {'CANCELLED'}
        if not self._resolve(context):
            self.report({'WARNING'}, "Select a tag in the list first")
            return {'CANCELLED'}
        return context.window_manager.invoke_confirm(
            self, event,
            title="Remove Tag",
            message=f"Remove tag '{self.display or self.tag}' from all scripts in this folder?",
            icon='WARNING',
        )

    def execute(self, context):
        if not self._single_folder_scope(context):
            return {'CANCELLED'}
        if not self._resolve(context):
            self.report({'WARNING'}, "Select a tag in the list first")
            return {'CANCELLED'}
        value = self.tag
        wm = context.window_manager
        for root in scanner.scope_roots(context):
            data = metadata.load(root)
            data["tags"] = [t for t in data["tags"] if t.casefold() != value]
            for entry in data["scripts"].values():
                if isinstance(entry, dict) and entry.get("tags"):
                    kept = [t for t in utils.split_tags(entry["tags"]) if t.casefold() != value]
                    entry["tags"] = ", ".join(kept)
            metadata.save(root, data)
            scanner.set_registry_tags(root, data["tags"])
        for item in wm.smp_scripts:
            if scanner.in_scope(wm, item) and item.tags:
                kept = [t for t in utils.split_tags(item.tags) if t.casefold() != value]
                item.tags = ", ".join(kept)
        scanner.build_categories(context)
        return {'FINISHED'}


class SMP_OT_add_script_dir(Operator):
    bl_idname = "smp.add_script_dir"
    bl_label = "Add Script Folder"
    bl_description = "Add another script folder to the library list"

    def execute(self, context):
        prefs = utils.get_prefs(context)
        if prefs is None:
            return {'CANCELLED'}
        prefs.script_dirs.add()
        return {'FINISHED'}


class SMP_OT_remove_script_dir(Operator):
    bl_idname = "smp.remove_script_dir"
    bl_label = "Remove Script Folder"
    bl_description = "Remove this folder from the library list (nothing is deleted on disk)"

    index: IntProperty(options={'HIDDEN'})

    def execute(self, context):
        prefs = utils.get_prefs(context)
        if prefs is None or not (0 <= self.index < len(prefs.script_dirs)):
            return {'CANCELLED'}
        raw = prefs.script_dirs[self.index].path.strip()
        root = os.path.normpath(bpy.path.abspath(raw)) if raw else ""
        prefs.script_dirs.remove(self.index)
        # No disk walk here: just drop the cached entries of that library.
        scanner.purge_root(context, root)
        return {'FINISHED'}


class SMP_OT_open_folder(Operator):
    bl_idname = "smp.open_folder"
    bl_label = "Open Scripts Folder"
    bl_description = "Open the scripts folder in the system file browser"

    path: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        target = self.path
        if not target:
            dirs = utils.get_script_dirs(context)
            if len(dirs) > 1:
                self.report({'ERROR'}, 'Please select the script folder from the "Folders" panel!')
                return {'CANCELLED'}
            target = dirs[0] if dirs else ""
        if not target or not os.path.isdir(target):
            self.report({'ERROR'}, "Scripts folder is not set or does not exist")
            return {'CANCELLED'}
        try:
            utils.open_in_file_browser(target)
        except OSError as exc:
            self.report({'ERROR'}, f"Could not open folder: {exc}")
            return {'CANCELLED'}
        return {'FINISHED'}


class SMP_OT_save_script(Operator):
    bl_idname = "smp.save_script"
    bl_label = "Update & Save"
    bl_description = "Write this text back to its .py file on disk (a backup is kept if enabled)"

    @classmethod
    def poll(cls, context):
        return _active_external_text(context) is not None

    def execute(self, context):
        text = _active_external_text(context)
        if not _save_text(self, context, text):
            return {'CANCELLED'}
        self.report({'INFO'}, f"Saved {text.name}")
        return {'FINISHED'}


class SMP_OT_save_and_run(Operator):
    bl_idname = "smp.save_and_run"
    bl_label = "Save & Run"
    bl_description = "Save this text back to its .py file, then run the file from disk"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_external_text(context) is not None

    def execute(self, context):
        text = _active_external_text(context)
        if not _save_text(self, context, text):
            return {'CANCELLED'}
        abs_path = os.path.normpath(bpy.path.abspath(text.filepath))
        try:
            bpy.ops.script.python_file_run(filepath=abs_path)
        except RuntimeError as exc:
            self.report({'ERROR'}, f"{text.name}: {utils.short_error(exc)}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Saved and ran {text.name}")
        return {'FINISHED'}


def _target_dir_items(self, context):
    global _dir_enum_cache
    items = []
    for root in utils.get_script_dirs(context):
        label = os.path.basename(root.rstrip(os.sep)) or root
        items.append((root, label, root))
    if not items:
        items = [("", "No script folders", "")]
    _dir_enum_cache = items  # keep the strings alive (Blender enum callback rule)
    return _dir_enum_cache


_dir_enum_cache = []


class SMP_OT_save_as_script(Operator):
    bl_idname = "smp.save_as_script"
    bl_label = "Save as Python Script"
    bl_description = "Save this text into a script folder as a .py file and link it to the library"

    filename: StringProperty(
        name="File Name",
        description="Name of the .py file; a subfolder like tools/name.py is allowed",
    )
    target_dir: EnumProperty(name="Folder", items=_target_dir_items)

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return (
            space is not None
            and space.type == 'TEXT_EDITOR'
            and space.text is not None
            and not space.text.filepath
            and bool(utils.get_script_dirs(context))
        )

    def invoke(self, context, event):
        base = context.space_data.text.name.strip() or "script"
        if not base.lower().endswith(".py"):
            base += ".py"
        self.filename = base
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "filename")
        if len(utils.get_script_dirs(context)) > 1:
            layout.prop(self, "target_dir")

    def execute(self, context):
        dirs = utils.get_script_dirs(context)
        if not dirs:
            self.report({'ERROR'}, "No valid script folder configured")
            return {'CANCELLED'}
        root = self.target_dir if self.target_dir in dirs else dirs[0]

        name = self.filename.strip().replace("\\", "/").strip("/")
        if not name or name.lower() == ".py":
            self.report({'WARNING'}, "File name is empty")
            return {'CANCELLED'}
        if not name.lower().endswith(".py"):
            name += ".py"
        path = os.path.normpath(os.path.join(root, *name.split("/")))
        if not path.startswith(root + os.sep):
            self.report({'ERROR'}, "File name must stay inside the script folder")
            return {'CANCELLED'}
        if os.path.exists(path):
            self.report({'ERROR'}, f"Already exists: {os.path.relpath(path, root)}")
            return {'CANCELLED'}

        text = context.space_data.text
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except OSError as exc:
            self.report({'ERROR'}, f"Could not create folder: {exc}")
            return {'CANCELLED'}
        try:
            bpy.ops.text.save_as(filepath=path)
        except RuntimeError:
            # Fallback: write manually and relink the datablock to the file.
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text.as_string())
            except OSError as exc:
                self.report({'ERROR'}, f"Could not save: {exc}")
                return {'CANCELLED'}
            space = context.space_data
            bpy.data.texts.remove(text)
            space.text = bpy.data.texts.load(path)

        scanner.scan(context)
        self.report({'INFO'}, f"Saved {os.path.relpath(path, root)}")
        return {'FINISHED'}


class SMP_OT_reload_script(Operator):
    bl_idname = "smp.reload_script"
    bl_label = "Reload from Disk"
    bl_description = "Discard the edits in this editor and reload the file from disk"

    @classmethod
    def poll(cls, context):
        return _active_external_text(context) is not None

    def invoke(self, context, event):
        text = _active_external_text(context)
        if text and text.is_dirty:
            return context.window_manager.invoke_confirm(self, event)
        return self.execute(context)

    def execute(self, context):
        try:
            bpy.ops.text.reload()
        except RuntimeError as exc:
            self.report({'ERROR'}, utils.short_error(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, "Reloaded from disk")
        return {'FINISHED'}


class SMP_OT_close_script(Operator):
    bl_idname = "smp.close_script"
    bl_label = "Close Script"
    bl_description = "Remove this text from the .blend (the file on disk is kept)"

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space and space.type == 'TEXT_EDITOR' and space.text is not None

    def invoke(self, context, event):
        text = context.space_data.text
        if text and text.is_dirty:
            return context.window_manager.invoke_confirm(self, event)
        return self.execute(context)

    def execute(self, context):
        text = context.space_data.text
        name = text.name
        bpy.data.texts.remove(text)
        self.report({'INFO'}, f"Closed {name}")
        return {'FINISHED'}


_classes = (
    SMP_OT_refresh,
    SMP_OT_run_script,
    SMP_OT_open_in_editor,
    SMP_OT_toggle_favorite,
    SMP_OT_edit_script_meta,
    SMP_OT_add_tag,
    SMP_OT_remove_tag,
    SMP_OT_add_script_dir,
    SMP_OT_remove_script_dir,
    SMP_OT_open_folder,
    SMP_OT_save_script,
    SMP_OT_save_and_run,
    SMP_OT_save_as_script,
    SMP_OT_reload_script,
    SMP_OT_close_script,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
