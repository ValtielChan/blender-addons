bl_info = {
    "name": "Cube Ring Generator",
    "author": "Muware",
    "version": (1, 1, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar (N) > Cube Ring",
    "description": "Generate a ring of randomly-sized cubes facing inward, with world-space UVs.",
    "category": "Add Mesh",
}

import bpy
import math
import random
import traceback
from mathutils import Vector, Matrix


# ==============================================================
# Geometry construction
# ==============================================================

def build_cube_data(size, texture_scale):
    """Build a cube mesh with size-aware UVs.

    UVs are scaled by (world_size_axis / texture_scale), so a seamless
    tileable texture appears at the same density on every cube
    regardless of its dimensions.
    """
    sx = size[0] * 0.5
    sy = size[1] * 0.5
    sz = size[2] * 0.5

    verts = [
        Vector((-sx, -sy, -sz)),  # 0
        Vector(( sx, -sy, -sz)),  # 1
        Vector(( sx,  sy, -sz)),  # 2
        Vector((-sx,  sy, -sz)),  # 3
        Vector((-sx, -sy,  sz)),  # 4
        Vector(( sx, -sy,  sz)),  # 5
        Vector(( sx,  sy,  sz)),  # 6
        Vector((-sx,  sy,  sz)),  # 7
    ]

    fx = size[0] / texture_scale
    fy = size[1] / texture_scale
    fz = size[2] / texture_scale

    face_data = [
        # -Z bottom
        ([0, 3, 2, 1], [(0.0, 0.0), (0.0, fy), (fx, fy), (fx, 0.0)]),
        # +Z top
        ([4, 5, 6, 7], [(0.0, 0.0), (fx, 0.0), (fx, fy), (0.0, fy)]),
        # -Y front
        ([0, 1, 5, 4], [(0.0, 0.0), (fx, 0.0), (fx, fz), (0.0, fz)]),
        # +Y back
        ([3, 7, 6, 2], [(0.0, 0.0), (0.0, fz), (fx, fz), (fx, 0.0)]),
        # -X left
        ([0, 4, 7, 3], [(0.0, 0.0), (0.0, fz), (fy, fz), (fy, 0.0)]),
        # +X right
        ([1, 2, 6, 5], [(0.0, 0.0), (fy, 0.0), (fy, fz), (0.0, fz)]),
    ]

    return verts, face_data


def generate_ring_geometry(props):
    """Generate the full ring as raw mesh data."""
    rng_angle   = random.Random(props.seed)
    rng_radial  = random.Random(props.seed + 1)
    rng_size    = random.Random(props.seed + 2)
    rng_lateral = random.Random(props.seed + 3)

    all_verts = []
    all_faces = []
    all_uvs = []

    count = max(1, props.count)

    for i in range(count):
        # Angular position with normalized jitter.
        base_angle = (i / count) * 2.0 * math.pi
        jitter_amplitude = (props.spacing_jitter / count) * 2.0 * math.pi
        angle = base_angle + rng_angle.uniform(-jitter_amplitude, jitter_amplitude)

        # Base point on circle.
        circle_pos = Vector((
            math.cos(angle) * props.radius,
            math.sin(angle) * props.radius,
            0.0,
        ))

        # Radial offset.
        radial_dir = Vector((math.cos(angle), math.sin(angle), 0.0))
        radial_amount = rng_radial.uniform(
            props.radial_offset_min,
            props.radial_offset_max,
        )

        # Lateral noise.
        if props.lateral_noise > 0.0:
            lateral = Vector((
                rng_lateral.uniform(-1.0, 1.0),
                rng_lateral.uniform(-1.0, 1.0),
                rng_lateral.uniform(-1.0, 1.0),
            )) * props.lateral_noise
        else:
            lateral = Vector((0.0, 0.0, 0.0))

        position = circle_pos + radial_dir * radial_amount + lateral

        # Random size: uniform (single value) or per-axis (vector).
        if props.uniform_scale:
            s = rng_size.uniform(props.scale_uniform_min, props.scale_uniform_max)
            size = Vector((s, s, s))
            # Burn 2 extra RNG calls so toggling Uniform Scale doesn't
            # shift the downstream RNG sequence.
            rng_size.uniform(0.0, 1.0)
            rng_size.uniform(0.0, 1.0)
        else:
            size = Vector((
                rng_size.uniform(props.scale_min[0], props.scale_max[0]),
                rng_size.uniform(props.scale_min[1], props.scale_max[1]),
                rng_size.uniform(props.scale_min[2], props.scale_max[2]),
            ))

        # Orientation: cube local +X aligned toward world center.
        to_center = Vector((-math.cos(angle), -math.sin(angle), 0.0)).normalized()
        x_axis = to_center
        z_axis = Vector((0.0, 0.0, 1.0))
        y_axis = z_axis.cross(x_axis).normalized()

        rot_matrix = Matrix((
            (x_axis.x, y_axis.x, z_axis.x, 0.0),
            (x_axis.y, y_axis.y, z_axis.y, 0.0),
            (x_axis.z, y_axis.z, z_axis.z, 0.0),
            (0.0,      0.0,      0.0,      1.0),
        ))

        cube_verts, face_data = build_cube_data(size, props.texture_scale)

        offset = len(all_verts)
        for v in cube_verts:
            all_verts.append(rot_matrix @ v + position)

        for face_indices, face_uvs in face_data:
            all_faces.append([offset + idx for idx in face_indices])
            all_uvs.extend(face_uvs)

    return all_verts, all_faces, all_uvs


def create_or_replace_object(props, verts, faces, uvs):
    """Build a fresh mesh-object, replacing any previous object of same name."""
    obj_name = props.object_name or "CubeRing"

    if obj_name in bpy.data.objects:
        old_obj = bpy.data.objects[obj_name]
        old_mesh = old_obj.data
        bpy.data.objects.remove(old_obj, do_unlink=True)
        if old_mesh is not None and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)

    mesh = bpy.data.meshes.new(obj_name + "_mesh")
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    mesh.update()
    mesh.validate(verbose=False)

    uv_layer = mesh.uv_layers.new(name="UVMap")
    for i, uv in enumerate(uvs):
        uv_layer.data[i].uv = uv

    for poly in mesh.polygons:
        poly.use_smooth = False

    if props.material is not None:
        mesh.materials.append(props.material)

    obj = bpy.data.objects.new(obj_name, mesh)
    bpy.context.collection.objects.link(obj)

    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    return obj


def regenerate(props):
    """Run the full pipeline. Used by both the operator and live updates."""
    verts, faces, uvs = generate_ring_geometry(props)
    create_or_replace_object(props, verts, faces, uvs)


# ==============================================================
# Live update callback
# ==============================================================

def _live_update(self, context):
    """Triggered on every property change. Regenerates if auto_update is on."""
    if not self.auto_update:
        return
    try:
        regenerate(self)
    except Exception:
        traceback.print_exc()


# ==============================================================
# Properties
# ==============================================================

class CubeRingProperties(bpy.types.PropertyGroup):
    auto_update: bpy.props.BoolProperty(
        name="Live Update",
        description="Regenerate immediately on every parameter change. Disable for heavy rings",
        default=True,
    )
    object_name: bpy.props.StringProperty(
        name="Name",
        description="Name of the generated object. Re-using the same name overwrites the previous ring",
        default="CubeRing",
        update=_live_update,
    )
    count: bpy.props.IntProperty(
        name="Count",
        description="Number of cubes in the ring",
        default=24,
        min=1,
        soft_max=500,
        max=5000,
        update=_live_update,
    )
    radius: bpy.props.FloatProperty(
        name="Radius",
        description="Radius of the ring (cubes are placed on this circle before any offset)",
        default=2.0,
        min=0.0,
        soft_max=20.0,
        unit='LENGTH',
        update=_live_update,
    )
    spacing_jitter: bpy.props.FloatProperty(
        name="Spacing Jitter",
        description="Random angular shift on each cube. 0 = perfectly uniform, 1 = max chaos",
        default=0.3,
        min=0.0,
        max=1.0,
        update=_live_update,
    )
    radial_offset_min: bpy.props.FloatProperty(
        name="Radial Offset Min",
        description="Minimum outward shift from the circle (negative = inward)",
        default=0.0,
        unit='LENGTH',
        update=_live_update,
    )
    radial_offset_max: bpy.props.FloatProperty(
        name="Radial Offset Max",
        description="Maximum outward shift from the circle",
        default=0.3,
        unit='LENGTH',
        update=_live_update,
    )
    lateral_noise: bpy.props.FloatProperty(
        name="Lateral Noise",
        description="Random offset on all 3 axes",
        default=0.0,
        min=0.0,
        soft_max=1.0,
        unit='LENGTH',
        update=_live_update,
    )
    uniform_scale: bpy.props.BoolProperty(
        name="Uniform Scale",
        description="If on, every cube is a true cube (X = Y = Z). If off, each axis is sampled independently (boxes)",
        default=False,
        update=_live_update,
    )
    scale_uniform_min: bpy.props.FloatProperty(
        name="Min",
        description="Minimum cube edge length (uniform mode)",
        default=0.1,
        min=0.001,
        soft_max=2.0,
        unit='LENGTH',
        update=_live_update,
    )
    scale_uniform_max: bpy.props.FloatProperty(
        name="Max",
        description="Maximum cube edge length (uniform mode)",
        default=0.4,
        min=0.001,
        soft_max=2.0,
        unit='LENGTH',
        update=_live_update,
    )
    scale_min: bpy.props.FloatVectorProperty(
        name="Scale Min",
        description="Minimum cube size on each axis (X, Y, Z)",
        default=(0.1, 0.1, 0.1),
        size=3,
        min=0.001,
        soft_max=2.0,
        subtype='XYZ',
        update=_live_update,
    )
    scale_max: bpy.props.FloatVectorProperty(
        name="Scale Max",
        description="Maximum cube size on each axis (X, Y, Z)",
        default=(0.4, 0.4, 0.4),
        size=3,
        min=0.001,
        soft_max=2.0,
        subtype='XYZ',
        update=_live_update,
    )
    seed: bpy.props.IntProperty(
        name="Seed",
        description="Master random seed",
        default=0,
        update=_live_update,
    )
    texture_scale: bpy.props.FloatProperty(
        name="Texture Scale",
        description="World-space size of one texture tile. Identical density on every cube. Smaller = denser",
        default=1.0,
        min=0.001,
        soft_max=10.0,
        unit='LENGTH',
        update=_live_update,
    )
    material: bpy.props.PointerProperty(
        name="Material",
        type=bpy.types.Material,
        description="Material applied to the generated mesh",
        update=_live_update,
    )


# ==============================================================
# Operators
# ==============================================================

class CUBERING_OT_generate(bpy.types.Operator):
    bl_idname = "cubering.generate"
    bl_label = "Generate Cube Ring"
    bl_description = "Generate or regenerate the ring with current parameters"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.cube_ring_props
        try:
            regenerate(props)
        except Exception as exc:
            self.report({'ERROR'}, f"Generation failed: {exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Ring '{props.object_name}' generated ({props.count} cubes)")
        return {'FINISHED'}


class CUBERING_OT_randomize_seed(bpy.types.Operator):
    bl_idname = "cubering.randomize_seed"
    bl_label = "Randomize Seed"
    bl_description = "Pick a new random seed and regenerate"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.cube_ring_props
        new_seed = random.randint(0, 999999)
        props.seed = new_seed
        # If live update is on, the seed setter already regenerated.
        # Otherwise we still want the dice button to do something visible.
        if not props.auto_update:
            try:
                regenerate(props)
            except Exception as exc:
                self.report({'ERROR'}, f"Generation failed: {exc}")
                return {'CANCELLED'}
        return {'FINISHED'}


# ==============================================================
# UI Panel
# ==============================================================

class CUBERING_PT_panel(bpy.types.Panel):
    bl_label = "Cube Ring Generator"
    bl_idname = "CUBERING_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Cube Ring"

    def draw(self, context):
        layout = self.layout
        props = context.scene.cube_ring_props

        # Live update toggle + manual button
        row = layout.row(align=True)
        row.prop(props, "auto_update", toggle=True, icon='FILE_REFRESH')
        row.operator("cubering.generate", text="Generate", icon='MESH_CUBE')

        layout.separator()

        # Output
        box = layout.box()
        box.label(text="Output", icon='OUTLINER_OB_MESH')
        box.prop(props, "object_name")

        # Layout
        box = layout.box()
        box.label(text="Layout", icon='MOD_ARRAY')
        box.prop(props, "count")
        box.prop(props, "radius")
        box.prop(props, "spacing_jitter", slider=True)

        # Offsets
        box = layout.box()
        box.label(text="Position Offsets", icon='ORIENTATION_NORMAL')
        col = box.column(align=True)
        col.prop(props, "radial_offset_min")
        col.prop(props, "radial_offset_max")
        box.prop(props, "lateral_noise")

        # Cube size
        box = layout.box()
        box.label(text="Cube Size", icon='MOD_SOLIDIFY')
        box.prop(props, "uniform_scale", toggle=True)
        if props.uniform_scale:
            row = box.row(align=True)
            row.prop(props, "scale_uniform_min")
            row.prop(props, "scale_uniform_max")
        else:
            box.prop(props, "scale_min")
            box.prop(props, "scale_max")

        # Randomization
        box = layout.box()
        box.label(text="Randomization", icon='RNDCURVE')
        row = box.row(align=True)
        row.prop(props, "seed")
        row.operator("cubering.randomize_seed", text="", icon='FILE_REFRESH')

        # Material & UV
        box = layout.box()
        box.label(text="Material & UVs", icon='MATERIAL')
        box.prop(props, "material")
        box.prop(props, "texture_scale")
        box.label(text="UVs scale with cube size.", icon='INFO')
        box.label(text="Use seamless tileable textures.")


# ==============================================================
# Registration
# ==============================================================

classes = (
    CubeRingProperties,
    CUBERING_OT_generate,
    CUBERING_OT_randomize_seed,
    CUBERING_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.cube_ring_props = bpy.props.PointerProperty(type=CubeRingProperties)


def unregister():
    if hasattr(bpy.types.Scene, "cube_ring_props"):
        del bpy.types.Scene.cube_ring_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()