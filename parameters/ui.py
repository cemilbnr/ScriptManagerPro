"""Parameters child panel for the selected script, plus the preferences box."""

import bpy
from bpy.types import Panel

from .. import utils
from ..ui import _SidebarMixin
from . import operators, properties


def _active_script(wm):
    if 0 <= wm.smp_active_script < len(wm.smp_scripts):
        return wm.smp_scripts[wm.smp_active_script]
    return None


def _draw_params(layout, context):
    wm = context.window_manager
    item = _active_script(wm)
    pset = properties.find_param_set(wm, item.path)

    header = layout.row(align=True)
    header.label(text=item.ui_label(), icon='FILE_SCRIPT')
    if pset is None:
        # Nothing is read from disk until the user asks for it.
        layout.operator("smp.params_load", text="Load Parameters", icon='PRESET').path = item.path
        return
    header.operator("smp.params_load", text="", icon='FILE_REFRESH').path = item.path
    reset_all = header.operator("smp.params_reset", text="", icon='LOOP_BACK')
    reset_all.path = item.path
    reset_all.param_name = ""
    header.operator("smp.params_save", text="", icon='CHECKMARK').path = item.path
    prefs = utils.get_prefs(context)
    show_descriptions = prefs is None or prefs.show_param_descriptions
    if prefs is not None:
        header.prop(prefs, "show_param_descriptions", text="", icon='INFO')

    for line in pset.error.split("\n"):
        if line:
            row = layout.row()
            row.alert = True
            row.label(text=line, icon='ERROR')

    if not len(pset.params):
        layout.label(text="No @PARAM parameters in this script", icon='INFO')
        return

    col = layout.column()
    for param in pset.params:
        if not param.is_valid:
            row = col.row()
            row.alert = True
            row.label(text=f"{param.name} (line {param.line}): {param.error}", icon='ERROR')
            continue

        row = col.row(align=True)
        row.prop(param, properties.VALUE_PROP[param.param_type], text=param.name)
        if properties.is_modified(param):
            single = row.operator("smp.params_reset", text="", icon='LOOP_BACK')
            single.path = item.path
            single.param_name = param.name
        else:
            row.label(text="", icon='BLANK1')

        if param.warning:
            sub = col.row()
            sub.active = False
            sub.label(text=param.warning, icon='ERROR')
        if param.description and show_descriptions:
            sub = col.row()
            sub.active = False
            sub.label(text=param.description)

    count = len(properties.collect_overrides(pset))
    if count:
        sub = layout.row()
        sub.active = False
        sub.label(text=f"{count} override(s) applied when run", icon='PLAY')


def draw_preferences(layout, prefs):
    box = layout.box()
    box.prop(prefs, "enable_parameters")
    if not prefs.enable_parameters:
        return
    col = box.column(align=True)
    col.label(text="Mark a module level variable to edit it in the Parameters panel:", icon='INFO')
    col.label(text="    # @PARAM")
    col.label(text="    copies = 3")
    col.label(text="Only str, int, float and bool values can be exported.")
    col.label(text="Runs with edited values use a temporary copy in <folder>/.script_manager/temp/")


class _ParamsPanelMixin(_SidebarMixin):
    bl_label = "Parameters"

    @classmethod
    def poll(cls, context):
        return operators.is_enabled(context) and _active_script(context.window_manager) is not None

    def draw(self, context):
        _draw_params(self.layout, context)


class SMP_PT_view3d_params(_ParamsPanelMixin, Panel):
    bl_idname = "SMP_PT_view3d_params"
    bl_space_type = 'VIEW_3D'
    bl_parent_id = "SMP_PT_view3d_main"


class SMP_PT_text_params(_ParamsPanelMixin, Panel):
    bl_idname = "SMP_PT_text_params"
    bl_space_type = 'TEXT_EDITOR'
    bl_parent_id = "SMP_PT_text_main"


_classes = (SMP_PT_view3d_params, SMP_PT_text_params)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
