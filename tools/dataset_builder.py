"""
Build unified datasets from rendered batches and point-target generator output.

Dataset A (point detection):
  Scans point-target images + segA/segC renders, produces:
    dataset_point/
      labels.csv          # frame_id, cx_px, cy_px, brightness, dist_km, sun_phase_deg
      splits.json         # train/val split
      manifest.json       # all image paths, metadata per frame

Dataset B (detection + segmentation):
  Scans segB renders with COCO annotations, produces:
    dataset_close/
      instances.json      # unified COCO detection + segmentation
      splits.json         # train/val split
      manifest.json       # image paths, batch metadata

Usage:
  python tools/dataset_builder.py --mode point --source <dir1,dir2,...> --output dataset_point
  python tools/dataset_builder.py --mode close --source <dir1,dir2,...> --output dataset_close
"""

import os, json, csv, argparse, glob


def build_point_dataset(source_dirs, output_dir, val_every=5):
    """Build point-target dataset from analytic PNGs + rendered frames."""
    os.makedirs(output_dir, exist_ok=True)
    labels = []
    images = []
    has_labels = False

    for src in source_dirs:
        if not os.path.isdir(src):
            continue
        # Check for labels.csv (analytical generator output)
        lpath = os.path.join(src, 'labels.csv')
        img_dir = os.path.join(src, 'images')
        if os.path.exists(lpath) and os.path.isdir(img_dir):
            has_labels = True
            with open(lpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    fid = int(row['frame_id'])
                    fname = f'frame_{fid:04d}.png'
                    fpath = os.path.join(img_dir, fname)
                    if os.path.exists(fpath):
                        labels.append(row)
                        images.append({
                            'id': fid,
                            'file_name': os.path.abspath(fpath),
                            'source': src,
                            'cx_px': float(row['cx_px']),
                            'cy_px': float(row['cy_px']),
                            'brightness': float(row.get('brightness', 1.0)),
                            'dist_km': float(row.get('dist_km', 0)),
                            'sun_phase_deg': float(row.get('sun_phase_deg', 90)),
                        })
            print(f'  {src}: {len(labels)} labeled frames')
            continue

        # Otherwise scan for frame_*.png files (Blender renders without labels)
        imgs = sorted(glob.glob(os.path.join(src, 'frame_*.png')))
        if not imgs:
            # Try images/ subdir
            imgs = sorted(glob.glob(os.path.join(src, 'images', 'frame_*.png')))
        for fpath in imgs:
            fname = os.path.basename(fpath)
            try:
                fid = int(fname.split('_')[1].split('.')[0])
            except (IndexError, ValueError):
                fid = len(images)
            images.append({
                'id': fid,
                'file_name': os.path.abspath(fpath),
                'source': src,
            })
        if imgs:
            print(f'  {src}: {len(imgs)} frames (no labels)')

    # Write labels.csv (copy from analytical output, or empty template)
    labels_path = os.path.join(output_dir, 'labels.csv')
    if has_labels and labels:
        with open(labels_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['frame_id', 'cx_px', 'cy_px', 'brightness', 'dist_km', 'sun_phase_deg'])
            for row in labels:
                writer.writerow([row['frame_id'], row['cx_px'], row['cy_px'],
                                 row.get('brightness', ''), row.get('dist_km', ''),
                                 row.get('sun_phase_deg', '')])
    else:
        with open(labels_path, 'w', newline='') as f:
            f.write('frame_id,cx_px,cy_px,brightness,dist_km,sun_phase_deg\n')

    # Write manifest.json
    manifest_path = os.path.join(output_dir, 'manifest.json')
    with open(manifest_path, 'w') as f:
        json.dump({'images': images, 'total': len(images)}, f, indent=2)

    # Write splits.json (every Nth to val)
    val_ids = sorted(img['id'] for img in images[::val_every])
    train_ids = sorted(img['id'] for img in images if img['id'] not in val_ids)
    splits_path = os.path.join(output_dir, 'splits.json')
    with open(splits_path, 'w') as f:
        json.dump({
            'train': train_ids, 'val': val_ids,
            'rule': f'every {val_every}th frame -> val'
        }, f)

    print(f'\nDataset A (point): {len(images)} images')
    print(f'  Train: {len(train_ids)}, Val: {len(val_ids)}')
    print(f'  Labels: {labels_path}')
    print(f'  Splits: {splits_path}')
    print(f'  Manifest: {manifest_path}')


def build_close_dataset(source_dirs, output_dir, val_every=5):
    """Build close-range detection/segmentation dataset from segB renders."""
    os.makedirs(output_dir, exist_ok=True)

    all_images = []
    all_annotations = []
    cat_names = {1: 'body', 2: 'solar_panel', 3: 'phased_array_antenna',
                 4: 'reflector_antenna', 5: 'solar_panel_tripod'}

    for src in source_dirs:
        if not os.path.isdir(src):
            continue

        # Find best-matching COCO JSON for this batch
        anno_dir = os.path.join(os.path.dirname(os.path.dirname(src)), 'annotations')
        coco_files = glob.glob(os.path.join(anno_dir, 'coco_segmentation_*.json'))
        if not coco_files:
            coco_files = glob.glob(os.path.join(anno_dir, 'coco_detection_*.json'))

        coco_data = None
        # Load all COCO files, pick the one with most images
        img_files = sorted(glob.glob(os.path.join(src, 'frame_*.png')))
        disk_names = set(os.path.basename(f) for f in img_files)
        best_coco = None
        best_match = 0
        for cf in coco_files:
            with open(cf) as f:
                coco_tmp = json.load(f)
            match = sum(1 for ci in coco_tmp.get('images', [])
                       if ci['file_name'] in disk_names)
            if match > best_match:
                best_match = match
                best_coco = coco_tmp
        if best_coco:
            coco_data = best_coco
            print(f'  Loaded COCO with {len(coco_data.get("images",[]))} images, '
                  f'{len(coco_data.get("annotations",[]))} anns ({best_match} matched)')

        # Build path map
        path_map = {os.path.basename(f): os.path.abspath(f) for f in img_files}

        if coco_data:
            matched = 0
            for ci in coco_data.get('images', []):
                fname = ci['file_name']
                if fname in path_map:
                    all_images.append({
                        'id': ci['id'],
                        'file_name': path_map[fname],
                        'width': ci.get('width', 2048),
                        'height': ci.get('height', 2048),
                        'source': src,
                    })
                    matched += 1
            for ann in coco_data.get('annotations', []):
                all_annotations.append(ann)
            print(f'  {src}: {matched} images, {len(all_annotations)} anns')
        else:
            for fpath in img_files:
                all_images.append({
                    'id': len(all_images),
                    'file_name': os.path.abspath(fpath),
                    'width': 2048, 'height': 2048, 'source': src,
                })
            print(f'  {src}: {len(img_files)} images (no COCO)')

    # Write unified COCO JSON
    categories = [{'id': k, 'name': v, 'supercategory': 'satellite'}
                  for k, v in cat_names.items()]
    coco_out = {
        'info': {'description': 'Close-range satellite detection/segmentation dataset'},
        'images': [{'id': img['id'], 'file_name': img['file_name'],
                     'width': img.get('width', 2048), 'height': img.get('height', 2048)}
                   for img in all_images],
        'annotations': all_annotations,
        'categories': categories,
    }
    instances_path = os.path.join(output_dir, 'instances.json')
    with open(instances_path, 'w') as f:
        json.dump(coco_out, f)

    # Splits
    val_ids = sorted(img['id'] for img in all_images[::val_every])
    train_ids = sorted(img['id'] for img in all_images if img['id'] not in val_ids)
    splits_path = os.path.join(output_dir, 'splits.json')
    with open(splits_path, 'w') as f:
        json.dump({'train': train_ids, 'val': val_ids,
                   'rule': f'every {val_every}th frame -> val'}, f)

    # Manifest
    manifest_path = os.path.join(output_dir, 'manifest.json')
    with open(manifest_path, 'w') as f:
        json.dump({'images': all_images, 'total': len(all_images)}, f, indent=2)

    print(f'\nDataset B (close): {len(all_images)} images, {len(all_annotations)} annotations')
    print(f'  Train: {len(train_ids)}, Val: {len(val_ids)}')
    print(f'  Instances: {instances_path}')
    print(f'  Splits: {splits_path}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', required=True, choices=['point', 'close'])
    parser.add_argument('--source', required=True,
                        help='Comma-separated source directories')
    parser.add_argument('--output', required=True, help='Output dataset directory')
    parser.add_argument('--val_every', type=int, default=5,
                        help='Every Nth frame -> val set')
    args = parser.parse_args()

    sources = [s.strip() for s in args.source.split(',')]

    if args.mode == 'point':
        build_point_dataset(sources, args.output, args.val_every)
    else:
        build_close_dataset(sources, args.output, args.val_every)
