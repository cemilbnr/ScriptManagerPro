"""Sidebar panels for the 3D Viewport and the Text Editor.

Layout: a main "Script Manager" panel with the tools row, plus collapsible
child panels — Folders (only when more than one library is configured),
Tags and Scripts — each with its own search field above its list.
"""

import os

import bpy
from bpy.types import Panel, UIList

from . import scanner, utils

CATEGORY_ICONS = {
    'ALL': 'OUTLINER_COLLECTION',
    'FAV': 'SOLO_ON',
    'TAG': 'BOOKMARKS',
    'UNTAGGED': 'FILE_BLANK',
}


def _matches(item, query):
    return (
        query in item.name.lower()
        or query in item.display_name.lower()
        or query in item.tags.lower()
        or query in item.rel_dir.lower()
    )


def _count_label(row, count):
    sub = row.row(align=True)
    sub.alignment = 'RIGHT'
    sub.active = False
    sub.label(text=str(count))


class SMP_UL_folders(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.name, icon='OUTLINER_COLLECTION' if item.kind == 'ALL' else 'FILE_FOLDER')
        _count_label(row, item.count)

    def draw_filter(self, context, layout):
        pass  # filtered by the search field above the list

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        query = context.window_manager.smp_search_folders.strip().lower()
        if not query:
            return [], []
        flags = [
            self.bitflag_filter_item if (item.kind == 'ALL' or query in item.name.lower()) else 0
            for item in items
        ]
        return flags, []


class SMP_UL_categories(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        if item.kind == 'TAG':
            # Editable prop: double-click renames the tag everywhere in scope.
            row.prop(item, "name", text="", emboss=False, icon='BOOKMARKS')
        else:
            row.label(text=item.name, icon=CATEGORY_ICONS.get(item.kind, 'BOOKMARKS'))
        _count_label(row, item.count)

    def draw_filter(self, context, layout):
        pass  # filtered by the search field above the list

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        query = context.window_manager.smp_search_tags.strip().lower()
        if not query:
            return [], []
        flags = [
            self.bitflag_filter_item if query in item.name.lower() else 0
            for item in items
        ]
        return flags, []


class SMP_UL_scripts(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        fav = row.operator(
            "smp.toggle_favorite", text="", emboss=False,
            icon='SOLO_ON' if item.favorite else 'SOLO_OFF',
        )
        fav.path = item.path
        row.label(text=item.ui_label(), icon='FILE_SCRIPT')
        ops = row.row(align=True)
        ops.operator("smp.run_script", text="", emboss=False, icon='PLAY').path = item.path
        ops.operator("smp.open_in_editor", text="", emboss=False, icon='TEXT').path = item.path
        ops.operator("smp.edit_script_meta", text="", emboss=False, icon='PREFERENCES').path = item.path

    def draw_filter(self, context, layout):
        pass  # filtered by the search field above the list

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        wm = context.window_manager
        cat = scanner.active_category(wm)
        query = wm.smp_search_scripts.strip().lower()
        flags = []
        for item in items:
            visible = scanner.in_scope(wm, item)
            if visible and cat is not None and not scanner.category_matches(cat, item):
                visible = False
            if visible and query and not _matches(item, query):
                visible = False
            flags.append(self.bitflag_filter_item if visible else 0)
        return flags, []


def _draw_tools(layout, context):
    wm = context.window_manager
    box = layout.box()
    row = box.row(align=True)
    row.operator("smp.refresh", text="Refresh", icon='FILE_REFRESH')
    dirs = utils.get_script_dirs(context)
    # Empty path = let the operator decide: single folder opens directly,
    # multiple folders require a selection in the Folders panel.
    row.operator("smp.open_folder", text="", icon='FILE_FOLDER').path = scanner.scope_root(wm)
    row.operator("preferences.addon_show", text="", icon='PREFERENCES').module = utils.ADDON_ID

    if not dirs:
        prefs = utils.get_prefs(context)
        col = box.column(align=True)
        col.label(text="Add your script folder(s):", icon='INFO')
        if prefs is not None:
            for i, entry in enumerate(prefs.script_dirs):
                row = col.row(align=True)
                row.prop(entry, "path", text="")
                row.operator("smp.remove_script_dir", text="", icon='X').index = i
            col.operator("smp.add_script_dir", text="Add Folder", icon='ADD')


def _draw_folders(layout, context):
    wm = context.window_manager
    layout.prop(wm, "smp_search_folders", text="", icon='VIEWZOOM')
    layout.template_list(
        "SMP_UL_folders", "smp_folders",
        wm, "smp_folders", wm, "smp_active_folder",
        rows=3, maxrows=8,
    )


def _draw_tags(layout, context):
    wm = context.window_manager
    layout.prop(wm, "smp_search_tags", text="", icon='VIEWZOOM')
    row = layout.row()
    row.template_list(
        "SMP_UL_categories", "smp_categories",
        wm, "smp_categories", wm, "smp_active_category",
        rows=4, maxrows=10,
    )
    side = row.column(align=True)
    side.operator("smp.add_tag", text="", icon='ADD')
    cat = scanner.active_category(wm)
    sub = side.column(align=True)
    sub.enabled = bool(cat is not None and cat.kind == 'TAG')
    sub.operator("smp.remove_tag", text="", icon='REMOVE')


def _draw_scripts(layout, context):
    wm = context.window_manager
    layout.prop(wm, "smp_search_scripts", text="", icon='VIEWZOOM')
    if len(wm.smp_scripts) == 0:
        layout.label(text="No scripts found — press Refresh", icon='INFO')
        return
    layout.template_list(
        "SMP_UL_scripts", "smp_scripts",
        wm, "smp_scripts", wm, "smp_active_script",
        rows=8, maxrows=16,
    )


def _draw_active_script_box(layout, context):
    space = context.space_data
    text = space.text if space else None
    box = layout.box()
    if text is None:
        box.label(text="No text open", icon='TEXT')
        box.operator("text.new", text="New Script", icon='ADD')
        return
    suffix = "  (unsaved)" if text.is_dirty else ""
    box.label(text=f"{text.name}{suffix}", icon='FILE_SCRIPT')
    if text.filepath:
        row = box.row(align=True)
        row.operator("smp.save_script", text="Update & Save", icon='FILE_TICK')
        row.operator("smp.save_and_run", text="", icon='PLAY')
        row.operator("smp.reload_script", text="", icon='FILE_REFRESH')
        row.operator("smp.close_script", text="", icon='X')
    else:
        row = box.row(align=True)
        row.operator("smp.save_as_script", text="Save as .py...", icon='FILE_TICK')
        row.operator("smp.close_script", text="", icon='X')


def _has_dirs(context):
    return bool(utils.get_script_dirs(context))


def _multiple_dirs_configured(context):
    prefs = utils.get_prefs(context)
    if prefs is None:
        return False
    return len([e for e in prefs.script_dirs if e.path.strip()]) > 1


class _SidebarMixin:
    bl_region_type = 'UI'
    bl_category = "Script Manager"


class SMP_PT_view3d_main(_SidebarMixin, Panel):
    bl_label = "Script Manager"
    bl_idname = "SMP_PT_view3d_main"
    bl_space_type = 'VIEW_3D'

    def draw(self, context):
        _draw_tools(self.layout, context)


class SMP_PT_text_main(_SidebarMixin, Panel):
    bl_label = "Script Manager"
    bl_idname = "SMP_PT_text_main"
    bl_space_type = 'TEXT_EDITOR'

    def draw(self, context):
        _draw_active_script_box(self.layout, context)
        _draw_tools(self.layout, context)


class _FoldersPanelMixin(_SidebarMixin):
    bl_label = "Folders"

    @classmethod
    def poll(cls, context):
        return _multiple_dirs_configured(context)

    def draw(self, context):
        _draw_folders(self.layout, context)


class _TagsPanelMixin(_SidebarMixin):
    bl_label = "Tags"

    @classmethod
    def poll(cls, context):
        return _has_dirs(context)

    def draw(self, context):
        _draw_tags(self.layout, context)


class _ScriptsPanelMixin(_SidebarMixin):
    bl_label = "Scripts"

    @classmethod
    def poll(cls, context):
        return _has_dirs(context)

    def draw(self, context):
        _draw_scripts(self.layout, context)


class SMP_PT_view3d_folders(_FoldersPanelMixin, Panel):
    bl_idname = "SMP_PT_view3d_folders"
    bl_space_type = 'VIEW_3D'
    bl_parent_id = "SMP_PT_view3d_main"


class SMP_PT_view3d_tags(_TagsPanelMixin, Panel):
    bl_idname = "SMP_PT_view3d_tags"
    bl_space_type = 'VIEW_3D'
    bl_parent_id = "SMP_PT_view3d_main"


class SMP_PT_view3d_scripts(_ScriptsPanelMixin, Panel):
    bl_idname = "SMP_PT_view3d_scripts"
    bl_space_type = 'VIEW_3D'
    bl_parent_id = "SMP_PT_view3d_main"


class SMP_PT_text_folders(_FoldersPanelMixin, Panel):
    bl_idname = "SMP_PT_text_folders"
    bl_space_type = 'TEXT_EDITOR'
    bl_parent_id = "SMP_PT_text_main"


class SMP_PT_text_tags(_TagsPanelMixin, Panel):
    bl_idname = "SMP_PT_text_tags"
    bl_space_type = 'TEXT_EDITOR'
    bl_parent_id = "SMP_PT_text_main"


class SMP_PT_text_scripts(_ScriptsPanelMixin, Panel):
    bl_idname = "SMP_PT_text_scripts"
    bl_space_type = 'TEXT_EDITOR'
    bl_parent_id = "SMP_PT_text_main"


_classes = (
    SMP_UL_folders,
    SMP_UL_categories,
    SMP_UL_scripts,
    SMP_PT_view3d_main,
    SMP_PT_view3d_folders,
    SMP_PT_view3d_tags,
    SMP_PT_view3d_scripts,
    SMP_PT_text_main,
    SMP_PT_text_folders,
    SMP_PT_text_tags,
    SMP_PT_text_scripts,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
