bl_info = {
    "name": "Blade Profile Generator",
    "author": "Muware",
    "version": (1, 4, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar (N) > Blade",
    "description": "Generate a sword blade from a width profile (markers along the length), with optional fuller and edge grind.",
    "category": "Add Mesh",
}

import bpy
import bmesh
import math
import traceback


# ==============================================================
# Geometry construction
# ==============================================================

def build_blade_geometry(profile, length, thickness, grind=0.0, grind_join=0.0,
                         fuller=None, fuller_segments=8):
    """Build blade mesh data.

    profile: list of (z, width) markers, any order, z in [0, length).
    grind:   edge grind width at the base, measured inward from the edge.
             The grind scales proportionally with the blade width: the
             central flat stays a constant fraction of the width, so a
             narrowing blade keeps a coherent grind. 0 = blunt edge.
    grind_join: if > 0, distance from the base where the grind meets the
             center: the proportional flat is additionally tapered to 0
             at that point (full diamond section beyond). 0 = the flat
             follows the width all the way and joins at the tip.
    fuller:  None, or (start, length, width, depth, fade). The groove is a
             circular arc cut into both faces: the arc (tool) radius is
             derived from width and depth. Over `fade` at both ends the
             depth ramps out; the cut width follows the same arc, which
             gives the rounded end outline of a real fuller.

    The blade runs along +Z, width on X, thickness on Y. Every ring uses
    the same cross-section topology; unused features collapse to
    coincident vertices that are merged afterwards.

    Returns (verts, faces, smooth) where smooth flags the fuller arc faces.
    """
    profile = sorted((z, w) for z, w in profile if 0.0 <= z < length)
    if not profile:
        profile = [(0.0, 0.045)]
    if profile[0][0] > 0.0:
        # No marker at the base: extend the first width flat back to 0.
        profile.insert(0, (0.0, profile[0][1]))

    def width_at(z):
        pts = profile + [(length, 0.0)]
        if z <= pts[0][0]:
            return pts[0][1]
        for (z0, w0), (z1, w1) in zip(pts, pts[1:]):
            if z <= z1:
                f = (z - z0) / (z1 - z0) if z1 > z0 else 1.0
                return w0 + f * (w1 - w0)
        return 0.0

    t = thickness
    ht = t * 0.5
    K = max(2, fuller_segments)

    if fuller:
        f_start, f_len, f_width, f_depth, f_fade = fuller
        f_depth = min(f_depth, t * 0.499)  # both faces must never meet
        f_start = max(0.0, f_start)
        f_end = min(f_start + f_len, length)
        # Floor the fade so ring z positions stay distinct.
        f_fade = max(min(f_fade, (f_end - f_start) * 0.5), 1e-4)
        if f_end <= f_start or f_depth <= 0.0:
            fuller = None
        else:
            hf_full = f_width * 0.5
            f_radius = (hf_full * hf_full + f_depth * f_depth) / (2.0 * f_depth)

    def depth_at(z):
        if not fuller or not (f_start <= z <= f_end):
            return 0.0
        return f_depth * min(1.0, (z - f_start) / f_fade, (f_end - z) / f_fade)

    grind_join = min(grind_join, length)
    hw0 = width_at(0.0) * 0.5
    flat_ratio = max(hw0 - grind, 0.0) / hw0 if hw0 > 0.0 else 0.0

    def flat_at(z, hw):
        flat = flat_ratio * hw  # constant fraction of the local width
        if grind_join > 0.0:
            flat *= max(0.0, 1.0 - z / grind_join)
        return flat

    stations = [z for z, _ in profile]
    if fuller:
        # Sample both ramps densely so the rounded run-out shows.
        for i in range(7):
            stations.append(f_start + f_fade * i / 6.0)
            stations.append(f_end - f_fade * i / 6.0)
    if grind_join > 0.0:
        stations.append(grind_join)
    stations.append(length)  # tip ring, width 0
    stations = sorted(set(round(z, 9) for z in stations if 0.0 <= z <= length))

    verts = []
    rings = []
    for z in stations:
        w = width_at(z)
        d = depth_at(z)
        hw = w * 0.5
        if d > 0.0:
            # Chord half-width of the arc at this depth (round tool ramping out).
            hf = min(math.sqrt(max(2.0 * f_radius * d - d * d, 0.0)), hw)
            arc = []
            for i in range(K + 1):
                x = -hf + 2.0 * hf * i / K
                dep = d - f_radius + math.sqrt(max(f_radius * f_radius - x * x, 0.0))
                arc.append((x, -ht + dep))
        else:
            hf = 0.0
            arc = [(0.0, -ht)] * (K + 1)
        xg = min(max(flat_at(z, hw), hf), hw)  # grind stops at the fuller rim

        i0 = len(verts)
        verts.append((-hw, 0.0, z))                     # left edge
        verts.append((-xg, -ht, z))
        verts += [(x, y, z) for x, y in arc]            # front arc, left→right
        verts.append((xg, -ht, z))
        verts.append((hw, 0.0, z))                      # right edge
        verts.append((xg, ht, z))
        verts += [(-x, -y, z) for x, y in arc]          # back arc, right→left
        verts.append((-xg, ht, z))
        rings.append(i0)

    n = 2 * K + 8
    # Base cap (normal -Z).
    faces = [[rings[0] + k for k in reversed(range(n))]]
    smooth = [False]
    # Side walls between consecutive rings. Degenerate quads from collapsed
    # features (no fuller, grind at center, 0-width tip) are merged away later.
    for r0, r1 in zip(rings, rings[1:]):
        for k in range(n):
            k2 = (k + 1) % n
            faces.append([r0 + k, r0 + k2, r1 + k2, r1 + k])
            smooth.append(2 <= k <= K + 1 or K + 6 <= k <= 2 * K + 5)

    return verts, faces, smooth


def create_or_replace_object(props, verts, faces, smooth):
    obj_name = props.object_name or "Blade"

    if obj_name in bpy.data.objects:
        old_obj = bpy.data.objects[obj_name]
        old_mesh = old_obj.data
        bpy.data.objects.remove(old_obj, do_unlink=True)
        if old_mesh is not None and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)

    mesh = bpy.data.meshes.new(obj_name + "_mesh")
    mesh.from_pydata(verts, [], faces)
    # Smooth-shade the fuller arc faces (flag survives the bmesh cleanup).
    for poly, s in zip(mesh.polygons, smooth):
        poly.use_smooth = s
    mesh.update()
    mesh.validate(verbose=False)

    # Merge the coincident vertices left by collapsed cross-section features.
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-6)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    if props.material is not None:
        mesh.materials.append(props.material)

    obj = bpy.data.objects.new(obj_name, mesh)
    bpy.context.collection.objects.link(obj)

    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(False)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    return obj


def regenerate(props):
    profile = [(m.position, m.width) for m in props.markers]
    fuller = None
    if props.use_fuller:
        fuller = (props.fuller_start, props.fuller_length,
                  props.fuller_width, props.fuller_depth, props.fuller_fade)
    verts, faces, smooth = build_blade_geometry(
        profile, props.length, props.thickness,
        grind=props.grind_width, grind_join=props.grind_join,
        fuller=fuller, fuller_segments=props.fuller_segments,
    )
    create_or_replace_object(props, verts, faces, smooth)


# ==============================================================
# Live update callback
# ==============================================================

def _live_update(self, context):
    props = context.scene.blade_profile_props
    if not props.auto_update:
        return
    try:
        regenerate(props)
    except Exception:
        traceback.print_exc()


# ==============================================================
# Properties
# ==============================================================

class BladeMarker(bpy.types.PropertyGroup):
    position: bpy.props.FloatProperty(
        name="Position",
        description="Distance from the blade base along its length",
        default=0.0,
        min=0.0,
        soft_max=2.0,
        unit='LENGTH',
        update=_live_update,
    )
    width: bpy.props.FloatProperty(
        name="Width",
        description="Blade width at this position",
        default=0.045,
        min=0.0,
        soft_max=0.2,
        unit='LENGTH',
        update=_live_update,
    )


class BladeProfileProperties(bpy.types.PropertyGroup):
    auto_update: bpy.props.BoolProperty(
        name="Live Update",
        description="Regenerate immediately on every parameter change",
        default=True,
    )
    object_name: bpy.props.StringProperty(
        name="Name",
        description="Name of the generated object. Re-using the same name overwrites the previous blade",
        default="Blade",
        update=_live_update,
    )
    length: bpy.props.FloatProperty(
        name="Length",
        description="Total blade length, base to tip",
        default=0.9,
        min=0.01,
        soft_max=2.0,
        unit='LENGTH',
        update=_live_update,
    )
    thickness: bpy.props.FloatProperty(
        name="Thickness",
        description="Blade thickness (constant along the length)",
        default=0.005,
        min=0.0005,
        soft_max=0.05,
        unit='LENGTH',
        update=_live_update,
    )
    grind_width: bpy.props.FloatProperty(
        name="Grind Width",
        description="Edge grind (émouture) width at the base, measured inward "
                    "from the edge. The grind scales proportionally with the "
                    "blade width along the length. 0 = blunt rectangular edge",
        default=0.012,
        min=0.0,
        soft_max=0.1,
        unit='LENGTH',
        update=_live_update,
    )
    grind_join: bpy.props.FloatProperty(
        name="Join At",
        description="Distance from the base where the grind meets the blade "
                    "center (the proportional flat is tapered to 0 there, then "
                    "the section is a full diamond). 0 = joins at the tip",
        default=0.0,
        min=0.0,
        soft_max=2.0,
        unit='LENGTH',
        update=_live_update,
    )
    use_fuller: bpy.props.BoolProperty(
        name="Fuller",
        description="Cut a fuller (groove) into both faces",
        default=False,
        update=_live_update,
    )
    fuller_start: bpy.props.FloatProperty(
        name="Start",
        description="Distance from the base where the fuller starts",
        default=0.0,
        min=0.0,
        soft_max=2.0,
        unit='LENGTH',
        update=_live_update,
    )
    fuller_length: bpy.props.FloatProperty(
        name="Length",
        description="Length of the fuller along the blade",
        default=0.5,
        min=0.01,
        soft_max=2.0,
        unit='LENGTH',
        update=_live_update,
    )
    fuller_width: bpy.props.FloatProperty(
        name="Width",
        description="Width of the fuller (centered on the blade)",
        default=0.012,
        min=0.001,
        soft_max=0.05,
        unit='LENGTH',
        update=_live_update,
    )
    fuller_depth: bpy.props.FloatProperty(
        name="Depth",
        description="Depth of the fuller on each face (clamped below half the thickness)",
        default=0.0015,
        min=0.0001,
        soft_max=0.01,
        unit='LENGTH',
        update=_live_update,
    )
    fuller_fade: bpy.props.FloatProperty(
        name="Fade",
        description="Length of the rounded run-out at both ends of the fuller",
        default=0.02,
        min=0.0,
        soft_max=0.2,
        unit='LENGTH',
        update=_live_update,
    )
    fuller_segments: bpy.props.IntProperty(
        name="Segments",
        description="Resolution of the fuller arc cross-section",
        default=8,
        min=2,
        max=64,
        update=_live_update,
    )
    material: bpy.props.PointerProperty(
        name="Material",
        type=bpy.types.Material,
        description="Material applied to the generated mesh",
        update=_live_update,
    )
    markers: bpy.props.CollectionProperty(type=BladeMarker)


# ==============================================================
# Operators
# ==============================================================

class BLADEGEN_OT_generate(bpy.types.Operator):
    bl_idname = "bladegen.generate"
    bl_label = "Generate Blade"
    bl_description = "Generate or regenerate the blade with current parameters"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.blade_profile_props
        try:
            regenerate(props)
        except Exception as exc:
            self.report({'ERROR'}, f"Generation failed: {exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Blade '{props.object_name}' generated")
        return {'FINISHED'}


class BLADEGEN_OT_add_marker(bpy.types.Operator):
    bl_idname = "bladegen.add_marker"
    bl_label = "Add Marker"
    bl_description = "Add a width marker along the blade"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.blade_profile_props
        marker = props.markers.add()
        if len(props.markers) > 1:
            prev = props.markers[len(props.markers) - 2]
            marker.position = min(prev.position + 0.2, props.length * 0.95)
            marker.width = prev.width
        _live_update(marker, context)
        return {'FINISHED'}


class BLADEGEN_OT_remove_marker(bpy.types.Operator):
    bl_idname = "bladegen.remove_marker"
    bl_label = "Remove Marker"
    bl_description = "Remove this width marker"
    bl_options = {'REGISTER', 'UNDO'}

    index: bpy.props.IntProperty()

    def execute(self, context):
        props = context.scene.blade_profile_props
        if 0 <= self.index < len(props.markers):
            props.markers.remove(self.index)
            _live_update(props, context)
        return {'FINISHED'}


# ==============================================================
# UI Panel
# ==============================================================

class BLADEGEN_PT_panel(bpy.types.Panel):
    bl_label = "Blade Profile Generator"
    bl_idname = "BLADEGEN_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Blade"

    def draw(self, context):
        layout = self.layout
        props = context.scene.blade_profile_props

        row = layout.row(align=True)
        row.prop(props, "auto_update", toggle=True, icon='FILE_REFRESH')
        row.operator("bladegen.generate", text="Generate", icon='MESH_CUBE')

        layout.separator()

        box = layout.box()
        box.label(text="Blade", icon='OUTLINER_OB_MESH')
        box.prop(props, "object_name")
        box.prop(props, "length")
        box.prop(props, "thickness")
        box.prop(props, "material")

        box = layout.box()
        box.label(text="Width Profile", icon='NORMALIZE_FCURVES')
        if not props.markers:
            box.label(text="No markers: default 4.5 cm base.", icon='INFO')
        for i, m in enumerate(props.markers):
            row = box.row(align=True)
            row.prop(m, "position", text="At")
            row.prop(m, "width", text="W")
            op = row.operator("bladegen.remove_marker", text="", icon='X')
            op.index = i
        box.operator("bladegen.add_marker", icon='ADD')
        box.label(text="Tip is always 0 at full length.", icon='INFO')

        box = layout.box()
        box.label(text="Edge Grind (Émouture)", icon='MOD_BEVEL')
        box.prop(props, "grind_width")
        box.prop(props, "grind_join")

        box = layout.box()
        box.prop(props, "use_fuller", icon='ALIGN_JUSTIFY')
        if props.use_fuller:
            col = box.column(align=True)
            col.prop(props, "fuller_start")
            col.prop(props, "fuller_length")
            col.prop(props, "fuller_width")
            col.prop(props, "fuller_depth")
            col.prop(props, "fuller_fade")
            col.prop(props, "fuller_segments")


# ==============================================================
# Registration
# ==============================================================

classes = (
    BladeMarker,
    BladeProfileProperties,
    BLADEGEN_OT_generate,
    BLADEGEN_OT_add_marker,
    BLADEGEN_OT_remove_marker,
    BLADEGEN_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.blade_profile_props = bpy.props.PointerProperty(type=BladeProfileProperties)


def unregister():
    if hasattr(bpy.types.Scene, "blade_profile_props"):
        del bpy.types.Scene.blade_profile_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
