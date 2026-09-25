"""Add-on preferences: multiple script folders + backup settings."""

import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, StringProperty
from bpy.types import AddonPreferences, PropertyGroup

from . import utils


class SMP_ScriptDirItem(PropertyGroup):
    # No update callback on purpose: the disk is only touched when the user
    # presses Refresh, never while typing a path or on startup.
    path: StringProperty(
        name="Path",
        description="Root folder of a .py script library (scanned recursively when you press Refresh)",
        subtype='DIR_PATH',
        default="",
    )


class SMP_AddonPreferences(AddonPreferences):
    bl_idname = utils.ADDON_ID

    script_dirs: CollectionProperty(type=SMP_ScriptDirItem)
    # Legacy v1.x single folder; migrated into script_dirs on the next scan.
    script_dir: StringProperty(options={'HIDDEN'}, default="")
    backup_on_save: BoolProperty(
        name="Backup on Save",
        description=(
            "Before Update & Save overwrites a file, copy the old version to "
            ".script_manager/backups/ inside its library"
        ),
        default=True,
    )
    backup_keep: IntProperty(
        name="Keep Backups",
        description="How many backups to keep per script",
        default=10,
        min=1,
        max=100,
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text="Script Folders:", icon='FILE_FOLDER')
        col = layout.column(align=True)
        for i, entry in enumerate(self.script_dirs):
            row = col.row(align=True)
            row.prop(entry, "path", text="")
            row.operator("smp.remove_script_dir", text="", icon='X').index = i
        col.operator("smp.add_script_dir", text="Add Folder", icon='ADD')

        box = layout.box()
        box.use_property_split = True
        box.prop(self, "backup_on_save")
        row = box.row()
        row.enabled = self.backup_on_save
        row.prop(self, "backup_keep")
        box.label(
            text="Metadata and backups live in <folder>/.script_manager/ of each library",
            icon='INFO',
        )


_classes = (SMP_ScriptDirItem, SMP_AddonPreferences)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
