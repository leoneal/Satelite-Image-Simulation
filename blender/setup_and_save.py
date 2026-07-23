"""
Quick setup script: loads frame 0, saves as .blend for GUI inspection.
Run: blender -b -P setup_and_save.py
"""
import bpy, csv, os, sys, math
from mathutils import Vector, Matrix, Quaternion

ephem_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'output', 'ephemeris')

KM_SCALE = 0.001
EARTH_RADIUS = 6371.0

# Load frame 0
def load_row(filepath, idx=0):
    rows = []
    with open(filepath) as f:
        for row in csv.DictReader(f):
            rows.append({k: float(v) for k, v in row.items()})
    return rows[idx]

obs = load_row(os.path.join(ephem_dir, 'observer_state.csv'), 0)
tgt = load_row(os.path.join(ephem_dir, 'target_state.csv'), 0)
sun = load_row(os.path.join(ephem_dir, 'sun_state.csv'), 0)

obs_pos = Vector((obs['pos_x_m']*KM_SCALE, obs['pos_y_m']*KM_SCALE, obs['pos_z_m']*KM_SCALE))
tgt_pos = Vector((tgt['pos_x_m']*KM_SCALE, tgt['pos_y_m']*KM_SCALE, tgt['pos_z_m']*KM_SCALE))
sun_pos = Vector((sun['pos_x_m']*KM_SCALE, sun['pos_y_m']*KM_SCALE, sun['pos_z_m']*KM_SCALE))

print(f"Observer: {obs_pos}")
print(f"Target:   {tgt_pos}")
print(f"Distance: {(tgt_pos - obs_pos).length:.1f} km")

# Clear scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# Earth
bpy.ops.mesh.primitive_uv_sphere_add(radius=EARTH_RADIUS, location=(0,0,0))
earth = bpy.context.active_object
earth.name = 'Earth'
mat_e = bpy.data.materials.new('EarthMat')
nodes_e = mat_e.node_tree.nodes; nodes_e.clear()
bsdf_e = nodes_e.new('ShaderNodeBsdfPrincipled')
bsdf_e.inputs['Base Color'].default_value = (0.1, 0.2, 0.5, 1.0)
out_e = nodes_e.new('ShaderNodeOutputMaterial')
mat_e.node_tree.links.new(bsdf_e.outputs['BSDF'], out_e.inputs['Surface'])
earth.data.materials.append(mat_e)

# Satellite model
bpy.ops.object.empty_add(type='PLAIN_AXES')
sat = bpy.context.active_object
sat.name = 'Satellite'
sat.scale = (KM_SCALE, KM_SCALE, KM_SCALE)

parts = [
    ('body', 'cube', (0,0,0), (2,1,0.75), (0.6,0.6,0.6,1), 1),
    ('panel_left', 'cube', (-3,0,0.1), (2,0.5,0.02), (0.1,0.15,0.3,1), 2),
    ('panel_right', 'cube', (3,0,0.1), (2,0.5,0.02), (0.1,0.15,0.3,1), 3),
    ('antenna', 'cylinder', (0,0,1), (1,1,0.3), (0.8,0.8,0.8,1), 4),
    ('thruster', 'cylinder', (0,0,-1), (1,1,1), (0.3,0.3,0.3,1), 5),
]
for name, shape, loc, scale, color, pid in parts:
    if shape == 'cube':
        bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    else:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.4, depth=0.5, location=loc)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    obj.parent = sat
    obj.pass_index = pid
    mat = bpy.data.materials.new(name + '_mat')
    nodes = mat.node_tree.nodes; nodes.clear()
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = color
    out = nodes.new('ShaderNodeOutputMaterial')
    mat.node_tree.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    obj.data.materials.append(mat)

# Place satellite
sat.location = tgt_pos
q = Quaternion((tgt['qw'], tgt['qx'], tgt['qy'], tgt['qz']))
sat.rotation_mode = 'QUATERNION'
sat.rotation_quaternion = q

# Camera at observer, looking at target
bpy.ops.object.camera_add()
cam = bpy.context.active_object
cam.name = 'SensorCamera'
cam.location = obs_pos
cam.data.angle = math.radians(0.117)
cam.data.sensor_fit = 'HORIZONTAL'
cam.data.clip_start = 0.01
cam.data.clip_end = 200000.0
direction = (tgt_pos - obs_pos).normalized()
z_axis = -direction
up = Vector((0,0,1))
if abs(z_axis.dot(up)) > 0.9999: up = Vector((1,0,0))
x_axis = up.cross(z_axis).normalized()
y_axis = z_axis.cross(x_axis).normalized()
rot = Matrix(((x_axis.x,y_axis.x,z_axis.x),(x_axis.y,y_axis.y,z_axis.y),(x_axis.z,y_axis.z,z_axis.z))).to_4x4()
cam.matrix_world = Matrix.Translation(obs_pos) @ rot
bpy.context.scene.camera = cam

# Sun light
bpy.ops.object.light_add(type='SUN')
sun_obj = bpy.context.active_object
sun_obj.name = 'Sun'
sun_obj.data.energy = 8.0
sun_dir = sun_pos.normalized()
z_sun = -sun_dir
up_sun = Vector((0,0,1))
if abs(z_sun.dot(up_sun)) > 0.9999: up_sun = Vector((1,0,0))
x_sun = up_sun.cross(z_sun).normalized()
y_sun = z_sun.cross(x_sun).normalized()
rot_sun = Matrix(((x_sun.x,y_sun.x,z_sun.x),(x_sun.y,y_sun.y,z_sun.y),(x_sun.z,y_sun.z,z_sun.z))).to_4x4()
sun_obj.matrix_world = rot_sun

# Background
world = bpy.context.scene.world
nodes_w = world.node_tree.nodes; nodes_w.clear()
bg = nodes_w.new('ShaderNodeBackground')
bg.inputs['Color'].default_value = (0.001, 0.001, 0.005, 1.0)
bg.inputs['Strength'].default_value = 1.0
out_w = nodes_w.new('ShaderNodeOutputWorld')
world.node_tree.links.new(bg.outputs['Background'], out_w.inputs['Surface'])

# Render settings
bpy.context.scene.render.engine = 'CYCLES'
bpy.context.scene.cycles.samples = 32
bpy.context.scene.render.resolution_x = 2048
bpy.context.scene.render.resolution_y = 2048
bpy.context.scene.render.filepath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'output', 'images', 'debug_frame0.png')
bpy.context.scene.render.image_settings.file_format = 'PNG'

# Set viewport shading to rendered
for area in bpy.context.screen.areas:
    if area.type == 'VIEW_3D':
        for space in area.spaces:
            if space.type == 'VIEW_3D':
                space.shading.type = 'RENDERED'
                break

# Save blend file
blend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'output', 'debug_scene.blend')
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
print(f"\nSaved: {blend_path}")
print("Open this file in Blender GUI to inspect the scene.")
