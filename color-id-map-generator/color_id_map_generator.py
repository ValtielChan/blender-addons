bl_info = {
    "name": "Color ID Map Generator",
    "author": "Muware",
    "version": (1, 1, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > Color ID",
    "description": "Bake a per-material Color ID map texture from UV islands with per-face hue variation",
    "category": "UV",
}

import bpy
import bmesh
import colorsys
import os
from bpy.props import IntProperty, StringProperty, FloatVectorProperty, BoolProperty, EnumProperty
from bpy.types import Operator, Panel, PropertyGroup


# ============================================================
# Helpers
# ============================================================

_MAT_ENUM_CACHE = []  # prevents string GC issues with EnumProperty callbacks


def _material_enum_items(self, context):
    global _MAT_ENUM_CACHE
    items = []
    obj = context.active_object
    if obj and obj.type == 'MESH' and obj.material_slots:
        for i, slot in enumerate(obj.material_slots):
            name = slot.material.name if slot.material else "(empty)"
            items.append((str(i), f"{i}: {name}", "", i))
    if not items:
        items = [('0', "(no materials)", "", 0)]
    _MAT_ENUM_CACHE = items
    return items


def _sanitize_filename_chunk(s):
    return "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in s)


def _build_output_path(base_path, suffix):
    p = bpy.path.abspath(base_path)
    root, ext = os.path.splitext(p)
    if not ext:
        ext = '.png'
    return f"{root}_{_sanitize_filename_chunk(suffix)}{ext}"


# ============================================================
# UV islands + color computation
# ============================================================

def detect_uv_islands(bm, uv_layer, allowed_face_indices, threshold=1e-5):
    """Group allowed faces into UV islands via union-find on shared UV edges."""
    allowed = set(allowed_face_indices)
    parent = {idx: idx for idx in allowed}

    def find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for edge in bm.edges:
        linked = [f for f in edge.link_faces if f.index in allowed]
        if len(linked) < 2:
            continue
        v1, v2 = edge.verts
        face_uvs = []
        for f in linked:
            uv_a, uv_b = None, None
            for loop in f.loops:
                if loop.vert == v1:
                    uv_a = loop[uv_layer].uv.copy()
                elif loop.vert == v2:
                    uv_b = loop[uv_layer].uv.copy()
            face_uvs.append((f, uv_a, uv_b))

        for i in range(len(face_uvs)):
            for j in range(i + 1, len(face_uvs)):
                f1, a1, b1 = face_uvs[i]
                f2, a2, b2 = face_uvs[j]
                if None in (a1, b1, a2, b2):
                    continue
                if (a1 - a2).length < threshold and (b1 - b2).length < threshold:
                    union(f1.index, f2.index)

    groups = {}
    for idx in allowed:
        groups.setdefault(find(idx), []).append(idx)

    islands = list(groups.values())
    for isl in islands:
        isl.sort()
    islands.sort(key=lambda i: (-len(i), i[0]))
    return islands


def bit_reverse_permutation(j, n):
    if n <= 1:
        return 0
    bits = max(1, (n - 1).bit_length())
    x, rev = j, 0
    for _ in range(bits):
        rev = (rev << 1) | (x & 1)
        x >>= 1
    return rev % n


def compute_face_colors(islands, hue_offset=0.0,
                        sat_range=(0.70, 1.00), val_range=(0.45, 1.00)):
    golden = 0.61803398875
    face_colors = {}
    for i, island in enumerate(islands):
        hue = (i * golden + hue_offset) % 1.0
        n = len(island)
        for j, fidx in enumerate(island):
            if n == 1:
                sat, val = sat_range[1], val_range[1]
            else:
                k = bit_reverse_permutation(j, n)
                t = k / max(n - 1, 1)
                val = val_range[0] + t * (val_range[1] - val_range[0])
                sat = sat_range[1] - (1.0 - t) * (sat_range[1] - sat_range[0]) * 0.6
            r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
            face_colors[fidx] = (r, g, b, 1.0)
    return face_colors


# ============================================================
# Core bake routine (single material slot)
# ============================================================

def bake_color_id_for_slot(context, obj, material_index, image_size, output_path,
                           bg_color=(0.0, 0.0, 0.0, 1.0), attr_name="ColorIDMap",
                           hue_offset=0.0):
    if obj.type != 'MESH':
        raise RuntimeError("The active object is not a mesh.")
    if not obj.data.uv_layers:
        raise RuntimeError("The mesh has no UV map.")
    if material_index >= len(obj.material_slots):
        raise RuntimeError(f"Material slot {material_index} does not exist.")

    target_indices = [p.index for p in obj.data.polygons if p.material_index == material_index]
    if not target_indices:
        raise RuntimeError(f"Slot {material_index} contains no faces.")

    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    # 1. UV islands restricted to this material's faces
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active
    islands = detect_uv_islands(bm, uv_layer, allowed_face_indices=target_indices)
    bm.free()

    # 2. Per-face colors
    face_colors = compute_face_colors(islands, hue_offset=hue_offset)

    # 3. Color Attribute on the ORIGINAL mesh (accumulate: only update target faces)
    color_attr = obj.data.color_attributes.get(attr_name)
    if color_attr is None or color_attr.domain != 'CORNER' or color_attr.data_type != 'FLOAT_COLOR':
        if color_attr is not None:
            obj.data.color_attributes.remove(color_attr)
        color_attr = obj.data.color_attributes.new(name=attr_name, type='FLOAT_COLOR', domain='CORNER')

    target_set = set(target_indices)
    for poly in obj.data.polygons:
        if poly.index in target_set:
            color = face_colors.get(poly.index, (1.0, 1.0, 1.0, 1.0))
            for loop_idx in poly.loop_indices:
                color_attr.data[loop_idx].color = color

    obj.data.color_attributes.active_color = color_attr
    try:
        obj.data.color_attributes.render_color_index = list(obj.data.color_attributes).index(color_attr)
    except Exception:
        pass

    # 4. Duplicate object for clean bake, strip non-target faces from the dupe
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    context.view_layer.objects.active = obj
    bpy.ops.object.duplicate(linked=False)
    dupe = context.active_object
    dupe.name = f"_TempBake_{obj.name}_mat{material_index}"

    # Save scene state
    scene = context.scene
    prev_engine = scene.render.engine
    prev_samples = scene.cycles.samples if hasattr(scene, 'cycles') else 64
    prev_vt = scene.view_settings.view_transform
    prev_look = scene.view_settings.look
    prev_clear = scene.render.bake.use_clear
    prev_margin = scene.render.bake.margin
    prev_margin_type = scene.render.bake.margin_type
    prev_sel_to_act = scene.render.bake.use_selected_to_active

    temp_mat = None
    image = None

    try:
        # 5. Remove non-target faces from the dupe
        bpy.ops.object.mode_set(mode='EDIT')
        bm_edit = bmesh.from_edit_mesh(dupe.data)
        bm_edit.faces.ensure_lookup_table()
        to_delete = [f for f in bm_edit.faces if f.material_index != material_index]
        if to_delete:
            bmesh.ops.delete(bm_edit, geom=to_delete, context='FACES')
        bmesh.update_edit_mesh(dupe.data)
        bpy.ops.object.mode_set(mode='OBJECT')

        # 6. Target image
        slot = obj.material_slots[material_index]
        mat_name_safe = slot.material.name if slot.material else f"empty{material_index}"
        img_name = f"{obj.name}_{mat_name_safe}_ColorIDMap"
        if img_name in bpy.data.images:
            bpy.data.images.remove(bpy.data.images[img_name])
        image = bpy.data.images.new(img_name, image_size, image_size, alpha=True)
        image.filepath_raw = bpy.path.abspath(output_path)
        image.file_format = 'PNG'
        # Background fill
        image.pixels = list(bg_color) * (image_size * image_size)

        # 7. Temp emit material
        temp_mat = bpy.data.materials.new(name="_TempColorIDBake")
        temp_mat.use_nodes = True
        nt = temp_mat.node_tree
        nt.nodes.clear()

        n_attr = nt.nodes.new('ShaderNodeAttribute')
        n_attr.attribute_name = attr_name
        n_attr.location = (-600, 0)

        n_emit = nt.nodes.new('ShaderNodeEmission')
        n_emit.location = (-300, 0)

        n_out = nt.nodes.new('ShaderNodeOutputMaterial')
        n_out.location = (0, 0)

        n_img = nt.nodes.new('ShaderNodeTexImage')
        n_img.image = image
        n_img.location = (-600, -300)
        n_img.select = True
        nt.nodes.active = n_img

        nt.links.new(n_attr.outputs['Color'], n_emit.inputs['Color'])
        nt.links.new(n_emit.outputs['Emission'], n_out.inputs['Surface'])

        # 8. Replace all materials on dupe with the temp emit material
        dupe.data.materials.clear()
        dupe.data.materials.append(temp_mat)

        # 9. Bake config
        scene.render.engine = 'CYCLES'
        scene.cycles.samples = 1
        scene.cycles.bake_type = 'EMIT'
        scene.render.bake.margin = max(4, image_size // 128)
        scene.render.bake.margin_type = 'EXTEND'
        scene.render.bake.use_clear = False
        scene.render.bake.use_selected_to_active = False
        scene.view_settings.view_transform = 'Raw'
        scene.view_settings.look = 'None'

        bpy.ops.object.select_all(action='DESELECT')
        dupe.select_set(True)
        context.view_layer.objects.active = dupe

        # 10. Bake + save
        bpy.ops.object.bake(type='EMIT')
        image.save()

    finally:
        # Cleanup: delete dupe and its mesh data
        dupe_mesh = dupe.data if dupe else None
        if dupe is not None:
            bpy.data.objects.remove(dupe, do_unlink=True)
        if dupe_mesh is not None and dupe_mesh.users == 0:
            bpy.data.meshes.remove(dupe_mesh)
        if temp_mat is not None and temp_mat.users == 0:
            bpy.data.materials.remove(temp_mat)

        # Restore scene state
        scene.render.engine = prev_engine
        if prev_engine == 'CYCLES':
            scene.cycles.samples = prev_samples
        scene.view_settings.view_transform = prev_vt
        scene.view_settings.look = prev_look
        scene.render.bake.use_clear = prev_clear
        scene.render.bake.margin = prev_margin
        scene.render.bake.margin_type = prev_margin_type
        scene.render.bake.use_selected_to_active = prev_sel_to_act

        # Restore selection on original
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj

    return len(islands), len(face_colors), bpy.path.abspath(output_path)


# ============================================================
# Properties
# ============================================================

class ColorIDProperties(PropertyGroup):
    resolution: IntProperty(
        name="Resolution",
        default=2048,
        min=128,
        max=8192,
    )
    output_path: StringProperty(
        name="Output PNG",
        default="//color_id_map.png",
        subtype='FILE_PATH',
        description="Output PNG path. The material name is automatically suffixed before .png",
    )
    bg_color: FloatVectorProperty(
        name="Background",
        subtype='COLOR',
        size=4,
        default=(0.0, 0.0, 0.0, 1.0),
        min=0.0, max=1.0,
    )
    material_slot: EnumProperty(
        name="Material Slot",
        items=_material_enum_items,
        description="Material slot to bake. Only faces using this slot are processed",
    )
    bake_all_materials: BoolProperty(
        name="All Materials",
        default=False,
        description="Bake one Color ID map per material slot, suffixed with material name",
    )


# ============================================================
# Operator
# ============================================================

class COLORID_OT_generate(Operator):
    bl_idname = "colorid.generate"
    bl_label = "Generate Color ID Map"
    bl_description = "Bake a Color ID map for the selected material slot (or all slots)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.color_id_props
        obj = context.active_object

        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "No active mesh object.")
            return {'CANCELLED'}
        if not obj.material_slots:
            self.report({'ERROR'}, "The object has no material slots.")
            return {'CANCELLED'}

        if props.bake_all_materials:
            slot_indices = list(range(len(obj.material_slots)))
        else:
            try:
                slot_indices = [int(props.material_slot)]
            except ValueError:
                self.report({'ERROR'}, "Invalid material slot.")
                return {'CANCELLED'}

        results = []
        warnings = []

        for k, slot_idx in enumerate(slot_indices):
            slot = obj.material_slots[slot_idx]
            mat_name = slot.material.name if slot.material else f"emptyslot{slot_idx}"
            out_path = _build_output_path(props.output_path, mat_name)
            # Offset hues between materials so two different mats don't start from the same color
            hue_offset = (k * 0.137 + 0.073) % 1.0

            try:
                n_isl, n_faces, path = bake_color_id_for_slot(
                    context, obj, slot_idx,
                    image_size=props.resolution,
                    output_path=out_path,
                    bg_color=tuple(props.bg_color),
                    hue_offset=hue_offset,
                )
                results.append((mat_name, n_isl, n_faces, path))
            except Exception as e:
                warnings.append(f"{mat_name}: {e}")
                continue

        for w in warnings:
            self.report({'WARNING'}, w)

        if not results:
            self.report({'ERROR'}, "No bake succeeded.")
            return {'CANCELLED'}

        summary = " | ".join(
            f"{mat}: {n_isl} islands, {n_faces} faces -> {os.path.basename(p)}"
            for mat, n_isl, n_faces, p in results
        )
        self.report({'INFO'}, summary)
        return {'FINISHED'}


# ============================================================
# Panel
# ============================================================

class COLORID_PT_panel(Panel):
    bl_label = "Color ID Map"
    bl_idname = "COLORID_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Color ID"

    def draw(self, context):
        layout = self.layout
        props = context.scene.color_id_props
        obj = context.active_object

        col = layout.column(align=True)
        col.prop(props, "resolution")
        col.prop(props, "output_path")
        col.prop(props, "bg_color")

        layout.separator()

        row = layout.row()
        row.enabled = not props.bake_all_materials
        row.prop(props, "material_slot")

        layout.prop(props, "bake_all_materials")

        layout.separator()
        layout.operator("colorid.generate", icon='RENDER_STILL')

        if obj is None or obj.type != 'MESH':
            layout.label(text="No active mesh.", icon='ERROR')
        elif not obj.material_slots:
            layout.label(text="Active mesh has no materials.", icon='ERROR')


# ============================================================
# Register
# ============================================================

classes = (ColorIDProperties, COLORID_OT_generate, COLORID_PT_panel)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.color_id_props = bpy.props.PointerProperty(type=ColorIDProperties)


def unregister():
    del bpy.types.Scene.color_id_props
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
