bl_info = {
    "name": "Script Manager Pro",
    "blender": (4, 4, 0),
    "version": (0, 0, 3),
    "category": "Development",
    "author": "Cemil Berk",
    "description": "Manage and run your Python scripts in Blender with one-click access, favorites, tags, and in-panel editing.",
    "support": "COMMUNITY"
}

import bpy
import os
import json
from bpy.props import StringProperty, CollectionProperty, BoolProperty
from bpy.types import Operator, Panel, PropertyGroup, AddonPreferences


def get_metadata_path(script_dir):
    return os.path.join(script_dir, "Manager_preferences", "preferences.json")

def list_scripts(script_dir):
    return [f for f in os.listdir(script_dir) if f.endswith(".py")]

def load_metadata(script_dir):
    metadata_path = get_metadata_path(script_dir)
    if os.path.exists(metadata_path):
        with open(metadata_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_metadata(script_dir, data):
    metadata_path = get_metadata_path(script_dir)
    os.makedirs(os.path.dirname(metadata_path), exist_ok=True)
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

class ScriptManagerPreferences(AddonPreferences):
    bl_idname = __package__

    script_dir: StringProperty(
        name="Scripts Folder Path",
        subtype='DIR_PATH',
        default=""
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "script_dir")

class ScriptItem(PropertyGroup):
    name: StringProperty()
    path: StringProperty()
    favorite: BoolProperty(default=False)
    tags: StringProperty(default='')
    custom_display_name: StringProperty(default='')
    edit_mode: BoolProperty(default=False)

class SCRIPT_OT_RunScript(Operator):
    bl_idname = "script_manager.run_script"
    bl_label = "Run Script"
    bl_description = "Run the selected Python script."

    path: StringProperty()

    def execute(self, context):
        filename = os.path.basename(self.path)

        try:
            text = bpy.data.texts.load(self.path)
        except RuntimeError:
            text = bpy.data.texts.get(filename)

        if not text:
            self.report({'ERROR'}, f"Failed to load script: {filename}")
            return {'CANCELLED'}

        area = context.area
        old_type = area.type

        try:
            area.type = 'TEXT_EDITOR'
            area.spaces.active.text = text
            bpy.ops.text.run_script()
            bpy.data.texts.remove(text)
            self.report({'INFO'}, f"Executed: {filename}")
        except Exception as e:
            self.report({'ERROR'}, f"Execution error: {e}")
        finally:
            area.type = old_type

        return {'FINISHED'}

class SCRIPT_OT_OpenScript(Operator):
    bl_idname = "script_manager.open_script"
    bl_label = "Open in Text Editor"
    bl_description = "Open the script in Blender's text editor."

    path: StringProperty()

    def execute(self, context):
        filename = os.path.basename(self.path)
        try:
            text = bpy.data.texts.load(self.path)
        except RuntimeError:
            text = bpy.data.texts.get(filename)
        for area in context.window.screen.areas:
            if area.type == 'TEXT_EDITOR':
                area.spaces.active.text = text
                self.report({'INFO'}, f"Opened {filename} in Text Editor")
                return {'FINISHED'}
        self.report({'INFO'}, "No Text Editor found. Please open one manually.")
        return {'FINISHED'}

class SCRIPT_OT_ToggleFavorite(Operator):
    bl_idname = "script_manager.toggle_favorite"
    bl_label = "Toggle Favorite"
    bl_description = "Add or remove this script from favorites."

    script_name: StringProperty()

    def execute(self, context):
        wm = context.window_manager
        script_dir = context.preferences.addons[__package__].preferences.script_dir
        metadata = load_metadata(script_dir)
        for item in wm.script_list:
            if item.name == self.script_name:
                item.favorite = not item.favorite
                metadata[item.name] = {
                    "favorite": item.favorite,
                    "tags": item.tags,
                    "custom_display_name": item.custom_display_name
                }
                state = "added to" if item.favorite else "removed from"
                self.report({'INFO'}, f"{item.name} {state} favorites.")
                break
        save_metadata(script_dir, metadata)
        return {'FINISHED'}

class SCRIPT_OT_ToggleEditMode(Operator):
    bl_idname = "script_manager.toggle_edit_mode"
    bl_label = "Toggle Edit Mode"
    bl_description = "Toggle metadata editing for this script."

    script_name: StringProperty()

    def execute(self, context):
        wm = context.window_manager
        for item in wm.script_list:
            if item.name == self.script_name:
                item.edit_mode = not item.edit_mode
                mode = "enabled" if item.edit_mode else "disabled"
                self.report({'INFO'}, f"Edit mode {mode} for {item.name}")
                break
        return {'FINISHED'}

class SCRIPT_OT_SaveMetadata(Operator):
    bl_idname = "script_manager.save_metadata"
    bl_label = "Save Metadata"
    bl_description = "Save tags and display name for this script."

    script_name: StringProperty()

    def execute(self, context):
        wm = context.window_manager
        script_dir = context.preferences.addons[__package__].preferences.script_dir
        metadata = load_metadata(script_dir)
        for item in wm.script_list:
            if item.name == self.script_name:
                metadata[item.name] = {
                    "favorite": item.favorite,
                    "tags": item.tags,
                    "custom_display_name": item.custom_display_name
                }
                item.edit_mode = False
                self.report({'INFO'}, f"Metadata saved for {item.name}")
                break
        save_metadata(script_dir, metadata)
        return {'FINISHED'}

class SCRIPT_OT_RefreshList(Operator):
    bl_idname = "script_manager.refresh_list"
    bl_label = "Refresh List"
    bl_description = "Refresh the list of available scripts."

    def execute(self, context):
        wm = context.window_manager
        prefs = context.preferences.addons[__package__].preferences
        script_dir = prefs.script_dir
        if not os.path.isdir(script_dir):
            self.report({'ERROR'}, "Invalid Scripts Folder Path in Addon Preferences.")
            return {'CANCELLED'}

        wm.script_list.clear()
        metadata = load_metadata(script_dir)
        for fname in list_scripts(script_dir):
            item = wm.script_list.add()
            item.name = fname
            item.path = os.path.join(script_dir, fname)
            item.favorite = metadata.get(fname, {}).get("favorite", False)
            item.tags = metadata.get(fname, {}).get("tags", "")
            item.custom_display_name = metadata.get(fname, {}).get("custom_display_name", "")
        self.report({'INFO'}, "Script list refreshed.")
        return {'FINISHED'}

class SCRIPT_OT_OpenScriptFolder(Operator):
    bl_idname = "script_manager.open_script_folder"
    bl_label = "Open Scripts Folder"
    bl_description = "Open the scripts folder in your file explorer."

    def execute(self, context):
        script_dir = context.preferences.addons[__package__].preferences.script_dir
        if os.path.isdir(script_dir):
            os.startfile(script_dir)
            self.report({'INFO'}, "Scripts folder opened.")
        else:
            self.report({'ERROR'}, "Invalid Scripts Folder Path.")
        return {'FINISHED'}

class SCRIPT_PT_ScriptManagerPanel(Panel):
    bl_label = "Script Manager"
    bl_idname = "SCRIPT_PT_script_manager"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Script Manager'

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager

        row = layout.row()
        row.operator("script_manager.refresh_list", icon='FILE_REFRESH', text="Refresh List")
        row.operator("script_manager.open_script_folder", icon='FILE_FOLDER', text="Open Scripts Folder")

        row = layout.row()
        row.prop(wm, "filter_tags", text="Tags")
        row.prop(wm, "show_favorites_only", toggle=True, text="Favorites", icon='SOLO_ON')

        for item in wm.script_list:
            if wm.show_favorites_only and not item.favorite:
                continue
            if wm.filter_tags.strip() and wm.filter_tags.lower() not in item.tags.lower():
                continue
            box = layout.box()
            row = box.row()
            display_name = item.custom_display_name if item.custom_display_name.strip() else item.name
            row.label(text=display_name, icon='SCRIPT')
            run = row.operator("script_manager.run_script", text="", icon='PLAY')
            run.path = item.path
            edit = row.operator("script_manager.open_script", text="", icon='TEXT')
            edit.path = item.path
            fav = row.operator("script_manager.toggle_favorite", text="", icon='SOLO_ON' if item.favorite else 'SOLO_OFF')
            fav.script_name = item.name
            toggle = row.operator("script_manager.toggle_edit_mode", text="", icon='GREASEPENCIL')
            toggle.script_name = item.name

            if item.edit_mode:
                box.prop(item, "custom_display_name", text="Display Name")
                box.prop(item, "tags", text="Tags")
                save = box.operator("script_manager.save_metadata", text="Save")
                save.script_name = item.name
            else:
                if item.tags.strip():
                    row = box.row()
                    row.label(text=f"Tags: {item.tags}")

classes = (
    ScriptManagerPreferences,
    ScriptItem,
    SCRIPT_OT_RunScript,
    SCRIPT_OT_OpenScript,
    SCRIPT_OT_ToggleFavorite,
    SCRIPT_OT_ToggleEditMode,
    SCRIPT_OT_SaveMetadata,
    SCRIPT_OT_RefreshList,
    SCRIPT_OT_OpenScriptFolder,
    SCRIPT_PT_ScriptManagerPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.script_list = CollectionProperty(type=ScriptItem)
    bpy.types.WindowManager.show_favorites_only = BoolProperty(name="Favorites Only", default=False)
    bpy.types.WindowManager.filter_tags = StringProperty(name="Tag Filter", default="")

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.WindowManager.script_list
    del bpy.types.WindowManager.show_favorites_only
    del bpy.types.WindowManager.filter_tags

if __name__ == "__main__":
    register()
