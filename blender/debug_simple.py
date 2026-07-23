"""
Simplest possible debug: one satellite, one camera, one sun.
No Earth, no scaling, everything in meters.
"""
import bpy, csv, os, math
from mathutils import Vector, Matrix, Quaternion

# Paths
base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ephem = os.path.join(base, 'output', 'ephemeris')

# Load frame 0
def load_row(fp):
    with open(fp) as f:
        return {k: float(v) for k, v in csv.DictReader(f).__next__().items()}

obs = load_row(os.path.join(ephem, 'observer_state.csv'))
tgt = load_row(os.path.join(ephem, 'target_state.csv'))
sun = load_row(os.path.join(ephem, 'sun_state.csv'))

obs_p = Vector((obs['pos_x_m'], obs['pos_y_m'], obs['pos_z_m']))
tgt_p = Vector((tgt['pos_x_m'], tgt['pos_y_m'], tgt['pos_z_m']))
sun_p = Vector((sun['pos_x_m'], sun['pos_y_m'], sun['pos_z_m']))

print(f"Observer:  {obs_p}")
print(f"Target:    {tgt_p}")
print(f"Distance:  {(tgt_p - obs_p).length / 1000:.1f} km")
print(f"Sun:       {sun_p}, magnitude: {sun_p.length / 1.496e11:.2f} AU")

# Clear scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# === Simple test: make a BIG satellite so we can definitely see it ===
# Place a large bright sphere at the target position
bpy.ops.mesh.primitive_uv_sphere_add(radius=50.0, location=tgt_p)  # 50m bright ball
test_ball = bpy.context.active_object
test_ball.name = 'TestTarget'
mat = bpy.data.materials.new('Bright')
nodes = mat.node_tree.nodes; nodes.clear()
emit = nodes.new('ShaderNodeEmission')
emit.inputs['Color'].default_value = (1.0, 1.0, 0.5, 1.0)  # Bright yellow
emit.inputs['Strength'].default_value = 10.0
out = nodes.new('ShaderNodeOutputMaterial')
mat.node_tree.links.new(emit.outputs['Emission'], out.inputs['Surface'])
test_ball.data.materials.append(mat)

# === Camera ===
bpy.ops.object.camera_add()
cam = bpy.context.active_object
cam.name = 'SensorCamera'
cam.location = obs_p
cam.data.angle = math.radians(0.117)
cam.data.sensor_fit = 'HORIZONTAL'
cam.data.clip_start = 100.0       # 100 meters
cam.data.clip_end = 1.0e9         # 1 billion meters

# Point camera at target
direction = (tgt_p - obs_p).normalized()
track = cam.constraints.new('TRACK_TO')
track.target = test_ball
track.track_axis = 'TRACK_NEGATIVE_Z'
track.up_axis = 'UP_Z'

bpy.context.scene.camera = cam

# === Sun ===
bpy.ops.object.light_add(type='SUN')
sun_obj = bpy.context.active_object
sun_obj.name = 'Sun'
sun_obj.data.energy = 10.0

# Make sun point toward Earth center from sun direction
bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0, 0, 0))
earth_center = bpy.context.active_object
earth_center.name = 'EarthCenter'

# Sun lamp: use Track To to point its -Z toward earth center
# The sun lamp's rotation will then make light come from sun direction
track_sun = sun_obj.constraints.new('TRACK_TO')
track_sun.target = earth_center
track_sun.track_axis = 'TRACK_NEGATIVE_Z'
track_sun.up_axis = 'UP_Y'
sun_obj.location = sun_p * 0.1  # Put sun closer but keep direction correct

# === World background ===
world = bpy.context.scene.world
nodes_w = world.node_tree.nodes; nodes_w.clear()
bg = nodes_w.new('ShaderNodeBackground')
bg.inputs['Color'].default_value = (0.01, 0.01, 0.02, 1.0)
bg.inputs['Strength'].default_value = 1.0
out_w = nodes_w.new('ShaderNodeOutputWorld')
world.node_tree.links.new(bg.outputs['Background'], out_w.inputs['Surface'])

# === Render settings ===
bpy.context.scene.render.engine = 'CYCLES'
bpy.context.scene.cycles.samples = 32
bpy.context.scene.render.resolution_x = 512
bpy.context.scene.render.resolution_y = 512
bpy.context.scene.render.filepath = os.path.join(base, 'output', 'images', 'debug_simple.png')
bpy.context.scene.render.image_settings.file_format = 'PNG'

# Enable denoising
bpy.context.scene.cycles.use_denoising = True

# === Save and render ===
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(base, 'output', 'debug_simple.blend'))
print("\nSaved debug_simple.blend")

bpy.ops.render.render(write_still=True)
print(f"Rendered: {bpy.context.scene.render.filepath}")
print("\nNow open debug_simple.blend in Blender GUI to inspect.")
