bl_info = {
    "name": "Noise Surface Generator",
    "author": "Fabien",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar (N) > Noise Surface",
    "description": "Genere une surface avec bruit de Perlin parametrable en temps reel, puis fige le resultat",
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
# CALCUL DU BRUIT
# ============================================================
def fbm(x, y, octaves, lacunarity, persistence):
    """Fractal Brownian Motion base sur le Perlin natif de Blender (mode plat)."""
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


# Constante : rayon des cercles pour l'echantillonnage torique.
# Une valeur faible garde le bruit lisible ; elle est arbitraire mais coherente.
_TORUS_R = 1.0 / (2.0 * math.pi)


def fbm_seamless(u, v, reps, octaves, lacunarity, persistence, ox, oy):
    """FBM tileable.

    u, v sont des coordonnees normalisees dans [0, 1] sur la surface.
    On les enroule sur deux cercles (un tore en 4D) : comme un cercle se
    referme, le bruit est identique a u=0 et u=1 (idem pour v), donc la
    surface se repete sans couture. 'reps' = nombre de repetitions du motif
    sur la largeur ; il DOIT etre entier pour que le tiling reste valide.
    """
    total = 0.0
    amplitude = 1.0
    freq = 1.0
    max_amp = 0.0

    angle_u = u * 2.0 * math.pi
    angle_v = v * 2.0 * math.pi

    for _ in range(octaves):
        r = _TORUS_R * reps * freq
        # 4 coordonnees : les deux axes enroules chacun sur un cercle
        nx = ox + r * math.cos(angle_u)
        ny = oy + r * math.sin(angle_u)
        nz = r * math.cos(angle_v)
        nw = r * math.sin(angle_v)
        # mathutils.noise ne fait que de la 3D : on combine deux echantillons
        # decales pour approximer la 4e dimension proprement.
        n1 = noise.noise(mathutils.Vector((nx, ny, nz)))
        n2 = noise.noise(mathutils.Vector((nz, nw, nx)))
        n = (n1 + n2) * 0.5
        total += n * amplitude
        max_amp += amplitude
        amplitude *= persistence
        freq *= lacunarity
    return total / max_amp if max_amp > 0 else 0.0


def rebuild_surface(obj):
    """Reconstruit la geometrie du mesh a partir des proprietes stockees sur l'objet."""
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
# CALLBACK LIVE
# ============================================================
def update_callback(self, context):
    """Appele a chaque modification d'un slider quand le live est actif."""
    obj = context.active_object
    if obj is None or obj.type != 'MESH':
        return
    if not obj.noise_surface.is_noise_surface:
        return
    if not obj.noise_surface.live_update:
        return
    rebuild_surface(obj)


# ============================================================
# PROPRIETES STOCKEES SUR L'OBJET
# ============================================================
class NoiseSurfaceProps(PropertyGroup):
    is_noise_surface: BoolProperty(default=False)
    live_update: BoolProperty(
        name="Mise a jour live",
        default=True,
        update=update_callback,
    )

    size_x: FloatProperty(name="Taille X", default=10.0, min=0.1, update=update_callback)
    size_y: FloatProperty(name="Taille Y", default=10.0, min=0.1, update=update_callback)
    subdivisions: IntProperty(name="Subdivisions", default=100, min=1, max=1000, update=update_callback)

    noise_scale: FloatProperty(name="Echelle", default=2.0, min=0.001, update=update_callback)
    frequency: FloatProperty(name="Frequence", default=1.0, min=0.0, update=update_callback)
    octaves: IntProperty(name="Octaves", default=4, min=1, max=12, update=update_callback)
    lacunarity: FloatProperty(name="Lacunarite", default=2.0, min=0.0, update=update_callback)
    persistence: FloatProperty(name="Persistance", default=0.5, min=0.0, max=1.0, update=update_callback)

    seamless: BoolProperty(
        name="Seamless (tileable)",
        description="La surface se repete sans couture sur les deux axes horizontaux",
        default=False,
        update=update_callback,
    )
    repetitions: IntProperty(
        name="Repetitions",
        description="Nombre de repetitions du motif sur la largeur (doit etre entier pour le tiling). Remplace la frequence en mode seamless",
        default=2, min=1, max=64,
        update=update_callback,
    )

    height_min: FloatProperty(name="Hauteur min", default=0.0, update=update_callback)
    height_max: FloatProperty(name="Hauteur max", default=2.0, update=update_callback)

    seed_offset: FloatVectorProperty(name="Seed (offset)", size=2, default=(0.0, 0.0), update=update_callback)


# ============================================================
# OPERATEURS
# ============================================================
class NOISESURF_OT_create(Operator):
    bl_idname = "noise_surface.create"
    bl_label = "Creer une surface de bruit"
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
    bl_label = "Regenerer"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rebuild_surface(context.active_object)
        return {'FINISHED'}


class NOISESURF_OT_freeze(Operator):
    bl_idname = "noise_surface.freeze"
    bl_label = "Figer la surface"
    bl_description = "Verrouille le resultat : desactive le live et retire le marqueur, la surface devient un mesh normal"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj and obj.noise_surface.is_noise_surface:
            obj.noise_surface.live_update = False
            obj.noise_surface.is_noise_surface = False
            self.report({'INFO'}, "Surface figee : c'est maintenant un mesh standard.")
        return {'FINISHED'}


# ============================================================
# PANNEAU UI
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
            layout.label(text="Selectionne une surface de bruit")
            layout.label(text="ou cree-en une.")
            return

        p = obj.noise_surface

        row = layout.row()
        row.prop(p, "live_update", toggle=True, icon='PLAY' if p.live_update else 'PAUSE')
        if not p.live_update:
            row.operator("noise_surface.regenerate", text="", icon='FILE_REFRESH')

        box = layout.box()
        box.label(text="Maillage", icon='MESH_DATA')
        box.prop(p, "size_x")
        box.prop(p, "size_y")
        box.prop(p, "subdivisions")

        box = layout.box()
        box.label(text="Bruit", icon='FORCE_TURBULENCE')
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
        box.label(text="Hauteur", icon='ARROW_LEFTRIGHT')
        box.prop(p, "height_min")
        box.prop(p, "height_max")

        layout.separator()
        layout.operator("noise_surface.freeze", icon='LOCKED')


# ============================================================
# ENREGISTREMENT
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
