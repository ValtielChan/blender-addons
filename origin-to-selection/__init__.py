"""Origin to Selection

Put the active object's origin (pivot point) at the center of the current
selection in mesh edit mode, without moving the geometry.

Internally the operator replays the usual manual sequence: save the 3D
cursor, snap the cursor to the selection, switch to object mode, "origin to
cursor", back to edit mode, restore the cursor. The user only has one
shortcut to press.

SHORTCUT: Ctrl + Alt + C, in mesh edit mode (see _register_keymaps).
Also in the edit-mode right-click context menu.
To change it: Preferences > Keymap, search for "Origin to Selection".
"""

import bpy
import bmesh


class OBJECT_OT_origin_to_selection(bpy.types.Operator):
    """Put the object origin at the center of the selection"""

    bl_idname = "object.origin_to_selection"
    bl_label = "Origin to Selection"
    bl_description = (
        "Put the object origin at the center of the selection "
        "(edit mode), without moving the geometry. Shortcut: Ctrl+Alt+C"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == 'MESH'
            and context.mode == 'EDIT_MESH'
        )

    def execute(self, context):
        obj = context.active_object

        # Make sure something is actually selected.
        bm = bmesh.from_edit_mesh(obj.data)
        if not any(v.select for v in bm.verts):
            self.report({'WARNING'}, "Nothing selected: nothing to do")
            return {'CANCELLED'}

        cursor = context.scene.cursor
        prev_cursor_loc = cursor.location.copy()
        prev_cursor_rot = cursor.rotation_euler.copy()

        # Remember the object selection so only the active object is touched.
        prev_selected = list(context.selected_objects)
        active = context.view_layer.objects.active

        try:
            # 1. 3D cursor to the center of the selection.
            bpy.ops.view3d.snap_cursor_to_selected()

            # 2. Switch to object mode, isolating the active object.
            bpy.ops.object.mode_set(mode='OBJECT')
            for o in prev_selected:
                o.select_set(False)
            active.select_set(True)
            context.view_layer.objects.active = active

            # 3. Origin to cursor.
            bpy.ops.object.origin_set(type='ORIGIN_CURSOR')

        finally:
            # 4. Restore the object selection.
            for o in prev_selected:
                o.select_set(True)
            if active is not None:
                active.select_set(True)
                context.view_layer.objects.active = active

            # 5. Back to edit mode.
            if context.mode != 'EDIT_MESH':
                bpy.ops.object.mode_set(mode='EDIT')

            # 6. Restore the 3D cursor.
            cursor.location = prev_cursor_loc
            cursor.rotation_euler = prev_cursor_rot

        self.report({'INFO'}, "Origin moved to the selection")
        return {'FINISHED'}


def _menu_func(self, context):
    self.layout.operator(
        OBJECT_OT_origin_to_selection.bl_idname,
        text="Origin to Selection",
        icon='PIVOT_CURSOR',
    )


addon_keymaps = []


def _register_keymaps():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc is None:
        # Background mode: no user keyconfig.
        return
    # Ctrl+Alt+C in mesh edit mode. Also documented in the module docstring,
    # the bl_description and the README.
    km = kc.keymaps.new(name='Mesh', space_type='EMPTY')
    kmi = km.keymap_items.new(
        OBJECT_OT_origin_to_selection.bl_idname,
        type='C',
        value='PRESS',
        ctrl=True,
        alt=True,
    )
    addon_keymaps.append((km, kmi))


def _unregister_keymaps():
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()


def register():
    bpy.utils.register_class(OBJECT_OT_origin_to_selection)
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.append(_menu_func)
    _register_keymaps()


def unregister():
    _unregister_keymaps()
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(_menu_func)
    bpy.utils.unregister_class(OBJECT_OT_origin_to_selection)


if __name__ == "__main__":
    register()
