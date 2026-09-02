bl_info = {
    "name": "Curve Railing Generator",
    "author": "Muware",
    "version": (1, 2, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar (N) > Railing",
    "description": "Generate a railing (handrail + balusters) along a curve, auto-rounding corners and putting geometry only where the curvature needs it.",
    "category": "Add Mesh",
}

import bpy
import math
import traceback
from mathutils import Vector, Quaternion
from mathutils.geometry import interpolate_bezier


_Z = Vector((0.0, 0.0, 1.0))
_X = Vector((1.0, 0.0, 0.0))

# Dense samples per Bezier segment before simplification. Cheap: almost all of
# them get thrown away, they only exist so the angle measurement is accurate.
DENSE_PER_SEGMENT = 64


# ==============================================================
# Curve sampling
# ==============================================================

def is_polyline(spline):
    """True when the spline is just control points, with no curvature of its
    own: a POLY spline, or a Bezier whose handles are all VECTOR (which is
    what Blender gives you when you lay out corners rather than curves)."""
    if spline.type != 'BEZIER':
        return True
    return all(bp.handle_left_type == 'VECTOR' and bp.handle_right_type == 'VECTOR'
               for bp in spline.bezier_points)


def sample_spline(spline, matrix):
    """World-space polyline for one spline. Returns (points, cyclic, corners).

    `corners` says the points are control points to be filleted, rather than a
    dense sampling to be simplified. For a cyclic spline the closing point is
    NOT repeated at the end.
    """
    cyclic = spline.use_cyclic_u
    corners = is_polyline(spline)

    if spline.type == 'BEZIER':
        knots = spline.bezier_points
        n = len(knots)
        if n < 2:
            return [], cyclic, corners
        if corners:
            pts = [bp.co.copy() for bp in knots]
        else:
            pts = []
            last = n if cyclic else n - 1
            for i in range(last):
                a = knots[i]
                b = knots[(i + 1) % n]
                seg = interpolate_bezier(
                    a.co, a.handle_right, b.handle_left, b.co, DENSE_PER_SEGMENT + 1
                )
                pts.extend(seg[:-1])      # next segment contributes the shared knot
            if not cyclic:
                pts.append(knots[-1].co.copy())
    else:
        pts = [p.co.xyz.copy() for p in spline.points]
        if len(pts) < 2:
            return [], cyclic, corners

    return [matrix @ Vector(p) for p in pts], cyclic, corners


def dedupe(pts, eps=1e-6):
    """Drop points that land on their predecessor. Zero-length segments would
    otherwise give the tube sweep an undefined tangent."""
    out = []
    for p in pts:
        if not out or (p - out[-1]).length > eps:
            out.append(p)
    return out


def fillet(pts, cyclic, radius, max_angle):
    """Replace every corner of a control polyline with a true circular arc.

    Each arc is tessellated into ceil(turn / max_angle) segments, so the corner
    carries exactly the geometry its angle needs and the straights carry none.
    Adjacent fillets can never overlap: the tangent length is clamped to half
    of each neighbouring segment, shrinking the radius locally if it must.
    """
    n = len(pts)
    if n < 3 or radius <= 0.0:
        return dedupe(pts)

    out = [] if cyclic else [pts[0].copy()]
    for i in (range(n) if cyclic else range(1, n - 1)):
        p = pts[i]
        d1 = p - pts[i - 1]
        d2 = pts[(i + 1) % n] - p
        l1, l2 = d1.length, d2.length
        if l1 < 1e-9 or l2 < 1e-9:
            continue
        d1 /= l1
        d2 /= l2

        turn = d1.angle(d2, 0.0)
        axis = d1.cross(d2)
        if turn < 1e-4 or axis.length_squared < 1e-18:
            out.append(p.copy())          # collinear: not a corner, keep it as is
            continue
        axis.normalize()

        half = turn / 2.0
        tangent = min(radius * math.tan(half), l1 / 2.0, l2 / 2.0)
        r = tangent / math.tan(half)

        start = p - d1 * tangent
        centre = p + (d2 - d1).normalized() * math.hypot(tangent, r)
        spoke = start - centre
        # The epsilon keeps an exact 90 degrees at 9 degrees a step from
        # rounding up to 11 steps on float noise.
        steps = max(1, math.ceil(turn / max_angle - 1e-6))
        for k in range(steps + 1):
            q = spoke.copy()
            q.rotate(Quaternion(axis, turn * k / steps))
            out.append(centre + q)

    if not cyclic:
        out.append(pts[-1].copy())
    return dedupe(out)


def simplify(pts, cyclic, max_angle, max_length):
    """Keep a sample only when the polyline has turned by max_angle since the
    last kept one, or run straight for max_length. This is the whole point of
    the addon: dense geometry in tight corners, next to none on straights."""
    n = len(pts)
    if n < 3:
        return list(pts)

    keep = [0]
    turn = 0.0
    run = 0.0
    last = n if cyclic else n - 1
    for i in range(1, last):
        prev = pts[i] - pts[i - 1]
        nxt = pts[(i + 1) % n] - pts[i]
        run += prev.length
        if prev.length_squared > 0.0 and nxt.length_squared > 0.0:
            turn += prev.angle(nxt, 0.0)
        if turn >= max_angle or run >= max_length:
            keep.append(i)
            turn = 0.0
            run = 0.0
    if not cyclic:
        keep.append(n - 1)

    return [pts[i] for i in keep]


def resample_uniform(pts, cyclic, spacing):
    """Points at even arc-length steps, the step nudged so it divides the
    length exactly (same trick as the stair generator's riser height)."""
    n = len(pts)
    segs = [(pts[i + 1] - pts[i]).length for i in range(n - 1)]
    if cyclic:
        segs.append((pts[0] - pts[-1]).length)
    total = sum(segs)
    if total <= 0.0:
        return [pts[0]]

    count = max(1, round(total / spacing))
    step = total / count

    out = []
    i = 0
    acc = 0.0                                  # arc length at pts[i]
    for k in range(count if cyclic else count + 1):
        target = k * step
        while i < len(segs) and acc + segs[i] < target:
            acc += segs[i]
            i += 1
        if i >= len(segs):
            out.append((pts[0] if cyclic else pts[-1]).copy())
            continue
        t = (target - acc) / segs[i] if segs[i] > 0.0 else 0.0
        out.append(pts[i].lerp(pts[(i + 1) % n], t))
    return out


# ==============================================================
# Geometry construction
# ==============================================================

def _frame(tangent):
    """Fixed-up frame: no twist accumulation, and a railing's tube is always
    'upright' anyway. Falls back to X when the tangent is near vertical."""
    ref = _Z if abs(tangent.z) < 0.999 else _X
    up = (ref - tangent * ref.dot(tangent)).normalized()
    return tangent.cross(up), up


def _tangents(pts, cyclic):
    n = len(pts)
    out = []
    for i in range(n):
        if cyclic:
            a, b = pts[i - 1], pts[(i + 1) % n]
        else:
            a = pts[i - 1] if i > 0 else pts[i]
            b = pts[i + 1] if i < n - 1 else pts[i]
        d = b - a
        out.append(d.normalized() if d.length_squared > 0.0 else _X.copy())
    return out


def sweep(pts, radius, segments, cyclic=False, caps=True):
    """Circular tube along a polyline. Quads on the sides, n-gon caps.
    Returns (verts, faces, smooth_count) with faces indexed from 0."""
    n = len(pts)
    if n < 2 or radius <= 0.0 or segments < 3:
        return [], [], 0

    ring_angles = [2.0 * math.pi * k / segments for k in range(segments)]
    verts = []
    for p, t in zip(pts, _tangents(pts, cyclic)):
        side, up = _frame(t)
        for a in ring_angles:
            verts.append(p + (side * math.cos(a) + up * math.sin(a)) * radius)

    faces = []
    for i in range(n if cyclic else n - 1):
        a = i * segments
        b = ((i + 1) % n) * segments
        for k in range(segments):
            k1 = (k + 1) % segments
            faces.append((a + k, b + k, b + k1, a + k1))

    smooth = len(faces)
    if caps and not cyclic:
        faces.append(tuple(range(segments)))
        faces.append(tuple(reversed(range((n - 1) * segments, n * segments))))

    return verts, faces, smooth


def build_railing(pts, cyclic, corners, props):
    """Assemble rails and posts into one mesh.
    Returns (verts, faces, smooth_count, section_count).

    Faces are ordered tube-first so `smooth_count` marks the split between
    smooth-shaded tube faces and flat-shaded caps.
    """
    verts, tube_faces, cap_faces = [], [], []

    def add(v, f, smooth):
        off = len(verts)
        verts.extend(v)
        tube_faces.extend(tuple(i + off for i in q) for q in f[:smooth])
        cap_faces.extend(tuple(i + off for i in q) for q in f[smooth:])

    if corners:
        # Control points: the fillet already emits exactly the right density,
        # so running simplify() over it afterwards would only coarsen it.
        rail_path = fillet(pts, cyclic, props.corner_radius, props.max_angle)
    else:
        rail_path = simplify(pts, cyclic, props.max_angle, props.max_length)

    count = max(1, props.rail_count)
    for r in range(count):
        h = props.height * (r + 1) / count
        add(*sweep([p + _Z * h for p in rail_path],
                   props.rail_radius, props.rail_segments, cyclic))

    if props.use_posts:
        # Posts follow the rounded path, not the sharp control polyline. In
        # curve mode the dense sampling is the more faithful base.
        post_path = rail_path if corners else pts
        for q in resample_uniform(post_path, cyclic, max(props.post_spacing, 1e-4)):
            add(*sweep([q - _Z * props.post_sink, q + _Z * props.height],
                       props.post_radius, props.post_segments))

    return verts, tube_faces + cap_faces, len(tube_faces), len(rail_path)


# ==============================================================
# Mesh update
# ==============================================================

def gather_curve(curve_obj, matrix_inv, depsgraph=None):
    """All splines of the curve as (points, cyclic), in railing local space.

    Reads the evaluated copy so edit-mode moves and modifiers are picked up.
    A curve with a bevel/extrude evaluates to a Mesh instead, hence the fallback.
    """
    data = curve_obj.data
    if depsgraph is not None:
        evaluated = curve_obj.evaluated_get(depsgraph).data
        if hasattr(evaluated, "splines"):
            data = evaluated

    out = []
    for spline in data.splines:
        pts, cyclic, corners = sample_spline(spline, curve_obj.matrix_world)
        if len(pts) >= 2:
            out.append(([matrix_inv @ p for p in pts], cyclic, corners))
    return out


def regenerate(obj, depsgraph=None):
    props = obj.railing_props
    curve_obj = props.curve
    if curve_obj is None or curve_obj.type != 'CURVE':
        raise ValueError("no curve assigned")

    verts, faces = [], []
    smooth = 0
    dense = sections = 0
    for pts, cyclic, corners in gather_curve(curve_obj, obj.matrix_world.inverted(), depsgraph):
        v, f, s, kept = build_railing(pts, cyclic, corners, props)
        off = len(verts)
        verts.extend(v)
        # Keep every mesh's tube faces before any cap face, so one smooth count
        # still splits the merged list.
        faces[smooth:smooth] = [tuple(i + off for i in q) for q in f[:s]]
        faces.extend(tuple(i + off for i in q) for q in f[s:])
        smooth += s
        dense += len(pts)
        sections += kept

    if not verts:
        raise ValueError("curve has no usable spline")

    # Rewrite the existing mesh in place rather than swapping datablocks:
    # creating/removing datablocks from inside a depsgraph handler is asking
    # for trouble, and this is faster anyway.
    mesh = obj.data
    mesh.clear_geometry()
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    mesh.validate(verbose=False)

    for i, poly in enumerate(mesh.polygons):
        poly.use_smooth = i < smooth

    mesh.materials.clear()
    if props.material is not None:
        mesh.materials.append(props.material)

    props.stat_tris = sum(len(p.vertices) - 2 for p in mesh.polygons)
    props.stat_verts = len(mesh.vertices)
    props.stat_sections = sections
    props.stat_dense = dense
    return obj


def is_railing(obj):
    return obj is not None and obj.type == 'MESH' and obj.railing_props.is_railing


def path_is_corners(curve_obj):
    """Which authoring style the assigned curve uses, for the UI."""
    if curve_obj is None or curve_obj.type != 'CURVE' or not curve_obj.data.splines:
        return True
    return is_polyline(curve_obj.data.splines[0])


def find_railing(obj):
    """The railing to edit for the active object: itself, or the one driven by
    the active curve. So the panel keeps working while you edit the path."""
    if is_railing(obj):
        return obj
    if obj is not None and obj.type == 'CURVE':
        for o in bpy.data.objects:
            if is_railing(o) and o.railing_props.curve == obj:
                return o
    return None


# ==============================================================
# Live update callback
# ==============================================================

def _live_update(self, context):
    if not self.auto_update:
        return
    try:
        regenerate(self.id_data, context.evaluated_depsgraph_get() if context else None)
    except Exception:
        traceback.print_exc()


# Our own regenerate dirties the depsgraph, which re-enters the handler.
_rebuilding = False


@bpy.app.handlers.persistent
def _on_depsgraph_update(scene, depsgraph):
    """Rebuild railings whose curve just changed. This is what makes moving a
    control point in Edit Mode update the railing live."""
    global _rebuilding
    if _rebuilding:
        return

    dirty = {u.id.original.as_pointer() for u in depsgraph.updates}
    if not dirty:
        return

    targets = []
    for obj in scene.objects:
        # Cheap guards first: most objects are not railings.
        if obj.type != 'MESH' or obj.mode != 'OBJECT':
            continue
        props = obj.railing_props
        curve_obj = props.curve
        if not (props.is_railing and props.auto_update and curve_obj is not None):
            continue
        if curve_obj.original.as_pointer() in dirty or curve_obj.data.original.as_pointer() in dirty:
            targets.append(obj)

    if not targets:
        return

    _rebuilding = True
    try:
        for obj in targets:
            try:
                regenerate(obj, depsgraph)
            except Exception:
                traceback.print_exc()
    finally:
        _rebuilding = False


def _curve_poll(self, obj):
    return obj.type == 'CURVE'


# ==============================================================
# Properties
# ==============================================================

class RailingGenProperties(bpy.types.PropertyGroup):
    is_railing: bpy.props.BoolProperty(
        name="Is Railing",
        description="Marks this object as generated and editable by Curve Railing Generator",
        default=False,
    )
    auto_update: bpy.props.BoolProperty(
        name="Live Update",
        description="Regenerate immediately on every parameter change, and whenever the curve is edited",
        default=True,
    )
    curve: bpy.props.PointerProperty(
        name="Curve",
        type=bpy.types.Object,
        poll=_curve_poll,
        description="Curve the railing follows. Its path is the base line; the rail sits above it",
        update=_live_update,
    )

    height: bpy.props.FloatProperty(
        name="Height",
        description="Height of the handrail axis above the curve",
        default=1.0,
        min=0.0001,
        unit='LENGTH',
        update=_live_update,
    )
    rail_radius: bpy.props.FloatProperty(
        name="Rail Radius",
        description="Radius of the handrail tube",
        default=0.025,
        min=0.0001,
        unit='LENGTH',
        update=_live_update,
    )
    rail_segments: bpy.props.IntProperty(
        name="Rail Sides",
        description="Radial resolution of the handrail tube",
        default=8,
        min=3,
        update=_live_update,
    )
    rail_count: bpy.props.IntProperty(
        name="Rails",
        description="Number of horizontal rails, evenly spread between the curve and the height (the topmost is the handrail)",
        default=1,
        min=1,
        update=_live_update,
    )

    use_posts: bpy.props.BoolProperty(
        name="Posts",
        description="Generate the vertical balusters",
        default=True,
        update=_live_update,
    )
    post_radius: bpy.props.FloatProperty(
        name="Post Radius",
        description="Radius of the baluster tubes",
        default=0.015,
        min=0.0001,
        unit='LENGTH',
        update=_live_update,
    )
    post_segments: bpy.props.IntProperty(
        name="Post Sides",
        description="Radial resolution of the balusters",
        default=6,
        min=3,
        update=_live_update,
    )
    post_spacing: bpy.props.FloatProperty(
        name="Spacing",
        description="Target distance between balusters. Adjusted so they divide the curve exactly",
        default=1.0,
        min=0.001,
        unit='LENGTH',
        update=_live_update,
    )
    post_sink: bpy.props.FloatProperty(
        name="Sink",
        description="How far the balusters extend below the curve, to bury their base in the floor",
        default=0.0,
        min=0.0,
        unit='LENGTH',
        update=_live_update,
    )

    corner_radius: bpy.props.FloatProperty(
        name="Corner Radius",
        description="Radius of the arc that rounds off every corner of a control-point path. "
                    "Automatically shrunk on corners whose segments are too short to fit it. "
                    "0 keeps the corners sharp",
        default=0.2,
        min=0.0,
        unit='LENGTH',
        update=_live_update,
    )
    max_angle: bpy.props.FloatProperty(
        name="Max Deviation",
        description="A rail section is emitted once the curve has turned by this much. Lower = smoother corners and more triangles",
        default=math.radians(8.0),
        min=math.radians(0.1),
        max=math.radians(90.0),
        subtype='ANGLE',
        update=_live_update,
    )
    max_length: bpy.props.FloatProperty(
        name="Max Section",
        description="Longest straight rail section. Only caps how coarse a dead-straight run may get",
        default=10.0,
        min=0.001,
        unit='LENGTH',
        update=_live_update,
    )

    material: bpy.props.PointerProperty(
        name="Material",
        type=bpy.types.Material,
        description="Material applied to the generated mesh",
        update=_live_update,
    )

    stat_tris: bpy.props.IntProperty(name="Triangles")
    stat_verts: bpy.props.IntProperty(name="Vertices")
    stat_sections: bpy.props.IntProperty(name="Rail Sections")
    stat_dense: bpy.props.IntProperty(name="Sampled")


# ==============================================================
# Operators
# ==============================================================

class RAILGEN_OT_new(bpy.types.Operator):
    bl_idname = "railgen.new"
    bl_label = "New Railing"
    bl_description = "Create a railing following the active curve"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'CURVE'

    def execute(self, context):
        curve_obj = context.active_object
        obj = bpy.data.objects.new(curve_obj.name + "_Railing",
                                   bpy.data.meshes.new("Railing_mesh"))
        context.collection.objects.link(obj)
        obj.matrix_world = curve_obj.matrix_world.copy()
        obj.railing_props.is_railing = True
        obj.railing_props.curve = curve_obj
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


class RAILGEN_OT_new_path(bpy.types.Operator):
    bl_idname = "railgen.new_path"
    bl_label = "New Railing Path"
    bl_description = ("Create a 2-point control path at the 3D cursor with its railing, "
                      "and drop into Edit Mode. Extrude with E to lay out the run: "
                      "corners get rounded automatically")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        data = bpy.data.curves.new("Railing_Path", 'CURVE')
        data.dimensions = '3D'
        spline = data.splines.new('POLY')
        spline.points.add(1)
        spline.points[0].co = (0.0, 0.0, 0.0, 1.0)
        spline.points[1].co = (2.0, 0.0, 0.0, 1.0)

        curve_obj = bpy.data.objects.new("Railing_Path", data)
        context.collection.objects.link(curve_obj)
        curve_obj.location = context.scene.cursor.location

        for o in context.view_layer.objects:
            o.select_set(False)
        context.view_layer.objects.active = curve_obj
        curve_obj.select_set(True)

        if bpy.ops.railgen.new() != {'FINISHED'}:
            return {'CANCELLED'}

        # Leave the *path* active and in Edit Mode: that is what the user wants
        # to work on. The panel follows the curve back to its railing.
        for o in context.view_layer.objects:
            o.select_set(False)
        context.view_layer.objects.active = curve_obj
        curve_obj.select_set(True)
        # Select the free end before entering Edit Mode: once in, the spline
        # reference we hold points at the loaded-out copy and is empty.
        spline.points[0].select = False
        spline.points[1].select = True
        bpy.ops.object.mode_set(mode='EDIT')
        return {'FINISHED'}


class RAILGEN_OT_edit_path(bpy.types.Operator):
    bl_idname = "railgen.edit_path"
    bl_label = "Edit Path"
    bl_description = "Select the railing's curve and enter Edit Mode to move, add or extrude control points"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        railing = find_railing(context.active_object)
        return railing is not None and railing.railing_props.curve is not None

    def execute(self, context):
        curve_obj = find_railing(context.active_object).railing_props.curve
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for o in context.view_layer.objects:
            o.select_set(False)
        context.view_layer.objects.active = curve_obj
        curve_obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        return {'FINISHED'}


class RAILGEN_OT_freeze(bpy.types.Operator):
    bl_idname = "railgen.freeze"
    bl_label = "Freeze"
    bl_description = ("Disconnect this railing from the generator. The mesh is kept as is "
                      "and stops following its path; the parameters are gone for good "
                      "(Ctrl+Z to undo)")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return find_railing(context.active_object) is not None

    def execute(self, context):
        obj = find_railing(context.active_object)
        props = obj.railing_props
        curve_obj = props.curve

        # The mesh is already plain mesh data; only the link has to go.
        props.is_railing = False
        props.curve = None

        # Leave the active object on the frozen mesh, not on a path it no
        # longer drives.
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for o in context.view_layer.objects:
            o.select_set(False)
        context.view_layer.objects.active = obj
        obj.select_set(True)

        orphan = curve_obj is not None and not any(
            o.railing_props.curve == curve_obj for o in bpy.data.objects if is_railing(o))
        self.report({'INFO'}, f"'{obj.name}' frozen"
                    + (f" — path '{curve_obj.name}' is now unused" if orphan else ""))
        return {'FINISHED'}


class RAILGEN_OT_generate(bpy.types.Operator):
    bl_idname = "railgen.generate"
    bl_label = "Rebuild Railing"
    bl_description = "Rebuild the active railing from its curve and current parameters"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return find_railing(context.active_object) is not None

    def execute(self, context):
        obj = find_railing(context.active_object)
        try:
            regenerate(obj, context.evaluated_depsgraph_get())
        except Exception as exc:
            self.report({'ERROR'}, f"Generation failed: {exc}")
            return {'CANCELLED'}
        p = obj.railing_props
        self.report({'INFO'}, f"'{obj.name}' rebuilt ({p.stat_tris} tris)")
        return {'FINISHED'}


# ==============================================================
# UI Panel
# ==============================================================

class RAILGEN_PT_panel(bpy.types.Panel):
    bl_label = "Curve Railing"
    bl_idname = "RAILGEN_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Railing"

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        railing = find_railing(obj)
        if railing is None:
            layout.operator("railgen.new_path", text="New Railing Path", icon='ADD')
            if RAILGEN_OT_new.poll(context):
                layout.operator("railgen.new", text="From Active Curve", icon='OUTLINER_OB_CURVE')
            return

        props = railing.railing_props
        corners = path_is_corners(props.curve)

        layout.label(text=railing.name, icon='MOD_CURVE')
        row = layout.row(align=True)
        row.prop(props, "auto_update", toggle=True, icon='FILE_REFRESH')
        row.operator("railgen.generate", text="Rebuild", icon='MESH_DATA')
        layout.prop(props, "curve")
        row = layout.row(align=True)
        row.operator("railgen.edit_path", icon='EDITMODE_HLT')
        row.operator("railgen.freeze", icon='FREEZE')

        col = layout.column(align=True)
        col.prop(props, "height")
        col.prop(props, "rail_count")
        col.prop(props, "rail_radius")
        col.prop(props, "rail_segments")

        header, body = layout.panel("railgen_posts", default_closed=False)
        header.prop(props, "use_posts", text="Posts")
        if body is not None:
            body.enabled = props.use_posts
            col = body.column(align=True)
            col.prop(props, "post_spacing")
            col.prop(props, "post_radius")
            col.prop(props, "post_segments")
            col.prop(props, "post_sink")

        header, body = layout.panel("railgen_opt", default_closed=False)
        header.label(text="Optimization")
        if body is not None:
            col = body.column(align=True)
            col.prop(props, "max_angle")
            # The two path styles use different second knobs, showing both would
            # just leave one permanently inert.
            col.prop(props, "corner_radius" if corners else "max_length")

        header, body = layout.panel("railgen_result", default_closed=True)
        header.label(text="Result")
        if body is not None:
            col = body.column(align=True)
            col.label(text=f"Triangles: {props.stat_tris}")
            col.label(text=f"Vertices: {props.stat_verts}")
            col.label(text=f"Rail sections: {props.stat_sections}"
                           + ("" if corners else f" / {props.stat_dense} sampled"))
            col.label(text="Path: " + ("control points, corners rounded"
                                       if corners else "curve, adaptively simplified"))

        layout.prop(props, "material")


# ==============================================================
# Registration
# ==============================================================

classes = (
    RailingGenProperties,
    RAILGEN_OT_new,
    RAILGEN_OT_new_path,
    RAILGEN_OT_edit_path,
    RAILGEN_OT_freeze,
    RAILGEN_OT_generate,
    RAILGEN_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.railing_props = bpy.props.PointerProperty(type=RailingGenProperties)
    if _on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)


def unregister():
    if _on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update)
    if hasattr(bpy.types.Object, "railing_props"):
        del bpy.types.Object.railing_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


def _self_check():
    """The two bits that can silently go wrong: the adaptive simplifier and
    the tube's winding."""
    # Dead-straight run collapses to its endpoints.
    line = [Vector((x * 0.1, 0.0, 0.0)) for x in range(101)]
    assert simplify(line, False, math.radians(8), 100.0) == [line[0], line[-1]]
    # ...unless max_length forces sections.
    assert len(simplify(line, False, math.radians(8), 2.0)) in (6, 7)

    # A 90 degree arc turns 90 degrees: ~90/8 sections, whatever the sampling.
    arc = [Vector((math.cos(a * math.pi / 200), math.sin(a * math.pi / 200), 0.0))
           for a in range(101)]
    kept = simplify(arc, False, math.radians(8), 100.0)
    assert 11 <= len(kept) <= 13, len(kept)
    # Doubling the input density must not change the output much.
    arc2 = [Vector((math.cos(a * math.pi / 400), math.sin(a * math.pi / 400), 0.0))
            for a in range(201)]
    assert abs(len(simplify(arc2, False, math.radians(8), 100.0)) - len(kept)) <= 1

    # Fillet: a right-angle corner becomes a true arc of the asked radius.
    r, ma = 0.5, math.radians(9.0)
    corner = [Vector((0, 0, 0)), Vector((4, 0, 0)), Vector((4, 4, 0))]
    arc = fillet(corner, False, r, ma)
    assert arc[0] == corner[0] and arc[-1] == corner[-1]
    # 90 degrees at 9 degrees a step: 10 steps, 11 arc points, ends included.
    assert len(arc) == 13, len(arc)
    # Tangency: the arc leaves and rejoins the straight legs exactly at distance
    # r from the corner (tan(45) == 1), and every arc point is r from the centre.
    assert abs((arc[1] - corner[1]).length - r) < 1e-5
    assert abs((arc[-2] - corner[1]).length - r) < 1e-5
    centre = Vector((4 - r, r, 0))
    for p in arc[1:-1]:
        assert abs((p - centre).length - r) < 1e-5, (p, (p - centre).length)
    # Straight run through a collinear "corner" stays 2 points after dedupe.
    assert len(fillet([Vector((0, 0, 0)), Vector((1, 0, 0)), Vector((2, 0, 0))],
                      False, r, ma)) == 3
    # Radius too big for the legs shrinks instead of overshooting.
    tight = [Vector((0, 0, 0)), Vector((1, 0, 0)), Vector((1, 1, 0))]
    got = fillet(tight, False, 10.0, ma)
    assert abs((got[1] - tight[1]).length - 0.5) < 1e-5, (got[1] - tight[1]).length
    # Vertical corner (a ramp turning into a landing) must not blow up the frame.
    assert len(fillet([Vector((0, 0, 0)), Vector((2, 0, 0)), Vector((2, 0, 2))],
                      False, r, ma)) == 13
    # Cyclic square: 4 corners, no leftover control point, no duplicates.
    sq = [Vector((0, 0, 0)), Vector((4, 0, 0)), Vector((4, 4, 0)), Vector((0, 4, 0))]
    loop = fillet(sq, True, r, ma)
    assert len(loop) == 4 * 11, len(loop)
    assert min((loop[i] - loop[i - 1]).length for i in range(len(loop))) > 1e-6

    # Capped tube: closed, manifold, outward normals (positive volume).
    segs, r, length = 16, 0.5, 4.0
    verts, faces, smooth = sweep([Vector((0, 0, 0)), Vector((length, 0, 0))], r, segs)
    assert smooth == segs and len(faces) == segs + 2
    edges = {}
    for f in faces:
        for i in range(len(f)):
            e = frozenset((f[i], f[(i + 1) % len(f)]))
            edges[e] = edges.get(e, 0) + 1
    assert set(edges.values()) == {2}, "non-manifold tube"
    assert len(verts) - len(edges) + len(faces) == 2, "tube is not closed"
    vol = 0.0
    for f in faces:
        for i in range(1, len(f) - 1):
            a, b, c = verts[f[0]], verts[f[i]], verts[f[i + 1]]
            vol += a.dot(b.cross(c)) / 6.0
    exact = 0.5 * segs * math.sin(2 * math.pi / segs) * r * r * length   # inscribed prism
    assert abs(vol - exact) < 1e-4, f"{vol} != {exact} (inward normals?)"

    # Uniform resampling hits both ends and divides evenly.
    out = resample_uniform(line, False, 1.1)
    assert len(out) == 10 and (out[0] - line[0]).length < 1e-9 \
        and (out[-1] - line[-1]).length < 1e-9
    print("curve_railing_generator: self-check OK")


if __name__ == "__main__":
    _self_check()
    register()
