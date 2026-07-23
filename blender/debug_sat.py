"""
Place bright target at actual satellite position, camera at observer position.
Use direct rotation math (same approach as working closeup test).
"""
import bpy, csv, os, math
from mathutils import Vector, Matrix

base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ephem = os.path.join(base, 'output', 'ephemeris')

def load_row(fp):
    with open(fp) as f:
        return {k: float(v) for k, v in csv.DictReader(f).__next__().items()}

obs = load_row(os.path.join(ephem, 'observer_state.csv'))
tgt = load_row(os.path.join(ephem, 'target_state.csv'))
sun = load_row(os.path.join(ephem, 'sun_state.csv'))

obs_p = Vector((obs['pos_x_m'], obs['pos_y_m'], obs['pos_z_m']))
tgt_p = Vector((tgt['pos_x_m'], tgt['pos_y_m'], tgt['pos_z_m']))
sun_p = Vector((sun['pos_x_m'], sun['pos_y_m'], sun['pos_z_m']))

print(f"Observer: {obs_p}")
print(f"Target:   {tgt_p}")
print(f"Distance: {(tgt_p - obs_p).length/1000:.1f} km")
print(f"Dir obs->tgt: {(tgt_p - obs_p).normalized()}")

# Clear
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# Bright cube at target position (100m size so definitely visible at 117km)
bpy.ops.mesh.primitive_cube_add(size=100, location=tgt_p)
cube = bpy.context.active_object
cube.name = 'Target'
mat = bpy.data.materials.new('Bright')
nodes = mat.node_tree.nodes; nodes.clear()
emit = nodes.new('ShaderNodeEmission')
emit.inputs['Color'].default_value = (1, 0.8, 0.2, 1)
emit.inputs['Strength'].default_value = 5
out = nodes.new('ShaderNodeOutputMaterial')
mat.node_tree.links.new(emit.outputs['Emission'], out.inputs['Surface'])
cube.data.materials.append(mat)

# Camera at observer
bpy.ops.object.camera_add(location=obs_p)
cam = bpy.context.active_object
cam.name = 'Cam'
cam.data.angle = math.radians(0.117)
cam.data.sensor_fit = 'HORIZONTAL'
cam.data.clip_start = 100.0
cam.data.clip_end = 1.0e9

# Direct rotation: make camera -Z point toward target
# Camera looks down -Z, so camera +Z = (obs - tgt).normalized()
direction = (tgt_p - obs_p).normalized()   # obs -> tgt
cam_z = -direction                          # camera local +Z
cam_up = Vector((0, 0, 1))                 # world Z is "up"
if abs(cam_z.dot(cam_up)) > 0.9999:
    cam_up = Vector((1, 0, 0))
cam_x = cam_up.cross(cam_z).normalized()
cam_y = cam_z.cross(cam_x).normalized()
# Columns of rot matrix = local X, Y, Z axes in world space
rot = Matrix((
    (cam_x.x, cam_y.x, cam_z.x),
    (cam_x.y, cam_y.y, cam_z.y),
    (cam_x.z, cam_y.z, cam_z.z)
)).to_4x4()
cam.matrix_world = Matrix.Translation(obs_p) @ rot

bpy.context.scene.camera = cam

# Verify camera pointing
view_dir = -cam_z
dot = view_dir.dot(direction)
print(f"Camera view dot product with target direction: {dot:.6f} (should be ~1.0)")

# Sun
bpy.ops.object.light_add(type='SUN')
sun_obj = bpy.context.active_object
sun_obj.data.energy = 5
sun_dir = sun_p.normalized()
sun_z = sun_dir  # Sun +Z toward sun position
sun_up = Vector((0, 0, 1))
if abs(sun_z.dot(sun_up)) > 0.9999: sun_up = Vector((1, 0, 0))
sun_x = sun_up.cross(sun_z).normalized()
sun_y = sun_z.cross(sun_x).normalized()
sun_rot = Matrix((
    (sun_x.x, sun_y.x, sun_z.x),
    (sun_x.y, sun_y.y, sun_z.y),
    (sun_x.z, sun_y.z, sun_z.z)
)).to_4x4()
sun_obj.matrix_world = sun_rot

# Background
world = bpy.context.scene.world
nodes_w = world.node_tree.nodes; nodes_w.clear()
bg = nodes_w.new('ShaderNodeBackground')
bg.inputs['Color'].default_value = (0.01, 0.01, 0.02, 1)
bg.inputs['Strength'].default_value = 1
out_w = nodes_w.new('ShaderNodeOutputWorld')
world.node_tree.links.new(bg.outputs['Background'], out_w.inputs['Surface'])

# Render
bpy.context.scene.render.engine = 'CYCLES'
bpy.context.scene.cycles.samples = 32
bpy.context.scene.render.resolution_x = 512
bpy.context.scene.render.resolution_y = 512
bpy.context.scene.render.filepath = os.path.join(base, 'output', 'images', 'sat_target.png')
bpy.context.scene.render.image_settings.file_format = 'PNG'

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(base, 'output', 'debug_sat.blend'))
bpy.ops.render.render(write_still=True)
print(f"\nRendered. Camera dot product = {dot:.6f}")
print("Open debug_sat.blend in GUI to inspect.")
