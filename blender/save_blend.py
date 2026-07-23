"""
Quick: render first frame, save .blend for GUI inspection.
"""
import bpy, csv, os, math
from mathutils import Vector, Matrix, Quaternion

base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ephem = os.path.join(base, 'output', 'ephemeris')

def load_row(fp):
    with open(fp) as f:
        return {k: float(v) for k, v in csv.DictReader(f).__next__().items()}

obs = load_row(os.path.join(ephem, 'observer_state.csv'))
tgt = load_row(os.path.join(ephem, 'target_state.csv'))
sun = load_row(os.path.join(ephem, 'sun_state.csv'))

KM = 0.001
S = KM

obs_p = Vector((obs['pos_x_m']*KM, obs['pos_y_m']*KM, obs['pos_z_m']*KM))
tgt_p = Vector((tgt['pos_x_m']*KM, tgt['pos_y_m']*KM, tgt['pos_z_m']*KM))
sun_p = Vector((sun['pos_x_m']*KM, sun['pos_y_m']*KM, sun['pos_z_m']*KM))

print(f"Distance: {(tgt_p - obs_p).length:.1f} km")

# Clear
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# --- Satellite model ---
parts = []
for name, loc, sc, color, pid in [
    ('body',        (0,       0,      0),     (2.0, 1.0, 0.75), (0.7,0.7,0.7,1), 1),
    ('panel_left',  (-3.0*S,  0,      0.1*S), (2.0, 0.5, 0.02), (0.1,0.2,0.5,1), 2),
    ('panel_right', ( 3.0*S,  0,      0.1*S), (2.0, 0.5, 0.02), (0.1,0.2,0.5,1), 3),
    ('antenna',     ( 0,      0,      1.0*S), (1.0, 1.0, 0.3),  (0.9,0.9,0.9,1), 4),
    ('thruster',    ( 0,      0,     -1.0*S), (1.0, 1.0, 1.0),  (0.4,0.3,0.3,1), 5),
]:
    if 'antenna' in name or 'thruster' in name:
        if 'antenna' in name:
            bpy.ops.mesh.primitive_cylinder_add(radius=0.4*sc[0], depth=0.5*sc[2], location=loc)
        else:
            bpy.ops.mesh.primitive_cylinder_add(radius=0.3*sc[0], depth=0.5*sc[2], location=loc)
    else:
        bpy.ops.mesh.primitive_cube_add(size=2.0*S, location=loc)
        bpy.context.active_object.scale = sc
        bpy.ops.object.transform_apply(scale=True)

    obj = bpy.context.active_object
    obj.name = name
    obj.pass_index = pid
    parts.append(obj)

    mat = bpy.data.materials.new(name + '_mat')
    nodes = mat.node_tree.nodes; nodes.clear()
    emit = nodes.new('ShaderNodeEmission')
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    mix = nodes.new('ShaderNodeMixShader')
    emit.inputs['Color'].default_value = color
    emit.inputs['Strength'].default_value = 10.0
    bsdf.inputs['Base Color'].default_value = color
    bsdf.inputs['Roughness'].default_value = 0.5
    mix.inputs['Fac'].default_value = 1.0
    out = nodes.new('ShaderNodeOutputMaterial')
    mat.node_tree.links.new(emit.outputs['Emission'], mix.inputs[1])
    mat.node_tree.links.new(bsdf.outputs['BSDF'], mix.inputs[2])
    mat.node_tree.links.new(mix.outputs['Shader'], out.inputs['Surface'])
    obj.data.materials.append(mat)

# Place satellite at target position
tgt_q = Quaternion((tgt['qw'], tgt['qx'], tgt['qy'], tgt['qz']))
for p in parts:
    offset = p.location.copy()
    p.location = tgt_p + tgt_q @ offset
    p.rotation_mode = 'QUATERNION'
    p.rotation_quaternion = tgt_q

# Camera
bpy.ops.object.camera_add(location=obs_p)
cam = bpy.context.active_object
cam.name = 'SensorCamera'
cam.data.angle = math.radians(0.117)
cam.data.clip_start = 0.00001
cam.data.clip_end = 200000.0
direction = (tgt_p - obs_p).normalized()
cam_z = -direction; cam_up = Vector((0,0,1))
if abs(cam_z.dot(cam_up)) > 0.9999: cam_up = Vector((1,0,0))
cam_x = cam_up.cross(cam_z).normalized()
cam_y = cam_z.cross(cam_x).normalized()
rot = Matrix(((cam_x.x,cam_y.x,cam_z.x),(cam_x.y,cam_y.y,cam_z.y),(cam_x.z,cam_y.z,cam_z.z))).to_4x4()
cam.matrix_world = Matrix.Translation(obs_p) @ rot
bpy.context.scene.camera = cam

# Sun
bpy.ops.object.light_add(type='SUN')
sun_obj = bpy.context.active_object
sun_obj.data.energy = 20
sun_dir = sun_p.normalized()
z_sun = sun_dir; up_sun = Vector((0,0,1))
if abs(z_sun.dot(up_sun)) > 0.9999: up_sun = Vector((1,0,0))
x_sun = up_sun.cross(z_sun).normalized()
y_sun = z_sun.cross(x_sun).normalized()
sun_rot = Matrix(((x_sun.x,y_sun.x,z_sun.x),(x_sun.y,y_sun.y,z_sun.y),(x_sun.z,y_sun.z,z_sun.z))).to_4x4()
sun_obj.matrix_world = sun_rot

# Earth
bpy.ops.mesh.primitive_uv_sphere_add(radius=6371.0, location=(0,0,0))
earth = bpy.context.active_object
earth.name = 'Earth'
mat_e = bpy.data.materials.new('EarthMat')
nodes_e = mat_e.node_tree.nodes; nodes_e.clear()
bsdf_e = nodes_e.new('ShaderNodeBsdfPrincipled')
bsdf_e.inputs['Base Color'].default_value = (0.1, 0.2, 0.5, 1.0)
out_e = nodes_e.new('ShaderNodeOutputMaterial')
mat_e.node_tree.links.new(bsdf_e.outputs['BSDF'], out_e.inputs['Surface'])
earth.data.materials.append(mat_e)

# Background
world = bpy.context.scene.world
nodes_w = world.node_tree.nodes; nodes_w.clear()
bg = nodes_w.new('ShaderNodeBackground')
bg.inputs['Color'].default_value = (0.001, 0.001, 0.005, 1)
out_w = nodes_w.new('ShaderNodeOutputWorld')
world.node_tree.links.new(bg.outputs['Background'], out_w.inputs['Surface'])

# Render settings
bpy.context.scene.render.engine = 'CYCLES'
bpy.context.scene.cycles.samples = 16
bpy.context.scene.render.resolution_x = 2048
bpy.context.scene.render.resolution_y = 2048

# Save
out_path = os.path.join(base, 'output', 'scene_frame0.blend')
bpy.ops.wm.save_as_mainfile(filepath=out_path)
print(f"\nSaved: {out_path}")
print("Open in Blender GUI. Run render_scene.py from Scripting tab to test render.")
