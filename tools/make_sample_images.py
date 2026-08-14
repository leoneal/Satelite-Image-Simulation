"""Generate sample images for report: mask overlay visualization + point target."""
import os, sys, struct, zlib
import numpy as np

project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Category colors (BGR for OpenCV-style, but we use RGB)
CAT_COLORS = {
    1: (128, 128, 128),   # body: grey
    2: (50, 100, 200),    # solar_panel: blue
    3: (230, 220, 180),   # phased_array: cream
    4: (220, 210, 200),   # reflector: silver
    5: (150, 120, 80),    # tripod: bronze
}

def read_png(filepath):
    """Read PNG, return (H,W) or (H,W,3) uint8 numpy array."""
    with open(filepath, 'rb') as f:
        data = f.read()
    # Find IHDR
    ihdr_pos = data.find(b'IHDR')
    w = struct.unpack('>I', data[ihdr_pos+4:ihdr_pos+8])[0]
    h = struct.unpack('>I', data[ihdr_pos+8:ihdr_pos+12])[0]
    color_type = data[ihdr_pos+13]  # 0=gray, 2=RGB
    channels = 1 if color_type == 0 else 3

    # Find IDAT
    pos = data.find(b'IDAT')
    raw = b''
    while pos != -1:
        length = struct.unpack('>I', data[pos-4:pos])[0]
        raw += data[pos+4:pos+4+length]
        pos = data.find(b'IDAT', pos+4+length)

    raw = zlib.decompress(raw)
    row_size = w * channels + 1  # +1 for filter byte
    arr = np.zeros((h, w, channels) if channels > 1 else (h, w), dtype=np.uint8)
    for y in range(h):
        offset = y * row_size + 1
        if channels == 1:
            arr[y] = np.frombuffer(raw[offset:offset+w], dtype=np.uint8)
        else:
            arr[y] = np.frombuffer(raw[offset:offset+w*3], dtype=np.uint8).reshape(w, 3)
    return arr

def save_png_rgb(arr, filepath):
    """Save RGB uint8 (H,W,3) as PNG."""
    h, w = arr.shape[:2]
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    ihdr = struct.pack('>I', len(ihdr_data)) + b'IHDR' + ihdr_data
    ihdr += struct.pack('>I', zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff)
    raw = b''.join(b'\x00' + arr[y].tobytes() for y in range(h))
    idat_data = zlib.compress(raw, 6)
    idat = struct.pack('>I', len(idat_data)) + b'IDAT' + idat_data
    idat += struct.pack('>I', zlib.crc32(b'IDAT' + idat_data) & 0xffffffff)
    iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', zlib.crc32(b'IEND') & 0xffffffff)
    with open(filepath, 'wb') as f:
        f.write(sig + ihdr + idat + iend)


def make_mask_overlay(beauty_path, mask_path, output_path):
    """Overlay mask colors on beauty render: 50% beauty + 50% mask color."""
    beauty = read_png(beauty_path)
    mask = read_png(mask_path)

    h, w = mask.shape
    if beauty.ndim == 2:
        beauty_rgb = np.stack([beauty] * 3, axis=-1)
    else:
        beauty_rgb = beauty

    overlay = (beauty_rgb * 0.5).astype(np.float32)

    for cat_id, color in CAT_COLORS.items():
        # Map mask pixel values to categories (same logic as render_scene.py)
        if cat_id == 1:
            pmask = (mask == 1)
        elif cat_id == 2:
            pmask = (mask >= 2) & (mask <= 99)
        elif cat_id == 3:
            pmask = (mask >= 100) & (mask <= 149)
        elif cat_id == 4:
            pmask = (mask >= 150) & (mask <= 199)
        elif cat_id == 5:
            pmask = (mask >= 200) & (mask <= 249)
        else:
            continue
        if pmask.any():
            for c in range(3):
                overlay[pmask, c] += color[c] * 0.5

    overlay = np.clip(overlay, 0, 255).astype(np.uint8)
    save_png_rgb(overlay, output_path)
    print(f'  Mask overlay: {output_path}')


if __name__ == '__main__':
    # Sample 3: mask overlay — use a segB frame with full annotations
    segb_dir = 'output/images/segB_DSP_full_23165_23608_s64_r2048'
    mask_dir = 'output/annotations/instance_masks/segB_DSP_full_23165_23608_s64_r2048'

    beauty_path = os.path.join(project, segb_dir, 'frame_23386.png')
    mask_path = os.path.join(project, mask_dir, 'frame_23386.png')

    out_dir = os.path.join(project, 'output', 'sample_images')
    os.makedirs(out_dir, exist_ok=True)

    if os.path.exists(beauty_path) and os.path.exists(mask_path):
        make_mask_overlay(beauty_path, mask_path,
                         os.path.join(out_dir, 'sample3_annot_vis.png'))
    else:
        print(f'Sample 3: beauty={os.path.exists(beauty_path)}, mask={os.path.exists(mask_path)}')
        # Try the test_phase2 batch which has annotations
        test_beauty = os.path.join(project, 'output/images/test_phase2/frame_23386.png')
        test_mask = os.path.join(project, 'output/annotations/instance_masks/test_phase2/frame_23386.png')
        if os.path.exists(test_beauty) and os.path.exists(test_mask):
            make_mask_overlay(test_beauty, test_mask,
                             os.path.join(out_dir, 'sample3_annot_vis.png'))

    print('Done!')
