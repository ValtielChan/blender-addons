"""Origin to Selection

Place l'origine (point de pivot) de l'objet actif au centre de la
sélection courante en mode édition mesh, sans déplacer la géométrie.

En interne, l'opérateur reproduit l'enchaînement manuel habituel :
sauvegarde du curseur 3D, snap du curseur sur la sélection, passage en
mode objet, "origin to cursor", retour en mode édition, restauration du
curseur. L'utilisateur n'a qu'un seul raccourci à presser.

RACCOURCI : Ctrl + Alt + C, en mode édition mesh (voir _register_keymaps).
Aussi dans le menu contextuel (clic droit) du mode édition.
Pour le changer : Preferences > Keymap, chercher "Origin to Selection".
"""

import bpy
import bmesh


class OBJECT_OT_origin_to_selection(bpy.types.Operator):
    """Placer l'origine de l'objet sur le centre de la sélection"""

    bl_idname = "object.origin_to_selection"
    bl_label = "Origin to Selection"
    bl_description = (
        "Place l'origine de l'objet au centre de la selection "
        "(mode edition), sans deplacer la geometrie. Raccourci : Ctrl+Alt+C"
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

        # Verifier qu'il y a bien une selection.
        bm = bmesh.from_edit_mesh(obj.data)
        if not any(v.select for v in bm.verts):
            self.report({'WARNING'}, "Aucune selection : rien a faire")
            return {'CANCELLED'}

        cursor = context.scene.cursor
        prev_cursor_loc = cursor.location.copy()
        prev_cursor_rot = cursor.rotation_euler.copy()

        # Memoriser la selection d'objets pour ne toucher que l'objet actif.
        prev_selected = list(context.selected_objects)
        active = context.view_layer.objects.active

        try:
            # 1. Curseur 3D au centre de la selection.
            bpy.ops.view3d.snap_cursor_to_selected()

            # 2. Passage en mode objet et isolation de l'objet actif.
            bpy.ops.object.mode_set(mode='OBJECT')
            for o in prev_selected:
                o.select_set(False)
            active.select_set(True)
            context.view_layer.objects.active = active

            # 3. Origine sur le curseur.
            bpy.ops.object.origin_set(type='ORIGIN_CURSOR')

        finally:
            # 4. Restauration de la selection d'objets.
            for o in prev_selected:
                o.select_set(True)
            if active is not None:
                active.select_set(True)
                context.view_layer.objects.active = active

            # 5. Retour en mode edition.
            if context.mode != 'EDIT_MESH':
                bpy.ops.object.mode_set(mode='EDIT')

            # 6. Restauration du curseur 3D.
            cursor.location = prev_cursor_loc
            cursor.rotation_euler = prev_cursor_rot

        self.report({'INFO'}, "Origine placee sur la selection")
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
        # Mode background : pas de keyconfig utilisateur.
        return
    # Ctrl+Alt+C en mode edition mesh. Documente aussi dans le docstring du
    # module, le bl_description et le README.
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
