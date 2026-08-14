"""
Render close-up of satellite model with annotation color overlay.
"""
import bpy, os, math, numpy as np, zlib, struct
from mathutils import Vector, Matrix

base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# === Build simple satellite model ===
S = 1.0  # meters scale for close-up
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

def add_cube(name, loc, sc, pi):
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=loc)
    obj = bpy.context.active_object; obj.name = name
    obj.scale = sc; bpy.ops.object.transform_apply(scale=True)
    obj.pass_index = pi; return obj

def add_cyl(name, loc, r, d, pi):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=d, location=loc)
    obj = bpy.context.active_object; obj.name = name
    obj.pass_index = pi; return obj

body   = add_cube('body', (0,0,0), (2,1,0.75), 1)
panel1 = add_cube('panel_1', (-3,0,0.1), (2,0.5,0.02), 2)
panel2 = add_cube('panel_2', (3,0,0.1), (2,0.5,0.02), 3)
ap     = add_cyl('antenna_phased_1', (0,0,1.0), 0.4, 0.3, 100)
ar     = add_cyl('antenna_reflector_1', (0,0,-1.0), 0.3, 0.8, 150)

sat_parts = [body, panel1, panel2, ap, ar]

# Rotate for better angle
for obj in sat_parts:
    obj.rotation_euler = (math.radians(15), 0, math.radians(30))

# === Camera ===
cam_loc = (0, -30, 5)
bpy.ops.object.camera_add(location=cam_loc); cam = bpy.context.active_object
cam.data.angle = math.radians(25); cam.data.clip_start = 0.01; cam.data.clip_end = 10000
d = Vector((0,0,0)) - Vector(cam_loc); z = -d.normalized(); up = Vector((0,0,1))
if abs(z.dot(up))>0.9999: up = Vector((1,0,0))
x = up.cross(z).normalized(); y = z.cross(x).normalized()
cam.matrix_world = Matrix.Translation(cam_loc) @ Matrix(((x.x,y.x,z.x),(x.y,y.y,z.y),(x.z,y.z,z.z))).to_4x4()
bpy.context.scene.camera = cam

# === Sun + world ===
bpy.ops.object.light_add(type='SUN', location=(10,10,15)); bpy.context.active_object.data.energy = 3
nw = bpy.context.scene.world.node_tree.nodes; nw.clear()
bg = nw.new('ShaderNodeBackground'); bg.inputs['Color'].default_value = (0.02,0.02,0.03,1)
ow = nw.new('ShaderNodeOutputWorld')
bpy.context.scene.world.node_tree.links.new(bg.outputs['Background'], ow.inputs['Surface'])

# === RGB render ===
bpy.context.scene.render.engine = 'CYCLES'; bpy.context.scene.cycles.samples = 128
bpy.context.scene.render.resolution_x = 2048; bpy.context.scene.render.resolution_y = 2048
rgb_path = os.path.join(base, 'output', 'images', 'annot_vis_rgb_v3.png')
bpy.context.scene.render.filepath = rgb_path; bpy.ops.render.render(write_still=True)

# === Mask render ===
for obj in sat_parts:
    mat = bpy.data.materials.new(f'm_{obj.name}'); nd = mat.node_tree.nodes; nd.clear()
    e = nd.new('ShaderNodeEmission')
    e.inputs['Color'].default_value = (obj.pass_index/255.0, 0, 0, 1)
    o = nd.new('ShaderNodeOutputMaterial')
    mat.node_tree.links.new(e.outputs['Emission'], o.inputs['Surface'])
    obj.data.materials.clear(); obj.data.materials.append(mat)

nw = bpy.context.scene.world.node_tree.nodes; nw.clear()
bg2 = nw.new('ShaderNodeBackground'); bg2.inputs['Color'].default_value = (0,0,0,1)
ow2 = nw.new('ShaderNodeOutputWorld')
bpy.context.scene.world.node_tree.links.new(bg2.outputs['Background'], ow2.inputs['Surface'])

bpy.context.scene.cycles.samples = 1
exr_path = os.path.join(base, 'output', 'images', '_mask_v3.exr')
bpy.context.scene.render.image_settings.file_format = 'OPEN_EXR'
bpy.context.scene.render.filepath = exr_path; bpy.ops.render.render(write_still=True)
bpy.context.scene.render.image_settings.file_format = 'PNG'

# === Read mask ===
img = bpy.data.images.load(exr_path); w, h = img.size
px = np.empty(w*h*4, np.float32); img.pixels.foreach_get(px)
mask = np.flipud(np.rint(px.reshape(h,w,4)[:,:,0]*255).astype(np.uint8))
bpy.data.images.remove(img)

print("Mask stats:", dict(zip(*np.unique(mask, return_counts=True))))

# === Read RGB ===
rgb_img = bpy.data.images.load(rgb_path)
rp = np.empty(w*h*4, np.float32); rgb_img.pixels.foreach_get(rp)
rgb = (np.flipud(rp.reshape(h,w,4))[:,:,:3]*255).astype(np.uint8)
bpy.data.images.remove(rgb_img)

# === Category mapping and colors ===
CAT_COLORS = {1:(128,128,128), 2:(0,100,255), 3:(255,200,50), 4:(255,120,180), 5:(200,150,80)}
KNOWN = [1,2,3,4,5,100,150,200]
def px2cat(p):
    near = min(KNOWN, key=lambda k: abs(k-p))
    if near==1: return 1
    if 2<=near<=99: return 2
    if 100<=near<=149: return 3
    if 150<=near<=199: return 4
    if 200<=near<=249: return 5
    return None

# === Overlay ===
alpha = 0.5
overlay = rgb.copy()
for pv in range(1,256):
    cat = px2cat(pv)
    if cat is None: continue
    color = CAT_COLORS.get(cat, (255,255,255))
    bm = (mask == pv)
    if not bm.any(): continue
    for ch in range(3):
        overlay[:,:,ch][bm] = (overlay[:,:,ch][bm]*(1-alpha) + color[ch]*alpha).astype(np.uint8)
    if cat == 4: print(f"  Reflector: pixel={pv}, color={color}, pixels={bm.sum()}")

# === Outline ===
outline = overlay.copy()
border = np.zeros((h,w), bool)
for dy,dx in [(-1,0),(1,0),(0,-1),(0,1)]:
    border |= (mask != np.roll(np.roll(mask,dy,0),dx,1))
for pv in range(1,256):
    cat = px2cat(pv)
    if cat is None: continue
    b = border & (mask == pv)
    if not b.any(): continue
    color = CAT_COLORS.get(cat, (255,255,255))
    for ch in range(3): outline[:,:,ch][b] = color[ch]

# === Save PNG ===
def save_png(path, img):
    h,w = img.shape[:2]
    raw = b''.join(b'\x00'+img[y].tobytes() for y in range(h))
    idat = zlib.compress(raw, 6)
    ihdr = struct.pack('>IIBBBBB',w,h,8,2,0,0,0)
    def ch(typ,dat): return struct.pack('>I',len(dat))+typ+dat+struct.pack('>I',zlib.crc32(typ+dat)&0xffffffff)
    with open(path,'wb') as f: f.write(b'\x89PNG\r\n\x1a\n'+ch(b'IHDR',ihdr)+ch(b'IDAT',idat)+ch(b'IEND',b''))

save_png(os.path.join(base,'output','images','annot_vis_overlay_v3.png'), overlay)
save_png(os.path.join(base,'output','images','annot_vis_outline_v3.png'), outline)
print("Overlay & outline v3 saved.\nLegend: Grey=body, Blue=solar, Gold=phased, Pink=reflector")
