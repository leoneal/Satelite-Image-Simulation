"""
render_scene.py - Blender satellite image simulation renderer

Usage:
    blender -b -P render_scene.py -- --ephem_dir <path> [--start N] [--end N] [--samples 64]

The --ephem_dir should contain:
    observer_state.csv, target_state.csv, sun_state.csv, aux_data.csv, scene_config.json

Output:
    output/images/frame_0001.png ... (RGB renders)
    output/annotations/instance_masks/frame_0001.png ... (per-component instance masks)
    output/annotations/pose/frame_0001.txt ... (pose ground truth per frame)
    output/annotations/coco_detection.json (COCO detection annotations)
    output/annotations/coco_segmentation.json (COCO segmentation annotations)
    output/annotations/yolo/ (YOLO-format detection labels)
"""

import bpy
import csv
import json
import os
import sys
import math
import argparse
from mathutils import Vector, Matrix, Quaternion, Euler

# ============================================================
# Command-line argument parsing
# ============================================================

def parse_args():
    argv = sys.argv
    if '--' in argv:
        argv = argv[argv.index('--') + 1:]
    else:
        argv = []

    parser = argparse.ArgumentParser()
    parser.add_argument('--ephem_dir', required=True, help='Path to ephemeris data directory')
    parser.add_argument('--start', type=int, default=0, help='First frame index (0-based)')
    parser.add_argument('--end', type=int, default=None, help='Last frame index (exclusive)')
    parser.add_argument('--stride', type=int, default=1, help='Frame stride (1=every frame, 60=every 60th frame)')
    parser.add_argument('--samples', type=int, default=64, help='Cycles render samples')
    parser.add_argument('--resolution', type=int, default=2048, help='Render resolution (square)')
    parser.add_argument('--batch_size', type=int, default=500, help='Frames per batch')
    parser.add_argument('--batch_offset', type=int, default=0, help='Batch offset multiplier')
    parser.add_argument('--tag', type=str, default=None,
                        help='Batch tag for output subfolder naming (default: auto from start/end)')
    parser.add_argument('--no_annotations', action='store_true', help='Skip mask/COCO/YOLO/pose generation')
    return parser.parse_args(argv)


# ============================================================
# Data loading
# ============================================================

def load_csv(filepath):
    """Load CSV into list of dicts, converting numeric values"""
    rows = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k: float(v) for k, v in row.items()})
    return rows


def load_config(filepath):
    with open(filepath, 'r') as f:
        return json.load(f)


def load_all_data(ephem_dir):
    """Load all ephemeris data files"""
    print(f"Loading data from: {ephem_dir}")
    obs_data = load_csv(os.path.join(ephem_dir, 'observer_state.csv'))
    tgt_data = load_csv(os.path.join(ephem_dir, 'target_state.csv'))
    sun_data = load_csv(os.path.join(ephem_dir, 'sun_state.csv'))
    config = load_config(os.path.join(ephem_dir, 'scene_config.json'))
    print(f"  Loaded {len(obs_data)} frames")
    return obs_data, tgt_data, sun_data, config


# ============================================================
# Scene setup
# ============================================================

KM_SCALE = 0.001  # Convert meters to km for Blender scene
SAT_MODEL_SCALE = 1.0  # Realistic scale (meters)
EARTH_RADIUS = 6371.0  # km


def clear_scene():
    """Remove all default objects"""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()


def create_earth():
    """Create Earth sphere with Blue Marble texture (fallback to solid blue if not found)."""
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=EARTH_RADIUS,
        location=(0, 0, 0),
        segments=128, ring_count=64
    )
    earth = bpy.context.active_object
    earth.name = 'Earth'

    mat = bpy.data.materials.new('EarthMaterial')
    nodes = mat.node_tree.nodes
    nodes.clear()

    # Try to load 8K Earth texture
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tex_path = os.path.join(project_root, 'data', 'earth_textures', '8k_earth_daymap.jpg')

    if os.path.exists(tex_path):
        # Textured Earth
        img_tex = nodes.new('ShaderNodeTexImage')
        img = bpy.data.images.load(tex_path)
        img_tex.image = img
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Roughness'].default_value = 0.7
        nodes.new('ShaderNodeTexCoord')
        nodes.active = None  # not needed, just connect
        output = nodes.new('ShaderNodeOutputMaterial')
        mat.node_tree.links.new(img_tex.outputs['Color'], bsdf.inputs['Base Color'])
        mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
        print('  Earth: 8K textured')
    else:
        # Fallback: solid blue
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = (0.1, 0.2, 0.5, 1.0)
        bsdf.inputs['Roughness'].default_value = 0.7
        output = nodes.new('ShaderNodeOutputMaterial')
        mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
        print(f'  Earth: solid blue (texture not found at {tex_path})')

    earth.data.materials.append(mat)
    return earth


def create_satellite_model():
    """
    Build satellite model in km-scale world coordinates (no parent scaling).
    Same approach as working debug_dist.py.

    Model dimensions: ~9m x 2m x 1.5m = ~0.009 x 0.002 x 0.0015 km
    """
    S = KM_SCALE * SAT_MODEL_SCALE  # meters -> km conversion

    # --- Body (main bus): 4m x 2m x 1.5m ---
    bpy.ops.mesh.primitive_cube_add(size=2.0*S, location=(0, 0, 0))
    body = bpy.context.active_object
    body.name = 'body'
    body.scale = (2.0, 1.0, 0.75)  # 4m x 2m x 1.5m
    bpy.ops.object.transform_apply(scale=True)  # bake scale into mesh
    body.pass_index = 1

    # --- Left solar panel: 4m x 1m, very thin ---
    bpy.ops.mesh.primitive_cube_add(size=2.0*S, location=(-3.0*S, 0, 0.1*S))
    panel_l = bpy.context.active_object
    panel_l.name = 'panel_left'
    panel_l.scale = (2.0, 0.5, 0.02)
    bpy.ops.object.transform_apply(scale=True)
    panel_l.pass_index = 2

    # --- Right solar panel ---
    bpy.ops.mesh.primitive_cube_add(size=2.0*S, location=(3.0*S, 0, 0.1*S))
    panel_r = bpy.context.active_object
    panel_r.name = 'panel_right'
    panel_r.scale = (2.0, 0.5, 0.02)
    bpy.ops.object.transform_apply(scale=True)
    panel_r.pass_index = 3

    # --- Antenna: z=+1.0m ---
    bpy.ops.mesh.primitive_cylinder_add(radius=0.4*S, depth=0.1*S, location=(0, 0, 1.0*S))
    antenna = bpy.context.active_object
    antenna.name = 'antenna'
    antenna.pass_index = 4

    # --- Thruster: z=-1.0m ---
    bpy.ops.mesh.primitive_cylinder_add(radius=0.3*S, depth=0.5*S, location=(0, 0, -1.0*S))
    thruster = bpy.context.active_object
    thruster.name = 'thruster'
    thruster.pass_index = 5

    # Store all parts in a list for group movement (no parent empty)
    sat_parts = [body, panel_l, panel_r, antenna, thruster]

    # Add materials
    for child in [body, panel_l, panel_r, antenna, thruster]:
        mat = bpy.data.materials.new(child.name + '_mat')
        nodes = mat.node_tree.nodes
        nodes.clear()

        emit = nodes.new('ShaderNodeEmission')
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        mix = nodes.new('ShaderNodeMixShader')
        if 'panel' in child.name:
            emit.inputs['Color'].default_value = (0.1, 0.2, 0.5, 1.0)
            bsdf.inputs['Base Color'].default_value = (0.1, 0.2, 0.5, 1.0)
        elif 'antenna' in child.name:
            emit.inputs['Color'].default_value = (0.9, 0.9, 0.9, 1.0)
            bsdf.inputs['Base Color'].default_value = (0.9, 0.9, 0.9, 1.0)
        elif 'thruster' in child.name:
            emit.inputs['Color'].default_value = (0.5, 0.3, 0.3, 1.0)
            bsdf.inputs['Base Color'].default_value = (0.5, 0.3, 0.3, 1.0)
        else:
            emit.inputs['Color'].default_value = (0.7, 0.7, 0.7, 1.0)
            bsdf.inputs['Base Color'].default_value = (0.7, 0.7, 0.7, 1.0)
        emit.inputs['Strength'].default_value = 10.0
        bsdf.inputs['Roughness'].default_value = 0.5
        mix.inputs['Fac'].default_value = 1.0  # 100% emission (bypass BSDF for now)

        output = nodes.new('ShaderNodeOutputMaterial')
        mat.node_tree.links.new(emit.outputs['Emission'], mix.inputs[1])
        mat.node_tree.links.new(bsdf.outputs['BSDF'], mix.inputs[2])
        mat.node_tree.links.new(mix.outputs['Shader'], output.inputs['Surface'])
        if len(child.data.materials) == 0:
            child.data.materials.append(mat)

    return sat_parts


def setup_camera(fov_deg, resolution):
    """Create camera for first-person view"""
    bpy.ops.object.camera_add(location=(0, 0, 0))
    cam = bpy.context.active_object
    cam.name = 'SensorCamera'

    # Convert total FOV to horizontal field of view
    # Blender expects horizontal FOV in radians
    cam.data.angle = math.radians(fov_deg)
    cam.data.sensor_fit = 'HORIZONTAL'

    # Set clip planes for space scale (km units)
    cam.data.clip_start = 0.01   # 10 meters in km
    cam.data.clip_end = 200000.0  # 200,000 km

    # Set render resolution
    bpy.context.scene.render.resolution_x = resolution
    bpy.context.scene.render.resolution_y = resolution
    bpy.context.scene.render.resolution_percentage = 100

    return cam


def setup_sun():
    """Create directional sun light"""
    bpy.ops.object.light_add(type='SUN', location=(0, 0, 0))
    sun = bpy.context.active_object
    sun.name = 'SunLight'
    sun.data.energy = 20.0  # Space sunlight (no atmospheric attenuation)

    # Create empty for easy orientation
    bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0, 0, 0))
    sun_target = bpy.context.active_object
    sun_target.name = 'SunTarget'

    return sun, sun_target


def setup_stars(camera):
    """Starfield via emissive plane parented to camera (works around world shader bugs).
    A large textured plane is placed in front of the camera, acting as a backdrop.
    """
    # World: pure black
    world = bpy.context.scene.world
    nodes_w = world.node_tree.nodes
    links_w = world.node_tree.links
    nodes_w.clear()
    bg = nodes_w.new('ShaderNodeBackground')
    bg.inputs['Color'].default_value = (0.0, 0.0, 0.0, 1.0)
    bg.inputs['Strength'].default_value = 1.0
    out_w = nodes_w.new('ShaderNodeOutputWorld')
    links_w.new(bg.outputs['Background'], out_w.inputs['Surface'])

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tex_path = os.path.join(project_root, 'data', 'star_bg', '8k_stars.jpg')

    if not os.path.exists(tex_path):
        print(f'  Stars: fallback dark (no texture at {tex_path})')
        return

    # Create backdrop plane far behind any possible satellite distance
    # Camera looks along -Z. 100000 km ensures plane is always behind satellite.
    BACKDROP_DIST = 100000.0  # km, well beyond max satellite distance (~16300 km)
    # Plane size to fill 0.117 deg FOV at this distance
    import math as m
    half_fov = m.radians(0.117 / 2)  # half FOV in radians
    plane_size = 2.0 * BACKDROP_DIST * m.tan(half_fov) * 2.5  # 2.5x margin
    bpy.ops.mesh.primitive_plane_add(size=plane_size, location=(0, 0, -BACKDROP_DIST))
    plane = bpy.context.active_object
    plane.name = 'StarBackdrop'

    # Parent to camera so it follows
    plane.parent = camera

    # Emission material with star texture
    mat = bpy.data.materials.new('StarBackdropMat')
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    img = bpy.data.images.load(tex_path)
    tex = nodes.new('ShaderNodeTexImage')
    tex.image = img
    # Use Window coordinates so texture stays fixed relative to frame
    coord = nodes.new('ShaderNodeTexCoord')
    links.new(coord.outputs['Window'], tex.inputs['Vector'])

    emit = nodes.new('ShaderNodeEmission')
    emit.inputs['Strength'].default_value = 1.0
    links.new(tex.outputs['Color'], emit.inputs['Color'])
    out = nodes.new('ShaderNodeOutputMaterial')
    links.new(emit.outputs['Emission'], out.inputs['Surface'])
    plane.data.materials.append(mat)

    print('  Stars: backdrop plane with 8K texture')


def setup_render(samples):
    """Configure Cycles render settings"""
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False  # Denoising kills small satellite targets
    scene.cycles.use_adaptive_sampling = False

    # Output format
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_depth = '8'
    scene.render.image_settings.compression = 15

    # Enable object index pass for segmentation masks
    scene.view_layers['ViewLayer'].use_pass_object_index = True


# ============================================================
# Frame-by-frame update
# ============================================================

def position_from_row(row, scale=KM_SCALE):
    """Extract position vector (scaled) from CSV row"""
    return Vector((
        row['pos_x_m'] * scale,
        row['pos_y_m'] * scale,
        row['pos_z_m'] * scale
    ))


def quaternion_from_row(row):
    """Extract quaternion from CSV row (qx, qy, qz, qw)"""
    return Quaternion((row['qw'], row['qx'], row['qy'], row['qz']))


def update_frame(obs_row, tgt_row, sun_row, camera, sat_parts, sun_light, sun_target, debug=False):
    """Update scene objects for a single frame"""
    obs_pos = position_from_row(obs_row)
    tgt_pos = position_from_row(tgt_row)
    tgt_quat = quaternion_from_row(tgt_row)
    sun_pos = position_from_row(sun_row)

    if debug:
        print(f"  Frame 0: dist={(tgt_pos - obs_pos).length:.1f} km")

    # Camera at observer, looking at target
    camera.location = obs_pos
    direction = (tgt_pos - obs_pos).normalized()
    z_axis = -direction
    up = Vector((0, 0, 1))
    if abs(z_axis.dot(up)) > 0.9999:
        up = Vector((1, 0, 0))
    x_axis = up.cross(z_axis).normalized()
    y_axis = z_axis.cross(x_axis).normalized()
    rot = Matrix((
        (x_axis.x, y_axis.x, z_axis.x),
        (x_axis.y, y_axis.y, z_axis.y),
        (x_axis.z, y_axis.z, z_axis.z)
    )).to_4x4()
    camera.matrix_world = Matrix.Translation(obs_pos) @ rot

    # Satellite parts: move all to target position + rotate
    # Store initial offsets on first call
    if not hasattr(update_frame, 'offsets'):
        update_frame.offsets = [p.location.copy() for p in sat_parts]
    for part, offset in zip(sat_parts, update_frame.offsets):
        part.location = tgt_pos + tgt_quat @ offset
        part.rotation_mode = 'QUATERNION'
        part.rotation_quaternion = tgt_quat

    # Sun light direction
    sun_dir = sun_pos.normalized()
    z_sun = sun_dir
    up_sun = Vector((0, 0, 1))
    if abs(z_sun.dot(up_sun)) > 0.9999:
        up_sun = Vector((1, 0, 0))
    x_sun = up_sun.cross(z_sun).normalized()
    y_sun = z_sun.cross(x_sun).normalized()
    rot_sun = Matrix((
        (x_sun.x, y_sun.x, z_sun.x),
        (x_sun.y, y_sun.y, z_sun.y),
        (x_sun.z, y_sun.z, z_sun.z)
    )).to_4x4()
    sun_light.matrix_world = rot_sun
    sun_target.location = Vector((0, 0, 0))


# ============================================================
# Annotation generation (mask -> COCO/YOLO/pose)
# ============================================================

import numpy as np

DEBUG_MASK = False  # Set True to print per-frame mask pixel statistics

COMPONENT_CLASSES = {
    'body': 1,
    'panel_left': 2,
    'panel_right': 3,
    'antenna': 4,
    'thruster': 5,
}

CLASS_NAMES = {v: k for k, v in COMPONENT_CLASSES.items()}

# Mask colors: category id encoded directly in red channel (1..5),
# green/blue zero. Unambiguous up to 255 classes.
MASK_COLORS = {
    'body':        (1.0, 0.0, 0.0, 1.0),
    'panel_left':  (2/255, 0.0, 0.0, 1.0),
    'panel_right': (3/255, 0.0, 0.0, 1.0),
    'antenna':     (4/255, 0.0, 0.0, 1.0),
    'thruster':    (5/255, 0.0, 0.0, 1.0),
}

COCO_CATEGORIES = [
    {"id": 1, "name": "body", "supercategory": "satellite"},
    {"id": 2, "name": "panel_left", "supercategory": "satellite"},
    {"id": 3, "name": "panel_right", "supercategory": "satellite"},
    {"id": 4, "name": "antenna", "supercategory": "satellite"},
    {"id": 5, "name": "thruster", "supercategory": "satellite"},
]

# ---- mask colors in 0-255 pixel values ----
MASK_PIXEL_VALUE = {  # category id -> red channel pixel value
    'body': 1, 'panel_left': 2, 'panel_right': 3, 'antenna': 4, 'thruster': 5,
}
# Map pixel value (0-255) -> category id (same numbers, identity here)


def build_mask_material(name, color255):
    """Pure-color emission material encoding category id in red channel (0-255)."""
    mat = bpy.data.materials.new(name)
    nodes = mat.node_tree.nodes
    nodes.clear()
    emit = nodes.new('ShaderNodeEmission')
    emit.inputs['Color'].default_value = (color255 / 255.0, 0.0, 0.0, 1.0)
    emit.inputs['Strength'].default_value = 1.0
    out = nodes.new('ShaderNodeOutputMaterial')
    mat.node_tree.links.new(emit.outputs['Emission'], out.inputs['Surface'])
    return mat


def assign_mask_materials(sat_parts):
    """Swap each part's material for the mask color; returns originals for restore."""
    originals = {}
    for part in sat_parts:
        pixval = MASK_PIXEL_VALUE.get(part.name, 0)
        originals[part.name] = [m for m in part.data.materials]
        part.data.materials.clear()
        part.data.materials.append(build_mask_material(f'mask_{part.name}', pixval))
    return originals


def restore_materials(sat_parts, originals):
    for part in sat_parts:
        part.data.materials.clear()
        for m in originals.get(part.name, []):
            part.data.materials.append(m)


def render_mask_image(resolution, samples_backup, tmp_exr_path):
    """
    Render current frame with mask materials at 1 sample into a temp EXR,
    read back as numpy mask (H,W) uint8. EXR preserves scene-linear values.
    """
    scene = bpy.context.scene
    scene.cycles.samples = 1

    # Render to temp EXR (linear floats)
    prev_fmt = scene.render.image_settings.file_format
    prev_depth = scene.render.image_settings.color_depth
    scene.render.image_settings.file_format = 'OPEN_EXR'
    scene.render.image_settings.color_depth = '32'
    scene.render.filepath = tmp_exr_path
    bpy.ops.render.render(write_still=True)
    scene.render.image_settings.file_format = prev_fmt
    scene.render.image_settings.color_depth = prev_depth
    scene.cycles.samples = samples_backup

    img = bpy.data.images.load(tmp_exr_path)
    w, h = img.size
    pixels = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(pixels)
    arr = pixels.reshape(h, w, 4)
    bpy.data.images.remove(img)
    try:
        os.remove(tmp_exr_path)
    except OSError:
        pass

    red = arr[:, :, 0]
    mask = np.flipud(np.rint(red * 255.0).astype(np.uint8))

    # Debug: report mask content (only when DEBUG_MASK enabled)
    if DEBUG_MASK:
        uniq, counts = np.unique(mask, return_counts=True)
        top = sorted(zip(counts, uniq), reverse=True)[:6]
        print(f"  [mask debug] red min/max: {red.min():.4f}/{red.max():.4f}, "
              f"top (val:count): {[(int(u), int(c)) for c, u in top]}")
    return mask


def save_mask_png(mask, filepath):
    """Save uint8 mask as 8-bit grayscale PNG (pure stdlib, no Blender image API)."""
    import zlib, struct
    h, w = mask.shape
    # PNG signature
    sig = b'\x89PNG\r\n\x1a\n'
    # IHDR: width, height, bitdepth=8, colortype=0 (grayscale), compression=0, filter=0, interlace=0
    ihdr_data = struct.pack('>IIBBBBB', w, h, 8, 0, 0, 0, 0)
    ihdr = struct.pack('>I', len(ihdr_data)) + b'IHDR' + ihdr_data
    ihdr += struct.pack('>I', zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff)
    # IDAT: each scanline prefixed with filter byte 0
    raw = b''.join(b'\x00' + mask[y].tobytes() for y in range(h))
    idat_data = zlib.compress(raw, 6)
    idat = struct.pack('>I', len(idat_data)) + b'IDAT' + idat_data
    idat += struct.pack('>I', zlib.crc32(b'IDAT' + idat_data) & 0xffffffff)
    # IEND
    iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', zlib.crc32(b'IEND') & 0xffffffff)
    with open(filepath, 'wb') as f:
        f.write(sig + ihdr + idat + iend)


def rle_encode(binary_mask):
    """COCO RLE encoding (column-major run-length)."""
    pixels = binary_mask.T.flatten()  # column-major (Fortran order)
    pixels = np.concatenate([[0], pixels, [0]])
    runs = np.where(pixels[1:] != pixels[:-1])[0] + 1
    runs[1::2] -= runs[::2]
    counts = runs.tolist()
    return {"size": list(binary_mask.shape), "counts": counts}


def mask_to_annotations(mask, frame_id, image_filename, ann_id_start):
    """
    Extract per-class annotations from instance mask.
    Returns (coco_image_entry, coco_ann_entries, yolo_lines, next_ann_id).
    """
    h, w = mask.shape
    coco_img = {
        "id": frame_id,
        "file_name": image_filename,
        "width": int(w),
        "height": int(h),
    }
    coco_anns = []
    yolo_lines = []
    ann_id = ann_id_start

    for cat_name, cat_id in COMPONENT_CLASSES.items():
        pixval = MASK_PIXEL_VALUE[cat_name]
        binary = (mask == pixval)
        area = int(binary.sum())
        if area == 0:
            continue

        ys, xs = np.nonzero(binary)
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
        bw, bh = x1 - x0 + 1, y1 - y0 + 1

        coco_anns.append({
            "id": ann_id,
            "image_id": frame_id,
            "category_id": cat_id,
            "bbox": [x0, y0, bw, bh],
            "area": area,
            "segmentation": rle_encode(binary),
            "iscrowd": 0,
        })
        ann_id += 1

        # YOLO: class is 0-based
        yolo_lines.append(
            f"{cat_id - 1} {(x0 + bw/2)/w:.6f} {(y0 + bh/2)/h:.6f} {bw/w:.6f} {bh/h:.6f}"
        )

    return coco_img, coco_anns, yolo_lines, ann_id


def write_pose_file(pose_dir, frame_id, tgt_row, obs_row):
    qx, qy, qz, qw = tgt_row['qx'], tgt_row['qy'], tgt_row['qz'], tgt_row['qw']
    rx = tgt_row['pos_x_m'] - obs_row['pos_x_m']
    ry = tgt_row['pos_y_m'] - obs_row['pos_y_m']
    rz = tgt_row['pos_z_m'] - obs_row['pos_z_m']
    with open(os.path.join(pose_dir, f'frame_{frame_id:04d}.txt'), 'w') as f:
        f.write(f'{qx:.8f} {qy:.8f} {qz:.8f} {qw:.8f} {rx:.6f} {ry:.6f} {rz:.6f}\n')


# ============================================================
# Main rendering loop
# ============================================================

def main():
    args = parse_args()

    # Load data
    obs_data, tgt_data, sun_data, config = load_all_data(args.ephem_dir)
    fov_deg = config.get('sensor_fov_deg', 0.117)
    resolution = args.resolution
    samples = args.samples
    enable_annotations = not args.no_annotations

    # Determine frame range
    start_frame = args.start
    if args.end:
        end_frame = min(args.end, len(obs_data))
    else:
        end_frame = len(obs_data)

    # Apply batch offset
    if args.batch_offset > 0:
        start_frame = args.batch_offset * args.batch_size
        end_frame = min(start_frame + args.batch_size, len(obs_data))

    stride = max(1, args.stride)
    frame_indices = list(range(start_frame, end_frame, stride))
    num_render = len(frame_indices)
    print(f"\nRendering frames {start_frame} to {end_frame-1} stride {stride} ({num_render} frames)")
    print(f"Resolution: {resolution}x{resolution}, Samples: {samples}, FOV: {fov_deg} deg")
    print(f"Annotations: {'ON' if enable_annotations else 'OFF'}")

    # Batch tag: each render batch gets its own subfolder (project rule:
    # never mix frames from different batches in one directory)
    batch_tag = args.tag if args.tag else f'{start_frame}_{end_frame-1}_s{samples}_r{resolution}'

    # Output directories
    ephem_abs = os.path.abspath(args.ephem_dir)
    output_root = os.path.normpath(os.path.dirname(ephem_abs))
    image_dir = os.path.join(output_root, 'images', batch_tag)
    mask_dir = os.path.join(output_root, 'annotations', 'instance_masks', batch_tag)
    pose_dir = os.path.join(output_root, 'annotations', 'pose', batch_tag)
    yolo_dir = os.path.join(output_root, 'annotations', 'yolo', batch_tag)
    coco_dir = os.path.join(output_root, 'annotations')
    for d in [image_dir, mask_dir, pose_dir, yolo_dir, coco_dir]:
        os.makedirs(d, exist_ok=True)
    print(f"Batch tag: {batch_tag}")

    # Clear default scene
    clear_scene()

    # Build scene
    print("\n--- Building Scene ---")
    earth = create_earth()
    sat_parts = create_satellite_model()
    camera = setup_camera(fov_deg, resolution)
    sun_light, sun_target = setup_sun()
    setup_stars(camera)
    setup_render(samples)

    bpy.context.scene.camera = camera

    # Annotation accumulators
    coco_images = []
    coco_annotations = []
    ann_id = 1

    # Render loop
    print(f"\n--- Rendering ---")
    for frame_idx, actual_idx in enumerate(frame_indices):

        if frame_idx % 50 == 0:
            progress = frame_idx / num_render * 100
            print(f"  [{frame_idx}/{num_render}] {progress:.0f}% - Frame {actual_idx}")

        obs_row = obs_data[actual_idx]
        tgt_row = tgt_data[actual_idx]
        sun_row = sun_data[actual_idx] if actual_idx < len(sun_data) else sun_data[0]

        update_frame(obs_row, tgt_row, sun_row, camera, sat_parts, sun_light, sun_target)

        # 1. Beauty render (RGB)
        output_path = os.path.join(image_dir, f'frame_{actual_idx:04d}.png')
        bpy.context.scene.render.filepath = output_path
        bpy.ops.render.render(write_still=True)

        if enable_annotations:
            # 2. Mask render (pure-color, 1 sample)
            originals = assign_mask_materials(sat_parts)
            tmp_exr = os.path.join(mask_dir, f'_tmp_{actual_idx:04d}.exr')
            mask = render_mask_image(resolution, samples, tmp_exr)
            restore_materials(sat_parts, originals)

            # Save mask PNG
            save_mask_png(mask, os.path.join(mask_dir, f'frame_{actual_idx:04d}.png'))

            # 3. Extract annotations from mask
            img_entry, ann_entries, yolo_lines, ann_id = mask_to_annotations(
                mask, actual_idx, f'frame_{actual_idx:04d}.png', ann_id)
            coco_images.append(img_entry)
            coco_annotations.extend(ann_entries)
            with open(os.path.join(yolo_dir, f'frame_{actual_idx:04d}.txt'), 'w') as f:
                f.write('\n'.join(yolo_lines) + ('\n' if yolo_lines else ''))

            # 4. Pose ground truth
            write_pose_file(pose_dir, actual_idx, tgt_row, obs_row)

    print(f"\n--- Rendering Complete ---")
    print(f"Images: {image_dir}")

    # Write COCO JSON
    if enable_annotations and coco_images:
        # Detection (bbox only, no segmentation)
        coco_det = {
            "info": {"description": "Satellite rendezvous detection dataset",
                     "version": "1.0"},
            "licenses": [],
            "images": coco_images,
            "annotations": [
                {k: v for k, v in a.items() if k != 'segmentation'}
                for a in coco_annotations
            ],
            "categories": COCO_CATEGORIES,
        }
        det_path = os.path.join(coco_dir, f'coco_detection_{start_frame}_{end_frame-1}.json')
        with open(det_path, 'w') as f:
            json.dump(coco_det, f)

        # Segmentation (with RLE)
        coco_seg = {
            "info": {"description": "Satellite rendezvous instance segmentation dataset",
                     "version": "1.0"},
            "licenses": [],
            "images": coco_images,
            "annotations": coco_annotations,
            "categories": COCO_CATEGORIES,
        }
        seg_path = os.path.join(coco_dir, f'coco_segmentation_{start_frame}_{end_frame-1}.json')
        with open(seg_path, 'w') as f:
            json.dump(coco_seg, f)

        # Train/val split by interval sampling (every 5th frame -> val)
        val_ids = sorted(img['id'] for img in coco_images[::5])
        train_ids = sorted(img['id'] for img in coco_images if img['id'] not in set(val_ids))
        split = {"train": train_ids, "val": val_ids,
                 "rule": "every 5th rendered frame -> val"}
        with open(os.path.join(coco_dir, 'splits.json'), 'w') as f:
            json.dump(split, f)

        print(f"COCO detection:      {det_path} ({len(coco_images)} images, {len(coco_annotations)} anns)")
        print(f"COCO segmentation:   {seg_path}")
        print(f"Instance masks:      {mask_dir}")
        print(f"YOLO labels:         {yolo_dir}")
        print(f"Pose labels:         {pose_dir}")

    print("Done!")


if __name__ == '__main__':
    main()
