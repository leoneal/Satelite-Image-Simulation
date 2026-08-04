"""Minimal test: camera 100m from FBX model, bright emission."""
import bpy, os, math
from mathutils import Vector, Matrix

base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fbx = os.path.join(base, 'data', 'sat_models', 'DSP', '1323.fbx')

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

bpy.ops.import_scene.fbx(filepath=fbx)

# Remove non-mesh
for obj in list(bpy.data.objects):
    if obj.type != 'MESH':
        bpy.data.objects.remove(obj, do_unlink=True)

meshes = [obj for obj in bpy.data.objects if obj.type == 'MESH']
print(f"Meshes: {[m.name for m in meshes]}")

# Process each mesh
for obj in meshes:
    # Make active
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    # Clear materials
    obj.data.materials.clear()

    # Apply current transform
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    print(f"After apply: {obj.name}, loc={obj.location}, scale={obj.scale[:]}")
    bbox = [obj.matrix_world @ v.co for v in obj.data.vertices]
    xs = [v.x for v in bbox]; ys = [v.y for v in bbox]; zs = [v.z for v in bbox]
    print(f"  bbox: ({min(xs):.3f}, {min(ys):.3f}, {min(zs):.3f}) -> ({max(xs):.3f}, {max(ys):.3f}, {max(zs):.3f})")
    dims = (max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs))
    print(f"  dims: {dims[0]:.3f} x {dims[1]:.3f} x {dims[2]:.3f}")

    # Scale to 10m for visibility, then km
    target_size = 10.0  # meters
    current_size = max(dims)
    meter_scale = target_size / current_size  # scale to 10m
    obj.scale = (meter_scale, meter_scale, meter_scale)
    bpy.ops.object.transform_apply(scale=True)
    print(f"  after scale to 10m: dims = {max(dims)*meter_scale:.2f}m")

    # Now scale to km
    KM = 0.001
    obj.scale = (KM, KM, KM)
    bpy.ops.object.transform_apply(scale=True)
    print(f"  after KM scale: scale={obj.scale[:]}, location={obj.location}")

    # Add Principled BSDF (shows surface detail with lighting)
    mat = bpy.data.materials.new('test_bsdf')
    nodes = mat.node_tree.nodes; nodes.clear()
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = (0.7, 0.7, 0.7, 1)  # grey
    bsdf.inputs['Roughness'].default_value = 0.3
    bsdf.inputs['Metallic'].default_value = 0.2
    out = nodes.new('ShaderNodeOutputMaterial')
    mat.node_tree.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    obj.data.materials.append(mat)
    obj.name = 'satellite'
    obj.pass_index = 1
    obj.select_set(False)

# Add sun light from 45-degree angle, moderate energy
bpy.ops.object.light_add(type='SUN', location=(0.3, 0.3, 0.2))
sun = bpy.context.active_object
sun.data.energy = 1.5

# Camera 0.02 km (20m) to the side for close-up detail
import math
cam_loc = (0, 0.02, 0)
bpy.ops.object.camera_add(location=cam_loc)
cam = bpy.context.active_object
cam.data.angle = math.radians(30)
cam.data.clip_start = 0.00001
cam.data.clip_end = 1000
# Point camera at origin
from mathutils import Vector
direction = Vector((0, 0, 0)) - Vector(cam_loc)
z_axis = -direction.normalized()
up = Vector((0, 0, 1))
if abs(z_axis.dot(up)) > 0.9999: up = Vector((1, 0, 0))
x_axis = up.cross(z_axis).normalized()
y_axis = z_axis.cross(x_axis).normalized()
rot = Matrix(((x_axis.x, y_axis.x, z_axis.x),
              (x_axis.y, y_axis.y, z_axis.y),
              (x_axis.z, y_axis.z, z_axis.z))).to_4x4()
cam.matrix_world = Matrix.Translation(cam_loc) @ rot
bpy.context.scene.camera = cam

# Satellite at origin
for obj in meshes:
    obj.location = (0, 0, 0)

# World
world = bpy.context.scene.world
nodes_w = world.node_tree.nodes; nodes_w.clear()
bg = nodes_w.new('ShaderNodeBackground')
bg.inputs['Color'].default_value = (0, 0, 0, 1)
out_w = nodes_w.new('ShaderNodeOutputWorld')
world.node_tree.links.new(bg.outputs['Background'], out_w.inputs['Surface'])

# Render
bpy.context.scene.render.engine = 'CYCLES'
bpy.context.scene.cycles.samples = 32
bpy.context.scene.render.resolution_x = 1024
bpy.context.scene.render.resolution_y = 1024
bpy.context.scene.render.filepath = os.path.join(base, 'output', 'images', 'fbx_side_view.png')
bpy.ops.render.render(write_still=True)
print("Done")
