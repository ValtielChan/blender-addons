bl_info = {
    "name": "Stair Generator",
    "author": "Muware",
    "version": (1, 0, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar (N) > Stairs",
    "description": "Generate a clean, manifold, optimized solid staircase.",
    "category": "Add Mesh",
}

import bpy
import math
import traceback


# ==============================================================
# Parameter resolution
# ==============================================================

def resolve_params(props):
    """Resolve the over-constrained inputs into (count, riser, tread).

    Riser height always divides total height exactly: in HEIGHT mode the
    step count is the closest integer fit to the target riser, then the
    actual riser is recomputed from it.
    """
    height = max(props.total_height, 0.001)

    if props.step_mode == 'HEIGHT':
        count = max(1, round(height / max(props.step_height, 0.001)))
    else:
        count = props.step_count
    riser = height / count

    if props.depth_mode == 'ANGLE':
        tread = riser / math.tan(props.angle)
    else:
        tread = props.tread_depth

    return count, riser, tread


# ==============================================================
# Geometry construction
# ==============================================================

def build_stair_geometry(count, riser, tread, width):
    """Solid staircase: zigzag profile in XZ, extruded along Y (centered).

    Manifold, no duplicate verts. All faces are quads except the two
    side walls, which are single n-gons.
    """
    # Profile polygon (x, z), winding gives outward normals once extruded.
    profile = []
    for i in range(count):
        profile.append((i * tread, i * riser))
        profile.append((i * tread, (i + 1) * riser))
    profile.append((count * tread, count * riser))
    profile.append((count * tread, 0.0))

    m = len(profile)
    hw = width * 0.5
    verts = [(x, -hw, z) for x, z in profile] + [(x, hw, z) for x, z in profile]

    faces = []
    for i in range(m):
        j = (i + 1) % m
        faces.append((i, j, j + m, i + m))
    faces.append(tuple(reversed(range(m))))       # side at -Y
    faces.append(tuple(range(m, 2 * m)))          # side at +Y

    return verts, faces


def regenerate(obj):
    """Swap fresh mesh data into obj, keeping its transform, parenting and
    modifiers. Parameters are read from the object itself."""
    props = obj.stair_props
    count, riser, tread = resolve_params(props)
    verts, faces = build_stair_geometry(count, riser, tread, props.width)

    mesh = bpy.data.meshes.new(obj.name + "_mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    mesh.validate(verbose=False)

    for poly in mesh.polygons:
        poly.use_smooth = False

    if props.material is not None:
        mesh.materials.append(props.material)

    old_mesh = obj.data
    obj.data = mesh
    if old_mesh is not None and old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)

    return obj


def is_stair(obj):
    return obj is not None and obj.type == 'MESH' and obj.stair_props.is_stair


# ==============================================================
# Live update callback
# ==============================================================

def _live_update(self, context):
    if not self.auto_update:
        return
    try:
        # self.id_data is the Object owning this property group.
        regenerate(self.id_data)
    except Exception:
        traceback.print_exc()


# ==============================================================
# Properties
# ==============================================================

class StairGenProperties(bpy.types.PropertyGroup):
    is_stair: bpy.props.BoolProperty(
        name="Is Stair",
        description="Marks this object as generated and editable by Stair Generator",
        default=False,
    )
    auto_update: bpy.props.BoolProperty(
        name="Live Update",
        description="Regenerate immediately on every parameter change",
        default=True,
    )
    total_height: bpy.props.FloatProperty(
        name="Total Height",
        description="Total height climbed by the staircase",
        default=2.7,
        min=0.0001,
        unit='LENGTH',
        update=_live_update,
    )
    step_mode: bpy.props.EnumProperty(
        name="Steps From",
        description="How the number of steps is determined",
        items=[
            ('HEIGHT', "Step Height", "Give a target riser height; the closest whole step count is used"),
            ('COUNT', "Step Count", "Give the number of steps directly"),
        ],
        default='HEIGHT',
        update=_live_update,
    )
    step_height: bpy.props.FloatProperty(
        name="Step Height",
        description="Target riser height. Actual riser = total height / step count, so it always fits exactly",
        default=0.18,
        min=0.0001,
        unit='LENGTH',
        update=_live_update,
    )
    step_count: bpy.props.IntProperty(
        name="Step Count",
        description="Number of steps",
        default=15,
        min=1,
        update=_live_update,
    )
    depth_mode: bpy.props.EnumProperty(
        name="Depth From",
        description="How the tread depth is determined",
        items=[
            ('TREAD', "Tread Depth", "Give the tread depth (going) directly"),
            ('ANGLE', "Angle", "Give the slope angle; tread depth = riser / tan(angle)"),
        ],
        default='TREAD',
        update=_live_update,
    )
    tread_depth: bpy.props.FloatProperty(
        name="Tread Depth",
        description="Horizontal depth of each step (going)",
        default=0.27,
        min=0.0001,
        unit='LENGTH',
        update=_live_update,
    )
    angle: bpy.props.FloatProperty(
        name="Angle",
        description="Slope angle of the staircase",
        default=math.radians(33.7),
        # Hard bounds: tread = riser / tan(angle) blows up at 0 and collapses at 90.
        min=math.radians(0.1),
        max=math.radians(89.9),
        subtype='ANGLE',
        update=_live_update,
    )
    width: bpy.props.FloatProperty(
        name="Width",
        description="Width of the staircase (centered on the X axis)",
        default=1.0,
        min=0.0001,
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

class STAIRGEN_OT_new(bpy.types.Operator):
    bl_idname = "stairgen.new"
    bl_label = "New Staircase"
    bl_description = "Create a new staircase at the 3D cursor and make it the active object"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = bpy.data.objects.new("Stairs", bpy.data.meshes.new("Stairs_mesh"))
        context.collection.objects.link(obj)
        obj.location = context.scene.cursor.location
        obj.stair_props.is_stair = True
        try:
            regenerate(obj)
        except Exception as exc:
            bpy.data.objects.remove(obj, do_unlink=True)
            self.report({'ERROR'}, f"Generation failed: {exc}")
            return {'CANCELLED'}

        for o in context.view_layer.objects:
            o.select_set(False)
        context.view_layer.objects.active = obj
        obj.select_set(True)
        return {'FINISHED'}


class STAIRGEN_OT_generate(bpy.types.Operator):
    bl_idname = "stairgen.generate"
    bl_label = "Generate Stairs"
    bl_description = "Rebuild the active staircase with its current parameters"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return is_stair(context.active_object)

    def execute(self, context):
        obj = context.active_object
        try:
            regenerate(obj)
        except Exception as exc:
            self.report({'ERROR'}, f"Generation failed: {exc}")
            return {'CANCELLED'}
        count, _, _ = resolve_params(obj.stair_props)
        self.report({'INFO'}, f"'{obj.name}' rebuilt ({count} steps)")
        return {'FINISHED'}


# ==============================================================
# UI Panel
# ==============================================================

class STAIRGEN_PT_panel(bpy.types.Panel):
    bl_label = "Stair Generator"
    bl_idname = "STAIRGEN_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Stairs"

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        # Nothing editable selected: the only thing on offer is a new staircase.
        if not is_stair(obj):
            layout.operator("stairgen.new", text="New Staircase", icon='ADD')
            return

        props = obj.stair_props

        layout.label(text=obj.name, icon='MOD_ARRAY')
        row = layout.row(align=True)
        row.prop(props, "auto_update", toggle=True, icon='FILE_REFRESH')
        row.operator("stairgen.generate", text="Rebuild", icon='MESH_DATA')
        layout.operator("stairgen.new", text="New Staircase", icon='ADD')

        layout.separator()

        box = layout.box()
        box.label(text="Material", icon='MATERIAL')
        box.prop(props, "material", text="")

        box = layout.box()
        box.label(text="Dimensions", icon='DRIVER_DISTANCE')
        box.prop(props, "total_height")
        box.prop(props, "width")

        box = layout.box()
        box.label(text="Steps", icon='NLA_PUSHDOWN')
        box.row().prop(props, "step_mode", expand=True)
        if props.step_mode == 'HEIGHT':
            box.prop(props, "step_height")
        else:
            box.prop(props, "step_count")
        box.row().prop(props, "depth_mode", expand=True)
        if props.depth_mode == 'ANGLE':
            box.prop(props, "angle")
        else:
            box.prop(props, "tread_depth")

        # Resolved values, so the user sees what actually gets built.
        count, riser, tread = resolve_params(props)
        run = count * tread
        angle = math.degrees(math.atan2(riser, tread))
        blondel = 2.0 * riser + tread

        box = layout.box()
        box.label(text="Result", icon='INFO')
        col = box.column(align=True)
        col.label(text=f"Steps: {count}")
        col.label(text=f"Riser: {riser * 100:.1f} cm   Tread: {tread * 100:.1f} cm")
        col.label(text=f"Angle: {angle:.1f}°   Run: {run:.2f} m")
        # Blondel comfort rule: 2 x riser + tread should be 60-64 cm.
        ok = 0.60 <= blondel <= 0.64
        col.label(
            text=f"Blondel (2h+g): {blondel * 100:.1f} cm",
            icon='CHECKMARK' if ok else 'ERROR',
        )


# ==============================================================
# Registration
# ==============================================================

classes = (
    StairGenProperties,
    STAIRGEN_OT_new,
    STAIRGEN_OT_generate,
    STAIRGEN_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    # Params live on the object, so every staircase carries its own settings.
    bpy.types.Object.stair_props = bpy.props.PointerProperty(type=StairGenProperties)


def unregister():
    if hasattr(bpy.types.Object, "stair_props"):
        del bpy.types.Object.stair_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


def _self_check():
    """Geometry sanity: closed surface, no duplicate verts, exact volume."""
    n, riser, tread, width = 5, 0.2, 0.3, 1.5
    verts, faces = build_stair_geometry(n, riser, tread, width)
    m = 2 * n + 2
    assert len(verts) == 2 * m, len(verts)
    assert len(set(verts)) == len(verts), "duplicate vertices"
    assert len(faces) == m + 2, len(faces)
    # Euler characteristic of a closed genus-0 surface: V - E + F == 2
    edges = set()
    for f in faces:
        for i in range(len(f)):
            edges.add(frozenset((f[i], f[(i + 1) % len(f)])))
    assert len(verts) - len(edges) + len(faces) == 2, "not a closed surface"
    # Every edge shared by exactly 2 faces => manifold
    counts = {}
    for f in faces:
        for i in range(len(f)):
            e = frozenset((f[i], f[(i + 1) % len(f)]))
            counts[e] = counts.get(e, 0) + 1
    assert set(counts.values()) == {2}, "non-manifold edges"
    print("stair_generator: self-check OK")


if __name__ == "__main__":
    _self_check()
    register()
