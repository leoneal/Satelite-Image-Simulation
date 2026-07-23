"""
Minimal test: camera at origin, bright cube 100m in front.
If this is black, the problem is Blender itself.
"""
import bpy, os, math

base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Clear scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# Bright cube at (0, 100, 0) - 100m in front
bpy.ops.mesh.primitive_cube_add(size=5, location=(0, 100, 0))
cube = bpy.context.active_object
cube.name = 'Target'
mat = bpy.data.materials.new('Bright')
nodes = mat.node_tree.nodes; nodes.clear()
emit = nodes.new('ShaderNodeEmission')
emit.inputs['Color'].default_value = (1, 0.8, 0.2, 1)  # Orange
emit.inputs['Strength'].default_value = 5
out = nodes.new('ShaderNodeOutputMaterial')
mat.node_tree.links.new(emit.outputs['Emission'], out.inputs['Surface'])
cube.data.materials.append(mat)

# Camera at origin, looking along +Y
bpy.ops.object.camera_add(location=(0, 0, 0))
cam = bpy.context.active_object
cam.name = 'Cam'
cam.rotation_euler = (0, 0, 0)  # Default: looks down -Z
# Rotate to look down +Y
cam.rotation_euler = (math.pi/2, 0, 0)
cam.data.angle = math.radians(30)  # Wide FOV
cam.data.clip_start = 0.1
cam.data.clip_end = 10000
bpy.context.scene.camera = cam

# Sun
bpy.ops.object.light_add(type='SUN', location=(0, 0, 10))
sun = bpy.context.active_object
sun.data.energy = 5

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
bpy.context.scene.cycles.samples = 16
bpy.context.scene.render.resolution_x = 512
bpy.context.scene.render.resolution_y = 512
bpy.context.scene.render.filepath = os.path.join(base, 'output', 'images', 'closeup.png')
bpy.context.scene.render.image_settings.file_format = 'PNG'

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(base, 'output', 'debug_closeup.blend'))
bpy.ops.render.render(write_still=True)
print("Done - check closeup.png")
