"""
Regenerate COCO JSONs for a frame range by re-rendering ONLY the mask pass.
Used to repair batch-end COCO files lost when a render sub-batch was killed
(the per-image masks/yolo/pose survive; only the JSONs were lost).

The ×50-encoded mask PNGs cannot be used for this: values >= 6 are capped
at 250, losing instance/category identity. Re-rendering the 1-sample mask
pass recovers the raw values exactly (attitude seeds and sun offsets are
deterministic, matching the original renders).

Usage:
    blender -b -P regenerate_coco.py -- --ephem_dir <dir> \
        --output_root <sat_root> --start S --end E --stride ST \
        --blend_path <b> --fbx_path <f> --model_scale M --sat_class_id C \
        --tag <segment_tag>
"""
import bpy
import os
import sys
import math
import json
import random
import argparse
from mathutils import Vector, Quaternion

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_scene as rs


def parse_args():
    argv = sys.argv
    argv = argv[argv.index('--') + 1:] if '--' in argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--ephem_dir', required=True)
    p.add_argument('--output_root', required=True)
    p.add_argument('--start', type=int, required=True)
    p.add_argument('--end', type=int, required=True)
    p.add_argument('--stride', type=int, required=True)
    p.add_argument('--blend_path', default=None)
    p.add_argument('--fbx_path', default=None)
    p.add_argument('--model_scale', type=float, default=1.0)
    p.add_argument('--sat_class_id', type=int, default=None)
    p.add_argument('--tag', default='lt70km')
    return p.parse_args(argv)


def main():
    args = parse_args()
    obs_data, tgt_data, sun_data, _cfg = rs.load_all_data(args.ephem_dir)
    frames = list(range(args.start, min(args.end, len(obs_data)), args.stride))
    print(f'Regenerating COCO for {len(frames)} frames x 15 combos')

    # Scene setup (mask pass only — no stars needed, but world must be black)
    rs.clear_scene()
    earth = rs.create_earth()
    parts = rs.create_satellite_model(args.model_scale, 'auto',
                                      args.fbx_path, args.blend_path)
    camera = rs.setup_camera(0.08, 2048, 'track')
    sun_light, sun_target = rs.setup_sun()
    # Black world (mask render requires pure black background)
    world = bpy.context.scene.world
    nodes_w = world.node_tree.nodes
    nodes_w.clear()
    bg = nodes_w.new('ShaderNodeBackground')
    bg.inputs['Color'].default_value = (0, 0, 0, 1)
    out_w = nodes_w.new('ShaderNodeOutputWorld')
    world.node_tree.links.new(bg.outputs['Background'], out_w.inputs['Surface'])
    rs.setup_render(64, 'gpu')
    bpy.context.scene.camera = camera

    # Combo schedule: combo//3 = attitude var, combo%3 cycles [0,60,120]
    OFFSET_CYCLE = [0.0, 60.0, 120.0]

    coco_images = []
    coco_anns = []
    ann_id = 1
    mask_dir = os.path.join(args.output_root, 'annotations',
                            'instance_masks', args.tag)
    os.makedirs(mask_dir, exist_ok=True)

    for fid in frames:
        obs_row = obs_data[fid]
        tgt_row = tgt_data[fid]
        sun_row = sun_data[fid] if fid < len(sun_data) else sun_data[0]
        for combo in range(15):
            av = combo // 3
            offset = OFFSET_CYCLE[combo % 3]
            if av > 0:
                random.seed(fid * 1000 + av)
                perturb = rs.random_cone_quaternion(90.0)
            else:
                perturb = None

            rs.update_frame(obs_row, tgt_row, sun_row, camera, parts,
                            sun_light, sun_target, earth,
                            perturb_quat=perturb, sun_phase_offset=offset)

            originals, hidden = rs.assign_mask_materials(parts)
            tmp_exr = os.path.join(mask_dir, f'_tmp_regen_{fid}_{combo}.exr')
            mask = rs.render_mask_image(2048, 64, tmp_exr)
            rs.restore_materials(parts, originals, hidden)

            fname = (f'frame_{fid:04d}.png' if combo == 0
                     else f'frame_{fid:04d}_v{combo:03d}.png')
            img_entry, anns, _yolo, ann_id = rs.mask_to_annotations(
                mask, fid * 1000 + combo, fname, ann_id)
            coco_images.append(img_entry)
            coco_anns.extend(anns)

        if len(frames) > 1 and (frames.index(fid) + 1) % 10 == 0:
            print(f'  {frames.index(fid) + 1}/{len(frames)} frames done')

    # Write COCO JSONs (detection + segmentation) for this range
    ann_dir = os.path.join(args.output_root, 'annotations')
    det = {
        'info': {'description': 'Satellite rendezvous detection dataset',
                 'version': '1.0'},
        'licenses': [],
        'images': coco_images,
        'annotations': [{k: v for k, v in a.items() if k != 'segmentation'}
                        for a in coco_anns],
        'categories': rs.COCO_CATEGORIES,
    }
    det_path = os.path.join(ann_dir,
                            f'coco_detection_{args.start}_{args.end - 1}.json')
    with open(det_path, 'w') as f:
        json.dump(det, f)

    seg = {
        'info': {'description': 'Satellite rendezvous instance segmentation dataset',
                 'version': '1.0'},
        'licenses': [],
        'images': coco_images,
        'annotations': coco_anns,
        'categories': rs.COCO_CATEGORIES,
    }
    seg_path = os.path.join(ann_dir,
                            f'coco_segmentation_{args.start}_{args.end - 1}.json')
    with open(seg_path, 'w') as f:
        json.dump(seg, f)

    print(f'Done: {len(coco_images)} images, {len(coco_anns)} anns')
    print(f'  {det_path}')
    print(f'  {seg_path}')


if __name__ == '__main__':
    main()
