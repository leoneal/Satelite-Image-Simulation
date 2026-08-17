"""
build_coco.py - Rebuild unified COCO annotations from instance mask PNGs on disk.

Scans output/annotations/instance_masks/*.png, decodes each grayscale mask
(pixel value = category id), and emits:
  - coco_detection.json     (bbox + area)
  - coco_segmentation.json  (bbox + area + RLE)
  - splits.json             (every 5th frame -> val)

Works regardless of how many render batches produced the masks.
Pure stdlib + numpy.
"""

import os
import sys
import re
import json
import zlib
import struct
import numpy as np

# pixel → COCO category mapping.
# NEW encoding (default): PNG values are raw values × 50 (save_mask_png scale,
# capped at 250): 50 -> body(1), 100 -> panel(2), 150 -> panel(3), ... 250 -> panel(5+)
# LEGACY encoding (--legacy): raw values directly (v1.0 masks):
#   1=body, 2-99=panel, 100-149=phased, 150-199=reflector, 200-249=tripod
KNOWN_PIXELS = [1, 2, 3, 4, 5, 100, 150, 200]

def pixel_to_category(pix, legacy=False):
    if pix == 0:
        return None
    if legacy:
        raw = pix
    else:
        raw = pix // 50
        if raw < 1:
            raw = 1
        if raw > 5:
            raw = 5
    near = min(KNOWN_PIXELS, key=lambda k: abs(k - raw))
    if near == 1: return 1
    if 2 <= near <= 99: return 2
    if 100 <= near <= 149: return 3
    if 150 <= near <= 199: return 4
    if 200 <= near <= 249: return 5
    return None

COCO_CATEGORIES = [
    {"id": 1, "name": "body", "supercategory": "satellite"},
    {"id": 2, "name": "solar_panel", "supercategory": "satellite"},
    {"id": 3, "name": "phased_array_antenna", "supercategory": "satellite"},
    {"id": 4, "name": "reflector_antenna", "supercategory": "satellite"},
    {"id": 5, "name": "solar_panel_tripod", "supercategory": "satellite"},
]


def read_mask_png(filepath):
    """Decode 8-bit grayscale PNG (stdlib only)."""
    with open(filepath, 'rb') as f:
        data = f.read()
    assert data[:8] == b'\x89PNG\r\n\x1a\n', 'not a PNG'
    pos = 8
    idat = b''
    w = h = None
    while pos < len(data):
        ln = struct.unpack('>I', data[pos:pos+4])[0]
        typ = data[pos+4:pos+8]
        if typ == b'IHDR':
            w, h = struct.unpack('>II', data[pos+8:pos+16])
        elif typ == b'IDAT':
            idat += data[pos+8:pos+8+ln]
        pos += 12 + ln
    raw = zlib.decompress(idat)
    if w is None or h is None or w <= 0 or h <= 0:
        raise ValueError(f'Invalid PNG dimensions: {w}x{h}')
    stride = w + 1
    rows = [np.frombuffer(raw[y*stride+1:(y+1)*stride], dtype=np.uint8) for y in range(h)]
    if not rows:
        raise ValueError('Empty mask (0 rows)')
    return np.stack(rows)


def rle_encode(binary_mask):
    pixels = binary_mask.T.flatten()
    pixels = np.concatenate([[0], pixels, [0]])
    runs = np.where(pixels[1:] != pixels[:-1])[0] + 1
    runs[1::2] -= runs[::2]
    return {"size": list(binary_mask.shape), "counts": runs.tolist()}


def main(mask_dir, out_dir, val_stride=5, legacy=False):
    # Collect mask PNGs from mask_dir and all batch subdirectories
    mask_files = []  # (frame_id, full_path, file_name)
    def collect(d):
        if not os.path.isdir(d):
            return
        for f in sorted(os.listdir(d)):
            fp = os.path.join(d, f)
            if os.path.isdir(fp):
                if os.path.basename(fp) != 'no_starfield':  # skip old batch archive
                    collect(fp)
            elif f.startswith('frame_') and f.endswith('.png'):
                # Extract frame id: frame_XXXXX.png or frame_XXXXX_vNNN.png
                # Variation files get unique image ids (frame*1000 + variation),
                # matching render_scene.py's var_frame_id convention.
                m = re.match(r'frame_(\d+)(?:_v(\d+))?\.png$', f)
                if not m:
                    continue
                base = int(m.group(1))
                var = int(m.group(2)) if m.group(2) else 0
                mask_files.append((base * 1000 + var, fp, f))
    collect(mask_dir)
    mask_files.sort()
    print(f"Found {len(mask_files)} mask files under {mask_dir}")

    coco_images = []
    coco_anns = []
    ann_id = 1

    for frame_id, fp, mf in mask_files:
        try:
            mask = read_mask_png(fp)
        except Exception as e:
            print(f"  SKIP {fp}: {e}")
            continue
        h, w = mask.shape

        coco_images.append({
            "id": frame_id,
            "file_name": mf,
            "width": int(w),
            "height": int(h),
        })

        # Only process pixel values actually present in the mask
        # (naive 1..255 loop costs 256 full-image comparisons per image)
        for pixval in np.unique(mask):
            pixval = int(pixval)
            if pixval == 0:
                continue
            cat_id = pixel_to_category(pixval, legacy=legacy)
            if cat_id is None:
                continue
            binary = (mask == pixval)
            area = int(binary.sum())
            # Same area filter as render-time mask_to_annotations
            min_area = 2 if cat_id in (3, 4, 5) else 30
            if area < min_area:
                continue
            ys, xs = np.nonzero(binary)
            x0, x1 = int(xs.min()), int(xs.max())
            y0, y1 = int(ys.min()), int(ys.max())
            coco_anns.append({
                "id": ann_id,
                "image_id": frame_id,
                "category_id": cat_id,
                "bbox": [x0, y0, x1 - x0 + 1, y1 - y0 + 1],
                "area": area,
                "segmentation": rle_encode(binary),
                "iscrowd": 0,
            })
            ann_id += 1

    os.makedirs(out_dir, exist_ok=True)

    # Detection (no segmentation field)
    det = {
        "info": {"description": "Satellite rendezvous detection dataset", "version": "1.0"},
        "licenses": [],
        "images": coco_images,
        "annotations": [{k: v for k, v in a.items() if k != 'segmentation'} for a in coco_anns],
        "categories": COCO_CATEGORIES,
    }
    det_path = os.path.join(out_dir, 'coco_detection.json')
    with open(det_path, 'w') as f:
        json.dump(det, f)

    # Segmentation (with RLE)
    seg = {
        "info": {"description": "Satellite rendezvous instance segmentation dataset", "version": "1.0"},
        "licenses": [],
        "images": coco_images,
        "annotations": coco_anns,
        "categories": COCO_CATEGORIES,
    }
    seg_path = os.path.join(out_dir, 'coco_segmentation.json')
    with open(seg_path, 'w') as f:
        json.dump(seg, f)

    # Splits
    ids = sorted(img['id'] for img in coco_images)
    val_ids = ids[::val_stride]
    train_ids = [i for i in ids if i not in set(val_ids)]
    with open(os.path.join(out_dir, 'splits.json'), 'w') as f:
        json.dump({"train": train_ids, "val": val_ids,
                   "rule": f"every {val_stride}th frame -> val"}, f)

    print(f"coco_detection.json:    {len(coco_images)} images, {len(coco_anns)} anns")
    print(f"coco_segmentation.json: {seg_path}")
    print(f"splits.json: train={len(train_ids)}, val={len(val_ids)}")


if __name__ == '__main__':
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mask_dir = os.path.join(root, 'output', 'annotations', 'instance_masks')
    out_dir = os.path.join(root, 'output', 'annotations')
    legacy = '--legacy' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--legacy']
    if len(args) > 0:
        mask_dir = args[0]
    if len(args) > 1:
        out_dir = args[1]
    main(mask_dir, out_dir, legacy=legacy)
