"""
Gradually increase distance to find where the satellite disappears.
Renders at 4 distances: 0.1km, 1km, 10km, 117km.
"""
import bpy, csv, os, math
from mathutils import Vector, Matrix

base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ephem = os.path.join(base, 'output', 'ephemeris')

# Load frame 0
def load_row(fp):
    with open(fp) as f:
        return {k: float(v) for k, v in csv.DictReader(f).__next__().items()}

obs = load_row(os.path.join(ephem, 'observer_state.csv'))
tgt = load_row(os.path.join(ephem, 'target_state.csv'))

obs_p = Vector((obs['pos_x_m'], obs['pos_y_m'], obs['pos_z_m']))
tgt_p = Vector((tgt['pos_x_m'], tgt['pos_y_m'], tgt['pos_z_m']))
cam_dir = (tgt_p - obs_p).normalized()

KM = 0.001
obs_km = obs_p * KM
tgt_km = tgt_p * KM

print(f"Actual distance: {(tgt_km - obs_km).length:.1f} km")

distances = [0.1, 1.0, 10.0, 117.0]  # km

for dist_idx, dist_km in enumerate(distances):
    print(f"\n=== Distance: {dist_km} km ===")

    # Clear
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

    # Remove old materials
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)

    # Place satellite at specified distance
    tgt_pos = obs_km + cam_dir * dist_km

    # Create emissive cube (4m = 0.004 km wide in real scale)
    # Use km units: cube size = 0.004 km
    bpy.ops.mesh.primitive_cube_add(size=0.004, location=tgt_pos)  # 4m cube in km
    cube = bpy.context.active_object
    cube.name = f'Target_{dist_km}km'
    mat = bpy.data.materials.new('Emissive')
    nodes = mat.node_tree.nodes; nodes.clear()
    emit = nodes.new('ShaderNodeEmission')
    emit.inputs['Color'].default_value = (1, 0.5, 0, 1)  # Bright orange
    emit.inputs['Strength'].default_value = 10.0
    out = nodes.new('ShaderNodeOutputMaterial')
    mat.node_tree.links.new(emit.outputs['Emission'], out.inputs['Surface'])
    cube.data.materials.append(mat)

    # Angular size
    ang = math.degrees(math.atan2(0.004, dist_km))
    print(f"  Angular size: {ang:.4f} deg (FOV=0.117 deg)")

    # Camera
    bpy.ops.object.camera_add(location=obs_km)
    cam = bpy.context.active_object
    cam.name = 'Cam'
    cam.data.angle = math.radians(0.117)
    cam.data.clip_start = 0.00001  # 10m
    cam.data.clip_end = 200000.0
    # Point at target
    direction = (tgt_pos - obs_km).normalized()
    cam_z = -direction
    cam_up = Vector((0, 0, 1))
    if abs(cam_z.dot(cam_up)) > 0.9999: cam_up = Vector((1, 0, 0))
    cam_x = cam_up.cross(cam_z).normalized()
    cam_y = cam_z.cross(cam_x).normalized()
    rot = Matrix(((cam_x.x, cam_y.x, cam_z.x),
                  (cam_x.y, cam_y.y, cam_z.y),
                  (cam_x.z, cam_y.z, cam_z.z))).to_4x4()
    cam.matrix_world = Matrix.Translation(obs_km) @ rot
    bpy.context.scene.camera = cam

    # Background
    world = bpy.context.scene.world
    nodes_w = world.node_tree.nodes; nodes_w.clear()
    bg = nodes_w.new('ShaderNodeBackground')
    bg.inputs['Color'].default_value = (0.005, 0.005, 0.01, 1)
    out_w = nodes_w.new('ShaderNodeOutputWorld')
    world.node_tree.links.new(bg.outputs['Background'], out_w.inputs['Surface'])

    # Render
    bpy.context.scene.render.engine = 'CYCLES'
    bpy.context.scene.cycles.samples = 64
    bpy.context.scene.cycles.use_denoising = False  # No denoising for small target
    bpy.context.scene.render.resolution_x = 1024
    bpy.context.scene.render.resolution_y = 1024
    out_path = os.path.join(base, 'output', 'images', f'dist_{dist_km:.0f}km.png')
    bpy.context.scene.render.filepath = out_path
    bpy.context.scene.render.image_settings.file_format = 'PNG'
    bpy.ops.render.render(write_still=True)

    # Report
    px_per_deg = 1024 / 0.117
    target_px = ang * px_per_deg
    print(f"  Expected pixels: {target_px:.0f}")
    print(f"  Rendered: {out_path}")

print("\nDone. Check the 4 images.")
