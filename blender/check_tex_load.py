"""Check how the FBX texture is loaded in background mode."""
import bpy, os, numpy as np

base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fbx = os.path.join(base, 'data', 'sat_models', 'DSP', '1323.fbx')

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# Import FBX
bpy.ops.import_scene.fbx(filepath=fbx)

# Check the texture image
for img in bpy.data.images:
    if 'TJ_DSP' in img.name or '1323' in img.name:
        print(f"\nImage: {img.name}")
        print(f"  Filepath: {img.filepath}")
        print(f"  Size: {img.size}")
        print(f"  Colorspace: {img.colorspace_settings.name}")
        print(f"  Packed: {bool(img.packed_file)}")
        print(f"  Source: {img.source}")
        print(f"  Type: {img.type}")
        print(f"  Is dirty: {img.is_dirty}")
        print(f"  Has data: {img.has_data}")
        print(f"  Depth: {img.depth}")
        print(f"  Float buffer: {img.is_float}")

        # Try to read pixels
        if img.has_data and img.size[0] > 0:
            try:
                w, h = img.size
                pixels = np.empty(w*h*4, dtype=np.float32)
                img.pixels.foreach_get(pixels)
                arr = pixels.reshape(h, w, 4)
                print(f"  Pixel stats: R [{arr[:,:,0].min():.3f}, {arr[:,:,0].max():.3f}] mean={arr[:,:,0].mean():.3f}")
                print(f"               G [{arr[:,:,1].min():.3f}, {arr[:,:,1].max():.3f}] mean={arr[:,:,1].mean():.3f}")
                print(f"               B [{arr[:,:,2].min():.3f}, {arr[:,:,2].max():.3f}] mean={arr[:,:,2].mean():.3f}")

                # Check a sample area (center 10x10)
                cx, cy = w//2, h//2
                sample = arr[cy-5:cy+5, cx-5:cx+5, :3]
                print(f"  Center 10x10 avg: ({sample[:,:,0].mean():.3f}, {sample[:,:,1].mean():.3f}, {sample[:,:,2].mean():.3f})")
            except Exception as e:
                print(f"  Pixel read error: {e}")
        else:
            print("  No pixel data available")

# Also check material node setup
print("\n=== Material nodes ===")
for mat in bpy.data.materials:
    if mat.node_tree:
        print(f"\nMaterial: {mat.name}")
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE':
                print(f"  TexImage: {node.name}")
                print(f"    Image: {node.image.name if node.image else 'None'}")
                print(f"    Interpolation: {node.interpolation}")
                print(f"    Extension: {node.extension}")
                print(f"    ColorSpace: {node.color_space}")
                # Check what it's connected to
                for out_sock in node.outputs:
                    for link in out_sock.links:
                        print(f"    {out_sock.name} -> {link.to_node.name}.{link.to_socket.name}")

print("\nDone")
