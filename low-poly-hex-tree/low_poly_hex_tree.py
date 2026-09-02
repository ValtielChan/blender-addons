bl_info = {
    "name": "Low Poly Hex Tree",
    "author": "Muware",
    "version": (1, 4, 3),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar (N) > Tree",
    "description": "Procedural low poly tree with curving sections and box projected UVs",
    "category": "Add Mesh",
}

import math
import random

import bpy
import bmesh
from mathutils import Vector, Matrix
from bpy.props import (
    BoolProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    IntVectorProperty,
    PointerProperty,
)
from bpy.types import Operator, Panel, PropertyGroup


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_LEVELS = 9
CONE_THRESHOLD = 0.02
LAST_TREE_NAME = "LowPolyHexTree"

MAT_WOOD_INDEX = 0
MAT_LEAVES_INDEX = 1


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _basis_from_direction(direction):
    """Initial basis from a direction. Used only as a starting point; the
    propagation in build_branch_segments takes over from there."""
    direction = direction.normalized()
    if abs(direction.z) < 0.99:
        ref = Vector((0.0, 0.0, 1.0))
    else:
        ref = Vector((1.0, 0.0, 0.0))
    side = direction.cross(ref).normalized()
    forward = side.cross(direction).normalized()
    return side, forward


def _propagate_basis(prev_dir, prev_side, prev_forward, new_dir):
    """Rotate (prev_side, prev_forward) by the minimal rotation that takes
    prev_dir to new_dir. This is the rotation-minimizing frame: no roll is
    introduced around the branch axis when the direction changes."""
    prev_dir = prev_dir.normalized()
    new_dir = new_dir.normalized()
    cos_theta = max(-1.0, min(1.0, prev_dir.dot(new_dir)))
    if cos_theta > 0.99999:
        return prev_side.copy(), prev_forward.copy()
    if cos_theta < -0.99999:
        # Edge case: directions are opposite. Flip about prev_side.
        rot = Matrix.Rotation(math.pi, 4, prev_side)
        return (rot @ prev_side).normalized(), (rot @ prev_forward).normalized()
    axis = prev_dir.cross(new_dir).normalized()
    angle = math.acos(cos_theta)
    rot = Matrix.Rotation(angle, 4, axis)
    return (rot @ prev_side).normalized(), (rot @ prev_forward).normalized()


def make_ring_from_basis(bm, center, side, forward, radius, sides):
    """Create a polygon ring at `center` using an explicit (side, forward) basis.
    The ring lies in the plane spanned by side and forward."""
    verts = []
    step = (2.0 * math.pi) / sides
    for i in range(sides):
        angle = i * step
        offset = side * (math.cos(angle) * radius) + forward * (math.sin(angle) * radius)
        verts.append(bm.verts.new(center + offset))
    return verts


def make_ring(bm, center, direction, radius, sides):
    """Convenience wrapper that derives a basis from the direction.
    Used by the foliage code where each leaf is independent."""
    side, forward = _basis_from_direction(direction)
    return make_ring_from_basis(bm, center, side, forward, radius, sides)


def bridge_rings(bm, ring_a, ring_b, mat_index=MAT_WOOD_INDEX):
    n = len(ring_a)
    for i in range(n):
        j = (i + 1) % n
        f = bm.faces.new([ring_a[i], ring_a[j], ring_b[j], ring_b[i]])
        f.material_index = mat_index


def cap_ring(bm, ring, flip=False, mat_index=MAT_WOOD_INDEX):
    f = bm.faces.new(list(reversed(ring)) if flip else ring)
    f.material_index = mat_index


def cone_to_apex(bm, base_ring, apex, mat_index=MAT_WOOD_INDEX):
    n = len(base_ring)
    for i in range(n):
        j = (i + 1) % n
        f = bm.faces.new([base_ring[i], apex, base_ring[j]])
        f.material_index = mat_index


def tilt_direction(parent_dir, angle, azimuth):
    side, forward = _basis_from_direction(parent_dir)
    axis = (side * math.cos(azimuth) + forward * math.sin(azimuth)).normalized()
    rot = Matrix.Rotation(angle, 4, axis)
    return (rot @ parent_dir).normalized()


def _safe01(value):
    """Clamp to [0, 1] and zero out NaN / inf / negative."""
    if not (value >= 0.0):
        return 0.0
    if value > 1.0:
        return 1.0
    return value


# ---------------------------------------------------------------------------
# Multi section branch construction
# ---------------------------------------------------------------------------

def _section_directions(base_dir, n_sections, dir_noise, rng):
    """First section is anchored to base_dir. Later sections perturb from
    the previous direction but are softly pulled back toward base_dir."""
    base_dir = base_dir.normalized()
    directions = []
    cur_dir = base_dir.copy()
    for i in range(n_sections):
        if i > 0 and dir_noise > 0.0:
            noise_vec = Vector((
                rng.uniform(-1.0, 1.0),
                rng.uniform(-1.0, 1.0),
                rng.uniform(-1.0, 1.0),
            )) * dir_noise
            mixed = cur_dir * 0.7 + base_dir * 0.3 + noise_vec
            cur_dir = mixed.normalized()
        directions.append(cur_dir.copy())
    return directions


def build_branch_segments(bm, start, base_dir, length, base_radius, taper,
                          use_cone, sides, n_sections, dir_noise, rng,
                          mat_index=MAT_WOOD_INDEX):
    n_sections = max(1, n_sections)
    section_length = length / n_sections

    directions = _section_directions(base_dir, n_sections, dir_noise, rng)

    positions = [start.copy()]
    for d in directions:
        positions.append(positions[-1] + d * section_length)

    # Ring directions: at internal junctions use the bisector of incoming and
    # outgoing section directions to get a smooth transition.
    ring_dirs = [directions[0]]
    for i in range(1, n_sections):
        bisector = (directions[i - 1] + directions[i])
        if bisector.length < 1e-6:
            bisector = directions[i].copy()
        ring_dirs.append(bisector.normalized())
    ring_dirs.append(directions[-1])

    # Radii along the path.
    if use_cone:
        radii = [base_radius * (1.0 - i / n_sections) for i in range(n_sections + 1)]
        radii[-1] = 0.0
    else:
        end_radius_target = max(0.0005, base_radius * taper)
        if base_radius > 0.0:
            ratio = end_radius_target / base_radius
            per_factor = ratio ** (1.0 / n_sections)
            radii = [base_radius * (per_factor ** i) for i in range(n_sections + 1)]
        else:
            radii = [0.0] * (n_sections + 1)

    # Parallel transport of the basis along the ring directions. The first
    # ring uses the canonical basis from its direction; every subsequent ring
    # is reached by the minimal rotation from the previous one. This prevents
    # the cross section from rolling around the branch axis between sections.
    side0, forward0 = _basis_from_direction(ring_dirs[0])
    bases = [(side0, forward0)]
    cur_dir = ring_dirs[0]
    cur_side = side0
    cur_forward = forward0
    for i in range(1, len(ring_dirs)):
        cur_side, cur_forward = _propagate_basis(
            cur_dir, cur_side, cur_forward, ring_dirs[i]
        )
        bases.append((cur_side, cur_forward))
        cur_dir = ring_dirs[i]

    if use_cone:
        rings = []
        for i in range(n_sections):
            r = max(0.0005, radii[i])
            s, f = bases[i]
            rings.append(make_ring_from_basis(bm, positions[i], s, f, r, sides))

        cap_ring(bm, rings[0], mat_index=mat_index)
        for i in range(n_sections - 1):
            bridge_rings(bm, rings[i], rings[i + 1], mat_index=mat_index)

        apex = bm.verts.new(positions[-1])
        cone_to_apex(bm, rings[-1], apex, mat_index=mat_index)
    else:
        rings = []
        for i in range(n_sections + 1):
            r = max(0.0005, radii[i])
            s, f = bases[i]
            rings.append(make_ring_from_basis(bm, positions[i], s, f, r, sides))

        cap_ring(bm, rings[0], mat_index=mat_index)
        cap_ring(bm, rings[-1], flip=True, mat_index=mat_index)
        for i in range(n_sections):
            bridge_rings(bm, rings[i], rings[i + 1], mat_index=mat_index)

    return positions, directions, radii


# ---------------------------------------------------------------------------
# Foliage
# ---------------------------------------------------------------------------

LEAF_UVS = [(1.0, 1.0), (0.0, 1.0), (0.0, 0.0), (1.0, 0.0)]


def place_leaves_on_path(bm, positions, directions, radii, params, rng, uv_layer):
    n = params.leaves_per_branch
    if n <= 0:
        return

    n_sections = len(directions)
    if n_sections == 0:
        return

    jitter = params.leaf_position_jitter
    rot_noise = params.leaf_rotation_noise
    size_min = min(params.leaf_size_min, params.leaf_size_max)
    size_max = max(params.leaf_size_min, params.leaf_size_max)

    azimuth_phase = rng.uniform(0.0, 2.0 * math.pi)
    az_step = (2.0 * math.pi) / n

    for i in range(n):
        t_offset = (rng.random() - 0.5) * jitter
        t = (i + 0.5 + t_offset) / n
        t = max(0.05, min(0.98, t))

        section_t = t * n_sections
        section_idx = min(int(section_t), n_sections - 1)
        local_t = section_t - section_idx

        pos0 = positions[section_idx]
        pos1 = positions[section_idx + 1]
        position = pos0 * (1.0 - local_t) + pos1 * local_t

        direction = directions[section_idx]

        r0 = radii[section_idx]
        r1 = radii[section_idx + 1] if section_idx + 1 < len(radii) else 0.0
        radius_at_t = r0 * (1.0 - local_t) + r1 * local_t

        az_offset = (rng.random() - 0.5) * jitter
        azimuth = azimuth_phase + (i + 0.5 + az_offset) * az_step

        side, forward = _basis_from_direction(direction)
        outward = side * math.cos(azimuth) + forward * math.sin(azimuth)

        size = rng.uniform(size_min, size_max)

        quad_x = direction.copy()
        quad_y = direction.cross(outward).normalized()

        if rot_noise > 0.0:
            normal = outward.copy()
            rx = rng.uniform(-1.0, 1.0) * math.pi * rot_noise
            ry = rng.uniform(-1.0, 1.0) * math.pi * rot_noise
            rz = rng.uniform(-1.0, 1.0) * math.pi * rot_noise
            rot = (Matrix.Rotation(rx, 4, normal) @
                   Matrix.Rotation(ry, 4, quad_y) @
                   Matrix.Rotation(rz, 4, quad_x))
            quad_x = (rot @ quad_x).normalized()
            quad_y = (rot @ quad_y).normalized()

        leaf_center = position + outward * radius_at_t
        half = size * 0.5
        v1 = bm.verts.new(leaf_center + quad_x * half + quad_y * half)
        v2 = bm.verts.new(leaf_center - quad_x * half + quad_y * half)
        v3 = bm.verts.new(leaf_center - quad_x * half - quad_y * half)
        v4 = bm.verts.new(leaf_center + quad_x * half - quad_y * half)

        face = bm.faces.new([v1, v2, v3, v4])
        face.material_index = MAT_LEAVES_INDEX

        for j, loop in enumerate(face.loops):
            loop[uv_layer].uv = LEAF_UVS[j]


# ---------------------------------------------------------------------------
# Tree growth
# ---------------------------------------------------------------------------

def grow_branch(bm, start, direction, length, base_radius, depth, params,
                rng, leaf_rng, is_root=False, uv_layer=None):
    direction = direction.normalized()

    if not is_root and params.length_noise > 0.0:
        length *= 1.0 + rng.uniform(-1.0, 1.0) * params.length_noise

    is_leaf = depth >= params.max_depth
    sides = max(3, params.level_sides[depth])
    taper = params.level_taper[depth]
    use_cone = is_leaf and taper <= CONE_THRESHOLD

    n_sections = max(1, params.level_sections[depth])
    dir_noise = _safe01(params.level_curve_noise[depth])

    positions, directions, radii = build_branch_segments(
        bm, start, direction, length, base_radius, taper, use_cone,
        sides, n_sections, dir_noise, rng, mat_index=MAT_WOOD_INDEX,
    )

    if (uv_layer is not None and params.leaves_enabled
            and params.leaves_per_branch > 0
            and (params.max_depth - depth) < params.leaf_depth_count):
        place_leaves_on_path(bm, positions, directions, radii,
                             params, leaf_rng, uv_layer)

    if is_leaf:
        return

    end_pos = positions[-1]
    end_dir = directions[-1]
    end_radius = radii[-1]

    n_children = max(1, params.level_branches[depth])
    next_depth = depth + 1
    child_length_ratio = params.level_length_falloff[next_depth]

    azimuth_offset = rng.uniform(0.0, 2.0 * math.pi)
    azimuth_step = (2.0 * math.pi) / n_children

    for i in range(n_children):
        azimuth = azimuth_offset + i * azimuth_step
        azimuth += rng.uniform(-1.0, 1.0) * params.azimuth_noise

        angle = math.radians(params.branch_angle)
        if params.angle_noise > 0.0:
            angle *= 1.0 + rng.uniform(-1.0, 1.0) * params.angle_noise
        angle = max(0.0, min(math.radians(89.0), angle))

        child_dir = tilt_direction(end_dir, angle, azimuth)

        if params.vertical_bias != 0.0:
            target = Vector((0.0, 0.0, 1.0 if params.vertical_bias > 0.0 else -1.0))
            t = abs(params.vertical_bias)
            child_dir = ((1.0 - t) * child_dir + t * target).normalized()

        if params.direction_noise > 0.0:
            noise_vec = Vector((
                rng.uniform(-1.0, 1.0),
                rng.uniform(-1.0, 1.0),
                rng.uniform(-1.0, 1.0),
            )) * params.direction_noise
            child_dir = (child_dir + noise_vec).normalized()

        child_length = length * child_length_ratio
        child_radius = end_radius

        grow_branch(
            bm, end_pos, child_dir, child_length, child_radius,
            next_depth, params, rng, leaf_rng,
            is_root=False, uv_layer=uv_layer,
        )


# ---------------------------------------------------------------------------
# UV mapping for trunk and branches (box projection)
# ---------------------------------------------------------------------------

def apply_box_projection(bm, uv_layer, target_mat_index, scale):
    inv = 1.0 / max(0.0001, scale)
    for face in bm.faces:
        if face.material_index != target_mat_index:
            continue
        n = face.normal
        ax = abs(n.x)
        ay = abs(n.y)
        az = abs(n.z)
        if ax >= ay and ax >= az:
            for loop in face.loops:
                co = loop.vert.co
                loop[uv_layer].uv = (co.y * inv, co.z * inv)
        elif ay >= az:
            for loop in face.loops:
                co = loop.vert.co
                loop[uv_layer].uv = (co.x * inv, co.z * inv)
        else:
            for loop in face.loops:
                co = loop.vert.co
                loop[uv_layer].uv = (co.x * inv, co.y * inv)


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

def ensure_materials(obj, mat_wood, mat_leaves):
    mesh = obj.data
    while len(mesh.materials) < 2:
        mesh.materials.append(None)
    while len(mesh.materials) > 2:
        try:
            mesh.materials.pop(index=len(mesh.materials) - 1)
        except (TypeError, RuntimeError):
            break
    mesh.materials[MAT_WOOD_INDEX] = mat_wood
    mesh.materials[MAT_LEAVES_INDEX] = mat_leaves


# ---------------------------------------------------------------------------
# Tree builder
# ---------------------------------------------------------------------------

def build_tree_object(context, params, set_selection=True):
    rng = random.Random(params.seed)
    leaf_rng = random.Random(params.seed + 12345)

    old = bpy.data.objects.get(LAST_TREE_NAME)

    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.verify()

    try:
        grow_branch(
            bm,
            start=Vector((0.0, 0.0, 0.0)),
            direction=Vector((0.0, 0.0, 1.0)),
            length=params.trunk_height,
            base_radius=params.trunk_radius,
            depth=0,
            params=params,
            rng=rng,
            leaf_rng=leaf_rng,
            is_root=True,
            uv_layer=uv_layer,
        )

        apply_box_projection(bm, uv_layer, MAT_WOOD_INDEX, params.wood_uv_scale)

        if old is not None and params.replace_existing:
            mesh = old.data
            bm.to_mesh(mesh)
            obj = old
        else:
            mesh = bpy.data.meshes.new(LAST_TREE_NAME)
            bm.to_mesh(mesh)
            obj = bpy.data.objects.new(LAST_TREE_NAME, mesh)
            context.collection.objects.link(obj)
    finally:
        bm.free()

    ensure_materials(obj, params.mat_wood, params.mat_leaves)
    mesh.update()

    if set_selection:
        for o in list(context.selected_objects):
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj

    return obj, len(mesh.polygons)


# ---------------------------------------------------------------------------
# Live update plumbing
# ---------------------------------------------------------------------------

_updating_lock = False


def _update_tree(self, context):
    global _updating_lock
    if _updating_lock:
        return
    if not self.live_update:
        return
    if bpy.data.objects.get(LAST_TREE_NAME) is None:
        return
    _updating_lock = True
    try:
        build_tree_object(context, self, set_selection=False)
    except Exception as exc:
        print(f"[LowPolyHexTree] live update error: {exc}")
    finally:
        _updating_lock = False


def _update_materials(self, context):
    global _updating_lock
    if _updating_lock:
        return
    obj = bpy.data.objects.get(LAST_TREE_NAME)
    if obj is None:
        return
    ensure_materials(obj, self.mat_wood, self.mat_leaves)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class LPT_Properties(PropertyGroup):

    trunk_height: FloatProperty(
        name="Trunk Height", default=2.0, min=0.05, soft_max=10.0, max=50.0,
        update=_update_tree,
    )
    trunk_radius: FloatProperty(
        name="Trunk Radius", default=0.25, min=0.01, soft_max=2.0, max=10.0,
        update=_update_tree,
    )
    max_depth: IntProperty(
        name="Branch Depth", default=4, min=0, max=MAX_LEVELS - 1,
        update=_update_tree,
    )

    level_branches: IntVectorProperty(
        name="Branches per Split", size=MAX_LEVELS,
        default=(3, 3, 3, 3, 3, 3, 3, 3, 3),
        min=1, max=8, update=_update_tree,
    )
    level_sides: IntVectorProperty(
        name="Polygon Sides", size=MAX_LEVELS,
        default=(6, 6, 5, 4, 4, 3, 3, 3, 3),
        min=3, max=12, update=_update_tree,
    )
    level_sections: IntVectorProperty(
        name="Sections", size=MAX_LEVELS,
        default=(3, 2, 2, 1, 1, 1, 1, 1, 1),
        min=1, max=10, update=_update_tree,
    )
    level_curve_noise: FloatVectorProperty(
        name="Curve Noise", size=MAX_LEVELS,
        description="Per-level random directional perturbation between sections. "
                    "The first section of each branch is always anchored to its "
                    "starting direction, only later sections curve. Cross sections "
                    "are propagated by parallel transport so the bend never adds "
                    "twist around the branch axis",
        default=(0.0,) * MAX_LEVELS,
        min=0.0, max=1.0, update=_update_tree,
    )
    level_taper: FloatVectorProperty(
        name="Taper", size=MAX_LEVELS,
        default=(0.85, 0.78, 0.7, 0.6, 0.0, 0.0, 0.0, 0.0, 0.0),
        min=0.0, max=1.5, soft_max=1.0, update=_update_tree,
    )
    level_length_falloff: FloatVectorProperty(
        name="Length × Parent", size=MAX_LEVELS,
        default=(1.0, 0.75, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7),
        min=0.05, max=2.0, soft_max=1.5, update=_update_tree,
    )

    current_level: IntProperty(
        name="Edit Level", default=0, min=0, max=MAX_LEVELS - 1,
    )

    branch_angle: FloatProperty(
        name="Branch Angle", default=35.0, min=0.0, max=89.0,
        update=_update_tree,
    )
    vertical_bias: FloatProperty(
        name="Vertical Bias", default=0.25, min=-1.0, max=1.0,
        update=_update_tree,
    )
    direction_noise: FloatProperty(
        name="Direction Noise", default=0.15, min=0.0, max=1.0,
        update=_update_tree,
    )

    angle_noise: FloatProperty(
        name="Angle Noise", default=0.2, min=0.0, max=1.0, update=_update_tree,
    )
    azimuth_noise: FloatProperty(
        name="Azimuth Noise", default=0.3, min=0.0, max=math.pi,
        update=_update_tree,
    )
    length_noise: FloatProperty(
        name="Length Noise", default=0.15, min=0.0, max=1.0, update=_update_tree,
    )

    leaves_enabled: BoolProperty(
        name="Enable Foliage", default=True, update=_update_tree,
    )
    leaves_per_branch: IntProperty(
        name="Leaves per Branch", default=5, min=0, max=50, update=_update_tree,
    )
    leaf_depth_count: IntProperty(
        name="Foliage Depth", default=2, min=0, max=MAX_LEVELS,
        update=_update_tree,
    )
    leaf_size_min: FloatProperty(
        name="Leaf Size Min", default=0.18, min=0.001, max=2.0,
        update=_update_tree,
    )
    leaf_size_max: FloatProperty(
        name="Leaf Size Max", default=0.28, min=0.001, max=2.0,
        update=_update_tree,
    )
    leaf_position_jitter: FloatProperty(
        name="Position Jitter", default=0.4, min=0.0, max=1.0,
        update=_update_tree,
    )
    leaf_rotation_noise: FloatProperty(
        name="Rotation Noise", default=0.35, min=0.0, max=1.0,
        update=_update_tree,
    )

    mat_wood: PointerProperty(
        type=bpy.types.Material, name="Wood",
        update=_update_materials,
    )
    mat_leaves: PointerProperty(
        type=bpy.types.Material, name="Leaves",
        update=_update_materials,
    )
    wood_uv_scale: FloatProperty(
        name="Wood UV Scale",
        description="World units per texture tile on the trunk and branches",
        default=0.5, min=0.01, max=100.0, soft_max=10.0,
        update=_update_tree,
    )

    seed: IntProperty(
        name="Seed", default=1, min=0, max=999999, update=_update_tree,
    )
    replace_existing: BoolProperty(
        name="Replace Last Tree", default=True,
    )
    live_update: BoolProperty(
        name="Live Update", default=True,
    )


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class LPT_OT_generate(Operator):
    bl_idname = "mesh.lowpoly_hex_tree_generate"
    bl_label = "Generate Tree"
    bl_description = "Build a procedural low poly hex tree at the world origin"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        params = context.scene.lpt_props
        global _updating_lock
        _updating_lock = True
        try:
            obj, faces = build_tree_object(context, params, set_selection=True)
        finally:
            _updating_lock = False
        self.report({'INFO'}, f"Tree generated ({faces} faces, seed {params.seed})")
        return {'FINISHED'}


class LPT_OT_new_seed(Operator):
    bl_idname = "mesh.lowpoly_hex_tree_new_seed"
    bl_label = "New Seed"
    bl_description = "Increment the seed and regenerate the tree"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        p = context.scene.lpt_props
        p.seed = (p.seed + 1) % 1000000
        if not p.live_update:
            global _updating_lock
            _updating_lock = True
            try:
                build_tree_object(context, p, set_selection=True)
            finally:
                _updating_lock = False
        return {'FINISHED'}


class LPT_OT_set_edit_level(Operator):
    bl_idname = "mesh.lowpoly_hex_tree_set_edit_level"
    bl_label = "Edit Level"
    bl_options = {'INTERNAL'}

    level: IntProperty(default=0)

    def execute(self, context):
        context.scene.lpt_props.current_level = self.level
        return {'FINISHED'}


class LPT_OT_copy_level(Operator):
    bl_idname = "mesh.lowpoly_hex_tree_copy_level"
    bl_label = "Copy to All Levels"
    bl_description = "Copy the current level's parameters to every other level"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        p = context.scene.lpt_props
        src = p.current_level
        global _updating_lock
        _updating_lock = True
        try:
            for i in range(MAX_LEVELS):
                if i == src:
                    continue
                p.level_branches[i] = p.level_branches[src]
                p.level_sides[i] = p.level_sides[src]
                p.level_sections[i] = p.level_sections[src]
                p.level_curve_noise[i] = p.level_curve_noise[src]
                p.level_taper[i] = p.level_taper[src]
                if i > 0:
                    p.level_length_falloff[i] = p.level_length_falloff[src]
        finally:
            _updating_lock = False
        if p.live_update and bpy.data.objects.get(LAST_TREE_NAME) is not None:
            _updating_lock = True
            try:
                build_tree_object(context, p, set_selection=False)
            finally:
                _updating_lock = False
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

class LPT_PT_panel(Panel):
    bl_label = "Low Poly Hex Tree"
    bl_idname = "LPT_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Tree'

    def draw(self, context):
        layout = self.layout
        p = context.scene.lpt_props

        row = layout.row(align=True)
        row.scale_y = 1.4
        row.operator("mesh.lowpoly_hex_tree_generate", icon='MESH_DATA')
        row.operator("mesh.lowpoly_hex_tree_new_seed", icon='FILE_REFRESH', text="")

        layout.prop(p, "live_update", icon='AUTO')

        box = layout.box()
        box.label(text="Trunk Base", icon='MESH_CYLINDER')
        box.prop(p, "trunk_height")
        box.prop(p, "trunk_radius")
        box.prop(p, "max_depth")

        box = layout.box()
        box.label(text="Per-Level Settings", icon='MOD_ARRAY')

        shown_level = min(p.current_level, p.max_depth)
        row = box.row(align=True)
        for level in range(p.max_depth + 1):
            op = row.operator(
                "mesh.lowpoly_hex_tree_set_edit_level",
                text=str(level),
                depress=(shown_level == level),
            )
            op.level = level

        is_leaf = (shown_level == p.max_depth)
        if shown_level == 0 and p.max_depth == 0:
            label = f"Level {shown_level} (Trunk = Leaf)"
        elif shown_level == 0:
            label = f"Level {shown_level} (Trunk)"
        elif is_leaf:
            label = f"Level {shown_level} (Leaves)"
        else:
            label = f"Level {shown_level}"
        box.label(text=label, icon='RIGHTARROW')

        col = box.column(align=True)
        col.prop(p, "level_sides", index=shown_level, text="Sides")
        col.prop(p, "level_sections", index=shown_level, text="Sections")
        if p.level_sections[shown_level] > 1:
            col.prop(p, "level_curve_noise", index=shown_level, text="Curve Noise")
        col.prop(p, "level_taper", index=shown_level, text="Taper")
        if shown_level > 0:
            col.prop(p, "level_length_falloff", index=shown_level, text="Length × Parent")
        if not is_leaf:
            col.prop(p, "level_branches", index=shown_level, text="Branches")

        box.operator("mesh.lowpoly_hex_tree_copy_level", icon='DUPLICATE')

        box = layout.box()
        box.label(text="Direction", icon='ORIENTATION_NORMAL')
        box.prop(p, "branch_angle")
        box.prop(p, "vertical_bias")
        box.prop(p, "direction_noise")

        box = layout.box()
        box.label(text="Branch Noise", icon='RNDCURVE')
        box.prop(p, "angle_noise")
        box.prop(p, "azimuth_noise")
        box.prop(p, "length_noise")

        box = layout.box()
        header = box.row(align=True)
        header.prop(p, "leaves_enabled", text="")
        header.label(text="Foliage", icon='OUTLINER_OB_LIGHTPROBE')

        sub = box.column(align=True)
        sub.enabled = p.leaves_enabled
        sub.prop(p, "leaves_per_branch")
        sub.prop(p, "leaf_depth_count")

        sub.separator()
        size_row = sub.row(align=True)
        size_row.prop(p, "leaf_size_min", text="Size Min")
        size_row.prop(p, "leaf_size_max", text="Max")

        sub.prop(p, "leaf_position_jitter")
        sub.prop(p, "leaf_rotation_noise")

        box = layout.box()
        box.label(text="Materials & UV", icon='MATERIAL')
        box.prop(p, "mat_wood")
        box.prop(p, "mat_leaves")
        box.separator()
        box.prop(p, "wood_uv_scale")

        box = layout.box()
        box.prop(p, "seed")
        box.prop(p, "replace_existing")


def _add_menu_entry(self, context):
    self.layout.operator(LPT_OT_generate.bl_idname, icon='MESH_DATA')


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    LPT_Properties,
    LPT_OT_generate,
    LPT_OT_new_seed,
    LPT_OT_set_edit_level,
    LPT_OT_copy_level,
    LPT_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.lpt_props = PointerProperty(type=LPT_Properties)
    bpy.types.VIEW3D_MT_mesh_add.append(_add_menu_entry)


def unregister():
    bpy.types.VIEW3D_MT_mesh_add.remove(_add_menu_entry)
    del bpy.types.Scene.lpt_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
