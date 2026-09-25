"""PropertyGroups and WindowManager-level UI state.

The folder/script/category lists live on the WindowManager: they are a scan
cache, not user data. Everything the user edits (favorites, tags, display
names, the tag registry) persists to metadata.json inside each library.
"""

import functools

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


def _active_folder_update(self, context):
    # The tag list depends on the selected folder scope.
    from . import scanner
    scanner.build_categories(context)


def _category_name_update(self, context):
    # Fired by double-click renaming a tag row in the UIList.
    from . import scanner
    if scanner.is_building() or self.kind != 'TAG':
        return
    # Rebuilding the category list from inside its own item's update callback
    # is unsafe, so the rename is applied on the next timer tick.
    bpy.app.timers.register(
        functools.partial(scanner.apply_tag_rename, self.value, self.name),
        first_interval=0.0,
    )


class SMP_ScriptItem(PropertyGroup):
    name: StringProperty()                     # file name, e.g. "rename_bones.py"
    root: StringProperty(subtype='DIR_PATH')   # library root this script belongs to
    rel_key: StringProperty()                  # metadata key inside its root
    rel_dir: StringProperty()                  # "" for root level, else "rigging/utils"
    path: StringProperty(subtype='FILE_PATH')  # absolute path on disk
    display_name: StringProperty()
    tags: StringProperty()
    favorite: BoolProperty(default=False)

    def ui_label(self):
        return self.display_name.strip() or self.name


class SMP_FolderItem(PropertyGroup):
    """One row of the folder (library) list: All Folders or a configured root."""
    name: StringProperty()   # shown in the UI
    kind: StringProperty()   # 'ALL' or 'DIR'
    value: StringProperty()  # library root path for 'DIR'
    count: IntProperty(default=0)


class SMP_CategoryItem(PropertyGroup):
    """One row of the tag list: All / Favorites / a tag / Untagged."""
    name: StringProperty(update=_category_name_update)  # shown in the UI; editable for tags
    kind: StringProperty()   # 'ALL', 'FAV', 'TAG', 'UNTAGGED'
    value: StringProperty()  # casefolded tag for 'TAG'
    count: IntProperty(default=0)


_classes = (SMP_ScriptItem, SMP_FolderItem, SMP_CategoryItem)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    wm = bpy.types.WindowManager
    wm.smp_scripts = CollectionProperty(type=SMP_ScriptItem)
    wm.smp_folders = CollectionProperty(type=SMP_FolderItem)
    wm.smp_categories = CollectionProperty(type=SMP_CategoryItem)
    wm.smp_active_folder = IntProperty(default=0, update=_active_folder_update)
    wm.smp_active_category = IntProperty(default=0)
    wm.smp_active_script = IntProperty(default=0)
    wm.smp_search_folders = StringProperty(
        name="Search Folders",
        description="Filter the folder list",
        default="",
        options={'TEXTEDIT_UPDATE'},
    )
    wm.smp_search_tags = StringProperty(
        name="Search Tags",
        description="Filter the tag list",
        default="",
        options={'TEXTEDIT_UPDATE'},
    )
    wm.smp_search_scripts = StringProperty(
        name="Search Scripts",
        description="Filter by file name, display name, tag or subfolder",
        default="",
        options={'TEXTEDIT_UPDATE'},
    )


def unregister():
    for attr in (
        "smp_scripts",
        "smp_folders",
        "smp_categories",
        "smp_active_folder",
        "smp_active_category",
        "smp_active_script",
        "smp_search_folders",
        "smp_search_tags",
        "smp_search_scripts",
    ):
        try:
            delattr(bpy.types.WindowManager, attr)
        except AttributeError:
            pass
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
