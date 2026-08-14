"""Check FBX original materials and textures before clearing them."""
import bpy, os

base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fbx = os.path.join(base, 'data', 'sat_models', 'DSP', '1323.fbx')

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

bpy.ops.import_scene.fbx(filepath=fbx)

print("=== Materials in the scene ===")
for mat in bpy.data.materials:
    print(f"\nMaterial: {mat.name}")
    if mat.node_tree:
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE':
                img = node.image
                if img:
                    path = img.filepath if img.filepath else '(generated)'
                    has_data = 'packed' if img.packed_file else ('file exists' if img.filepath and os.path.exists(img.filepath) else 'file missing')
                    print(f"  Texture: {img.name} -> {path} [{has_data}] (size {img.size[0]}x{img.size[1]})")
            elif node.type == 'BSDF_PRINCIPLED':
                bc = node.inputs['Base Color'].default_value
                print(f"  BSDF Base Color: ({bc[0]:.2f}, {bc[1]:.2f}, {bc[2]:.2f})")
            elif node.type == 'BSDF_DIFFUSE' or node.type == 'BSDF_GLOSSY':
                bc = node.inputs.get('Color')
                if bc: print(f"  BSDF Color: {bc.default_value[:]}")
    else:
        print("  (no node tree)")

print(f"\n=== Images in blend ===")
for img in bpy.data.images:
    path = img.filepath if img.filepath else '(none)'
    size = img.size
    packed = 'PACKED' if img.packed_file else 'external'
    print(f"  {img.name}: {path} [{packed}] {size[0]}x{size[1]}")

print(f"\n=== Mesh objects and their material slots ===")
for obj in bpy.data.objects:
    if obj.type == 'MESH':
        print(f"  {obj.name}: {len(obj.data.materials)} material slots")
        for i, m in enumerate(obj.data.materials):
            print(f"    slot[{i}]: {m.name if m else 'None'}")
