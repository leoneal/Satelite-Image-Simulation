"""
Automated v2.0 rendering loop — 10 satellites, 2 distance segments each.
Resumes from last completed frame (all 15 variations present).

Output structure:
    dataset/v2.0/<sat_name>/images/<segment>/
    dataset/v2.0/<sat_name>/annotations/...
"""
import os, subprocess, glob, sys
from collections import Counter

BLENDER = "E:/Blender/blender.exe"
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EPHEM_DIR = os.path.join(PROJECT, "dataset", "segB_v2", "ephemeris")
FBX_ROOT = os.path.join(PROJECT, "data", "sat_models", "fbx")
# v2.0 dataset output lives on E: (F: doesn't have room for 30k+ images)
OUTPUT_BASE = "E:/sat_dataset/v2.0"

# ======== Satellite definitions ========
# (name, fbx_rel_path, model_scale, sat_class_id)
# name convention: <Cat><idx>_<Name> — Cat = NavSat/OptSat/MicSat/ComSat,
# idx = original numbering within the model category (e.g. 导航_1 → NavSat_1).
# sat_class_id: YOLO class for whole-satellite detection, offset by 5
# to avoid collision with component classes (0-4: body/panel/phased/reflector/tripod)
# User-annotated .blend files are auto-detected at:
#   output/blend_files/<name>.blend
# If found, the .blend (5-category annotation) is used; otherwise the raw
# FBX (auto body/panel classification) is used.
SATELLITES = [
    ("NavSat_1_Beidou-GEO",     "导航卫星/导航_1_Beidou-GEO/1_Beidou-GEO_model.fbx",      0.067, 5),
    ("NavSat_5_gps2",           "导航卫星/导航_5_gps2/5_gps2_model.fbx",                   0.243, 6),
    ("NavSat_3_galileo-sat",    "导航卫星/导航_3_galileo-sat/3_galileo-sat_model.fbx",     0.126, 7),
    ("OptSat_41_sbirs-high",    "光学遥感卫星/光感_41_sbirs-high/41_sbirs-high_model.fbx", 0.393, 8),
    ("OptSat_46-soho",          "光学遥感卫星/光感_46-soho/46-soho-model.fbx",             0.825, 9),
    ("OptSat_2_aqua",           "光学遥感卫星/光感_2_aqua/2_aqua_model.fbx",              0.265, 10),
    ("MicSat_12_terraSAR",      "微波遥感卫星/微波_12_terraSAR/微波_12_terraSAR.fbx",      1.468, 11),
    ("MicSat_03_3cosmo-skymed", "微波遥感卫星/微波_03_3cosmo-skymed/微波_03_3cosmo-skymed.fbx", 0.805, 12),
    ("ComSat_42-tdrs",          "通信卫星/通信_42-tdrs/42-tdrs-model.fbx",                0.489, 13),
    ("ComSat_47_wgs",           "通信卫星/通信_47_wgs/47_wgs_model.fbx",                  0.154, 14),
    ("ComSat_30_Milstar",       "通信卫星/通信_30-Milstar/30-Milstar-model.fbx",          0.542, 16),
    ("ComSat_3_AEHF",           "通信卫星/通信_3-AEHF/3-AEHF-model.fbx",                  0.307, 17),
    # DSP: legacy user-annotated model (DSP.blend, full model 1323_00 + parts).
    # fbx_rel None → solid colors, no texture linking.
    ("DSP",                     None,                                                      1.0,   15),
]

# ======== Distance segment definitions ========
# (segment_name, start, end, stride)
# User-specified allocation: ~142 frames <70km, ~68 frames 70-250km
SEGMENTS = [
    ("lt70km",    172020, 190592, 131),   # 142 frames
    ("70_250km_0", 136787, 172019, 1040),  # 34 frames (before closest approach)
    ("70_250km_1", 190593, 225823, 1040),  # 34 frames (after closest approach)
]

# ======== Augmentation ========
FRAME_VARIATIONS = 5       # attitude perturbations per frame
ATTITUDE_JITTER_DEG = 90   # max random cone angle
SUN_PHASE_OFFSETS = "60,120"  # 3 sun phases (0°, 60°, 120°)
SUN_ENERGY_RANGE = "60,200"   # random sun energy per combo (intensity variation)
SAMPLES = 64
RESOLUTION = 2048
FOV = 0.08
CAMERA_MODE = "track"
MODEL_TYPE = "auto"  # will use --fbx_path to override
REQUIRED_VARS = 15   # 5 attitude × 3 sun = 15 files per frame

SUB_BATCH_SIZE = 25  # frames per Blender invocation (smaller = more checkpoints)
BATCH_TIMEOUT_S = 14400  # 4h per sub-batch — multi-mesh models render slowly


def get_last_rendered_frame(sat_output_root, segment_tag, required_vars=REQUIRED_VARS):
    """Get highest frame number where all variation files exist AND all
    annotations (mask + yolo) are present. Checks both to avoid resuming
    past frames whose annotation pass was killed mid-write."""
    img_dir = os.path.join(sat_output_root, "images", segment_tag)
    if not os.path.isdir(img_dir):
        return None
    mask_dir = os.path.join(sat_output_root, "annotations",
                            "instance_masks", segment_tag)
    yolo_dir = os.path.join(sat_output_root, "annotations", "yolo", segment_tag)

    img_counts = Counter()
    for f in os.listdir(img_dir):
        if f.startswith("frame_") and f.endswith(".png"):
            base = f.replace(".png", "")
            if "_v" in base:
                fid = int(base.split("_v")[0].split("_")[1])
            else:
                fid = int(base.split("_")[1])
            img_counts[fid] += 1

    mask_counts = Counter()
    if os.path.isdir(mask_dir):
        for f in os.listdir(mask_dir):
            if f.startswith("frame_") and f.endswith(".png"):
                base = f.replace(".png", "")
                if "_v" in base:
                    fid = int(base.split("_v")[0].split("_")[1])
                else:
                    fid = int(base.split("_")[1])
                mask_counts[fid] += 1
    yolo_counts = Counter()
    if os.path.isdir(yolo_dir):
        for f in os.listdir(yolo_dir):
            if f.startswith("frame_") and f.endswith(".txt"):
                base = f.replace(".txt", "")
                if "_v" in base:
                    fid = int(base.split("_v")[0].split("_")[1])
                else:
                    fid = int(base.split("_")[1])
                yolo_counts[fid] += 1

    complete = sorted(fid for fid, c in img_counts.items()
                      if c >= required_vars
                      and mask_counts.get(fid, 0) >= required_vars
                      and yolo_counts.get(fid, 0) >= required_vars)
    return complete[-1] if complete else None


def run_sub_batch(tag, start, end, stride, model_scale, sat_class_id, fbx_path, output_root,
                  blend_path=None):
    """Run a single Blender sub-batch (≤50 frames)."""
    args = [
        "--ephem_dir", EPHEM_DIR,
        "--output_root", output_root,
        "--start", str(start), "--end", str(end),
        "--stride", str(stride),
        "--samples", str(SAMPLES),
        "--resolution", str(RESOLUTION),
        "--fov", str(FOV),
        "--camera_mode", CAMERA_MODE,
        "--model_type", MODEL_TYPE,
        "--model_scale", str(model_scale),
        "--sat_class_id", str(sat_class_id),
        "--frame_variations", str(FRAME_VARIATIONS),
        "--attitude_jitter_deg", str(ATTITUDE_JITTER_DEG),
        "--sun_phase_offsets", SUN_PHASE_OFFSETS,
        "--sun_energy_range", SUN_ENERGY_RANGE,
        "--render_device", "gpu",
        "--tag", tag,
    ]
    if fbx_path:
        args += ["--fbx_path", fbx_path]
    if blend_path:
        args += ["--blend_path", blend_path]

    cmd = [BLENDER, "-b", "-P",
           os.path.join(PROJECT, "blender", "render_scene.py"),
           "--"] + args
    try:
        result = subprocess.run(cmd, cwd=PROJECT,
                                capture_output=True, text=True,
                                encoding='utf-8', errors='replace',
                                timeout=BATCH_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        # Blender was killed mid-batch. Completed frames are valid —
        # the resume logic picks up from them on the next run.
        print(f"\n  TIMEOUT after {BATCH_TIMEOUT_S}s (partial frames saved, "
              f"rerun to resume)")
        return False
    if result.returncode != 0:
        print(f"\n  ERROR: {result.stderr[-500:]}")
        return False
    return True


def main():
    # Optional CLI filters for controlled runs:
    #   --only <name-substring>   process only matching satellites
    #   --limit <n>               max frames per segment (test mode)
    only = None
    limit = None
    argv = sys.argv[1:]
    if '--only' in argv:
        only = argv[argv.index('--only') + 1]
    if '--limit' in argv:
        limit = int(argv[argv.index('--limit') + 1])

    for sat_name, fbx_rel, model_scale, sat_class_id in SATELLITES:
        if only and only not in sat_name:
            continue

        fbx_path = os.path.join(FBX_ROOT, fbx_rel) if fbx_rel else None
        if fbx_path is not None and not os.path.exists(fbx_path):
            print(f"[{sat_name}] SKIP: FBX not found at {fbx_path}")
            continue

        # Auto-detect user-annotated .blend (5-category annotation).
        # Convention: output/blend_files/<sat_name>.blend
        blend_path = os.path.join(PROJECT, "output", "blend_files",
                                  f"{sat_name}.blend")
        if not os.path.exists(blend_path):
            blend_path = None

        sat_output_root = os.path.join(OUTPUT_BASE, sat_name)
        print(f"\n{'='*70}")
        print(f"[{sat_name}] class_id={sat_class_id}, scale={model_scale}")
        model_desc = (blend_path if blend_path else
                      ('raw FBX (body/panel only)' if fbx_path else 'blend (solid colors)'))
        print(f"  model: {model_desc}")
        print(f"  output: {sat_output_root}")

        for seg_name, seg_start, seg_end, seg_stride in SEGMENTS:
            if limit:
                seg_end = min(seg_end, seg_start + seg_stride * limit)
            total = len(range(seg_start, seg_end, seg_stride))
            if total == 0:
                continue

            last_done = get_last_rendered_frame(sat_output_root, seg_name)
            if last_done is not None and last_done >= seg_start:
                next_start = last_done + seg_stride
                n_done = (last_done - seg_start) // seg_stride + 1
            else:
                next_start = seg_start
                n_done = 0

            if next_start >= seg_end:
                print(f"  [{seg_name}] Complete: {total}/{total}")
                continue

            remaining = total - n_done
            print(f"  [{seg_name}] {n_done}/{total} done, {remaining} remaining "
                  f"(stride={seg_stride})")

            while next_start < seg_end:
                sub_end = min(seg_end, next_start + seg_stride * SUB_BATCH_SIZE)
                n = (sub_end - next_start - 1) // seg_stride + 1
                est_min = n * REQUIRED_VARS * 5.5 / 60
                print(f"    Frames {next_start}-{sub_end-seg_stride} "
                      f"({n} frames, ~{est_min:.0f} min)...", end=" ", flush=True)

                ok = run_sub_batch(seg_name, next_start, sub_end, seg_stride,
                                   model_scale, sat_class_id, fbx_path,
                                   sat_output_root, blend_path)
                print("OK" if ok else "FAILED")
                if not ok:
                    break
                next_start = sub_end

            final = get_last_rendered_frame(sat_output_root, seg_name)
            final_n = (final - seg_start) // seg_stride + 1 if final is not None else 0
            print(f"  [{seg_name}] Final: {final_n}/{total}")

    print("\n=== v2.0 rendering complete ===")


if __name__ == "__main__":
    main()
