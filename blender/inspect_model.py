"""Import FBX and list all mesh objects with their names."""
import bpy, os

# Clear
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# Import
fbx_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'data', 'sat_models', 'DSP', '1323.fbx')
bpy.ops.import_scene.fbx(filepath=fbx_path)

print("\n=== Imported objects ===")
for obj in bpy.data.objects:
    if obj.type == 'MESH':
        verts = len(obj.data.vertices)
        faces = len(obj.data.polygons)
        bbox = [obj.matrix_world @ v.co for v in obj.data.vertices]
        xs = [v.x for v in bbox]; ys = [v.y for v in bbox]; zs = [v.z for v in bbox]
        dims = (max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs))
        print(f"  {obj.name:40s}  {verts:6d} verts  {faces:6d} faces  dims=({dims[0]:.3f}, {dims[1]:.3f}, {dims[2]:.3f})")
    else:
        print(f"  {obj.name:40s}  type={obj.type}")

# Total bounding box
all_verts = []
for obj in bpy.data.objects:
    if obj.type == 'MESH':
        for v in obj.data.vertices:
            all_verts.append(obj.matrix_world @ v.co)
xs = [v.x for v in all_verts]; ys = [v.y for v in all_verts]; zs = [v.z for v in all_verts]
print(f"\nTotal bounding box: ({max(xs)-min(xs):.3f}, {max(ys)-min(ys):.3f}, {max(zs)-min(zs):.3f})")
print(f"Scale to 10m: divide by {max(max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs))/10:.1f}")
