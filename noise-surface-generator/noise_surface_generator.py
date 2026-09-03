bl_info = {
    "name": "Noise Surface Generator",
    "author": "Valtiel",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar (N) > Noise Surface",
    "description": "Generate a surface with real-time tweakable Perlin noise, then freeze the result",
    "category": "Add Mesh",
}

import bpy
import bmesh
import math
import mathutils
from mathutils import noise
from bpy.props import (
    FloatProperty,
    IntProperty,
    BoolProperty,
    FloatVectorProperty,
    PointerProperty,
)
from bpy.types import Panel, Operator, PropertyGroup


# ============================================================
# NOISE
# ============================================================
def fbm(x, y, octaves, lacunarity, persistence):
    """Fractal Brownian Motion on top of Blender's native Perlin noise (flat mode)."""
    total = 0.0
    amplitude = 1.0
    freq = 1.0
    max_amp = 0.0
    for _ in range(octaves):
        n = noise.noise(mathutils.Vector((x * freq, y * freq, 0.0)))  # [-1, 1]
        total += n * amplitude
        max_amp += amplitude
        amplitude *= persistence
        freq *= lacunarity
    return total / max_amp if max_amp > 0 else 0.0


# Constant: radius of the circles used for toroidal sampling.
# A small value keeps the noise readable; arbitrary but consistent.
_TORUS_R = 1.0 / (2.0 * math.pi)


def fbm_seamless(u, v, reps, octaves, lacunarity, persistence, ox, oy):
    """Tileable fBm.

    u, v are normalized coordinates in [0, 1] over the surface. They are
    wrapped onto two circles (a 4D torus): since a circle closes on itself,
    the noise is identical at u=0 and u=1 (same for v), so the surface
    repeats seamlessly. 'reps' = number of pattern repeats across the width;
    it MUST be a whole number for the tiling to stay valid.
    """
    total = 0.0
    amplitude = 1.0
    freq = 1.0
    max_amp = 0.0

    angle_u = u * 2.0 * math.pi
    angle_v = v * 2.0 * math.pi

    for _ in range(octaves):
        r = _TORUS_R * reps * freq
        # 4 coordinates: each axis wrapped onto its own circle
        nx = ox + r * math.cos(angle_u)
        ny = oy + r * math.sin(angle_u)
        nz = r * math.cos(angle_v)
        nw = r * math.sin(angle_v)
        # mathutils.noise is 3D only: combine two offset samples to
        # approximate the 4th dimension cleanly.
        n1 = noise.noise(mathutils.Vector((nx, ny, nz)))
        n2 = noise.noise(mathutils.Vector((nz, nw, nx)))
        n = (n1 + n2) * 0.5
        total += n * amplitude
        max_amp += amplitude
        amplitude *= persistence
        freq *= lacunarity
    return total / max_amp if max_amp > 0 else 0.0


def rebuild_surface(obj):
    """Rebuild the mesh geometry from the properties stored on the object."""
    if obj is None or obj.type != 'MESH':
        return
    p = obj.noise_surface
    mesh = obj.data

    bm = bmesh.new()
    segs = max(1, p.subdivisions)
    sx, sy = p.size_x, p.size_y
    ox, oy = p.seed_offset[0], p.seed_offset[1]

    raw = []
    coords = [[None] * (segs + 1) for _ in range(segs + 1)]

    for i in range(segs + 1):
        for j in range(segs + 1):
            u = i / segs
            v = j / segs
            px = (u - 0.5) * sx
            py = (v - 0.5) * sy
            if p.seamless:
                h = fbm_seamless(
                    u, v, p.repetitions,
                    p.octaves, p.lacunarity, p.persistence,
                    ox, oy,
                )
            else:
                nx = (px / p.noise_scale) * p.frequency + ox
                ny = (py / p.noise_scale) * p.frequency + oy
                h = fbm(nx, ny, p.octaves, p.lacunarity, p.persistence)
            raw.append(h)
            coords[i][j] = (px, py, h)

    hmin, hmax = min(raw), max(raw)
    span = (hmax - hmin) if (hmax - hmin) != 0 else 1.0
    tmin, tmax = p.height_min, p.height_max

    bverts = [[None] * (segs + 1) for _ in range(segs + 1)]
    for i in range(segs + 1):
        for j in range(segs + 1):
            px, py, h = coords[i][j]
            z = tmin + ((h - hmin) / span) * (tmax - tmin)
            bverts[i][j] = bm.verts.new((px, py, z))

    bm.verts.ensure_lookup_table()

    for i in range(segs):
        for j in range(segs):
            bm.faces.new((
                bverts[i][j],
                bverts[i + 1][j],
                bverts[i + 1][j + 1],
                bverts[i][j + 1],
            ))

    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()

    for poly in mesh.polygons:
        poly.use_smooth = True
    mesh.update()


# ============================================================
# LIVE CALLBACK
# ============================================================
def update_callback(self, context):
    """Called on every slider change while live update is on."""
    obj = context.active_object
    if obj is None or obj.type != 'MESH':
        return
    if not obj.noise_surface.is_noise_surface:
        return
    if not obj.noise_surface.live_update:
        return
    rebuild_surface(obj)


# ============================================================
# PROPERTIES STORED ON THE OBJECT
# ============================================================
class NoiseSurfaceProps(PropertyGroup):
    is_noise_surface: BoolProperty(default=False)
    live_update: BoolProperty(
        name="Live Update",
        default=True,
        update=update_callback,
    )

    size_x: FloatProperty(name="Size X", default=10.0, min=0.1, update=update_callback)
    size_y: FloatProperty(name="Size Y", default=10.0, min=0.1, update=update_callback)
    subdivisions: IntProperty(name="Subdivisions", default=100, min=1, max=1000, update=update_callback)

    noise_scale: FloatProperty(name="Scale", default=2.0, min=0.001, update=update_callback)
    frequency: FloatProperty(name="Frequency", default=1.0, min=0.0, update=update_callback)
    octaves: IntProperty(name="Octaves", default=4, min=1, max=12, update=update_callback)
    lacunarity: FloatProperty(name="Lacunarity", default=2.0, min=0.0, update=update_callback)
    persistence: FloatProperty(name="Persistence", default=0.5, min=0.0, max=1.0, update=update_callback)

    seamless: BoolProperty(
        name="Seamless (tileable)",
        description="The surface repeats seamlessly on both horizontal axes",
        default=False,
        update=update_callback,
    )
    repetitions: IntProperty(
        name="Repetitions",
        description="Number of pattern repeats across the width (must be a whole number for tiling). Replaces frequency in seamless mode",
        default=2, min=1, max=64,
        update=update_callback,
    )

    height_min: FloatProperty(name="Height Min", default=0.0, update=update_callback)
    height_max: FloatProperty(name="Height Max", default=2.0, update=update_callback)

    seed_offset: FloatVectorProperty(name="Seed (offset)", size=2, default=(0.0, 0.0), update=update_callback)


# ============================================================
# OPERATORS
# ============================================================
class NOISESURF_OT_create(Operator):
    bl_idname = "noise_surface.create"
    bl_label = "New Noise Surface"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mesh = bpy.data.meshes.new("NoiseSurface_mesh")
        obj = bpy.data.objects.new("NoiseSurface", mesh)
        context.collection.objects.link(obj)
        obj.noise_surface.is_noise_surface = True
        obj.location = context.scene.cursor.location
        rebuild_surface(obj)

        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {'FINISHED'}


class NOISESURF_OT_regenerate(Operator):
    bl_idname = "noise_surface.regenerate"
    bl_label = "Regenerate"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rebuild_surface(context.active_object)
        return {'FINISHED'}


class NOISESURF_OT_freeze(Operator):
    bl_idname = "noise_surface.freeze"
    bl_label = "Freeze Surface"
    bl_description = "Lock the result: turns off live update and drops the marker, the surface becomes a plain mesh"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj and obj.noise_surface.is_noise_surface:
            obj.noise_surface.live_update = False
            obj.noise_surface.is_noise_surface = False
            self.report({'INFO'}, "Surface frozen: it is now a standard mesh.")
        return {'FINISHED'}


# ============================================================
# UI PANEL
# ============================================================
class NOISESURF_PT_panel(Panel):
    bl_label = "Noise Surface"
    bl_idname = "NOISESURF_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Noise Surface"

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        layout.operator("noise_surface.create", icon='MESH_GRID')

        if obj is None or obj.type != 'MESH' or not obj.noise_surface.is_noise_surface:
            layout.label(text="Select a noise surface")
            layout.label(text="or create a new one.")
            return

        p = obj.noise_surface

        row = layout.row()
        row.prop(p, "live_update", toggle=True, icon='PLAY' if p.live_update else 'PAUSE')
        if not p.live_update:
            row.operator("noise_surface.regenerate", text="", icon='FILE_REFRESH')

        box = layout.box()
        box.label(text="Mesh", icon='MESH_DATA')
        box.prop(p, "size_x")
        box.prop(p, "size_y")
        box.prop(p, "subdivisions")

        box = layout.box()
        box.label(text="Noise", icon='FORCE_TURBULENCE')
        box.prop(p, "seamless", toggle=True, icon='UV_SYNC_SELECT')
        if p.seamless:
            box.prop(p, "repetitions")
        else:
            box.prop(p, "noise_scale")
            box.prop(p, "frequency")
        box.prop(p, "octaves")
        box.prop(p, "lacunarity")
        box.prop(p, "persistence")
        box.prop(p, "seed_offset")

        box = layout.box()
        box.label(text="Height", icon='ARROW_LEFTRIGHT')
        box.prop(p, "height_min")
        box.prop(p, "height_max")

        layout.separator()
        layout.operator("noise_surface.freeze", icon='LOCKED')


# ============================================================
# REGISTRATION
# ============================================================
classes = (
    NoiseSurfaceProps,
    NOISESURF_OT_create,
    NOISESURF_OT_regenerate,
    NOISESURF_OT_freeze,
    NOISESURF_PT_panel,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Object.noise_surface = PointerProperty(type=NoiseSurfaceProps)


def unregister():
    del bpy.types.Object.noise_surface
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
