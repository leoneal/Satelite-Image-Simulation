"""
Automated v2.1 rendering loop — 14 satellites.

v2.1 changes vs v2.0:
  - 10 sun angle variants per frame (1 true + 9 random 0-180°, deterministic)
  - 5 attitude x 10 sun = 50 combos; 63 frames/satellite -> 3,150 images
  - Solar-constant irradiance baseline 1361 W/m2, range 680-2041 (0.5x-1.5x)
  - Grayscale beauty renders (compositor), mask unaffected
  - YOLO extra satellite category class (19=nav, 20=opt, 21=mic, 22=com)
  - factors CSV: sun_irradiance_w_m2 + fov_deg columns
  - Output: E:/sat_dataset/v2.1/<sat_name>/

Resumes from last completed frame (all 50 variations + annotations present).
"""
import os, subprocess, sys
from collections import Counter

BLENDER = "E:/Blender/blender.exe"
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EPHEM_DIR = os.path.join(PROJECT, "dataset", "segB_v2", "ephemeris")
FBX_ROOT = os.path.join(PROJECT, "data", "sat_models", "fbx")
OUTPUT_BASE = "E:/sat_dataset/v2.1"

# Category YOLO classes (v2.1): 19=导航, 20=光学遥感, 21=微波遥感, 22=通信
CAT_NAV, CAT_OPT, CAT_MIC, CAT_COM = 19, 20, 21, 22

# ======== Satellite definitions ========
# (name, fbx_rel_path, model_scale, sat_class_id, category_id)
SATELLITES = [
    ("NavSat_1_Beidou-GEO",     "导航卫星/导航_1_Beidou-GEO/1_Beidou-GEO_model.fbx",      0.067, 5,  CAT_NAV),
    ("NavSat_5_gps2",           "导航卫星/导航_5_gps2/5_gps2_model.fbx",                   0.243, 6,  CAT_NAV),
    ("NavSat_3_galileo-sat",    "导航卫星/导航_3_galileo-sat/3_galileo-sat_model.fbx",     0.126, 7,  CAT_NAV),
    ("OptSat_41_sbirs-high",    "光学遥感卫星/光感_41_sbirs-high/41_sbirs-high_model.fbx", 0.393, 8,  CAT_OPT),
    ("OptSat_46-soho",          "光学遥感卫星/光感_46-soho/46-soho-model.fbx",             0.825, 9,  CAT_OPT),
    ("OptSat_2_aqua",           "光学遥感卫星/光感_2_aqua/2_aqua_model.fbx",              0.265, 10, CAT_OPT),
    ("MicSat_12_terraSAR",      "微波遥感卫星/微波_12_terraSAR/微波_12_terraSAR.fbx",      1.468, 11, CAT_MIC),
    ("MicSat_03_3cosmo-skymed", "微波遥感卫星/微波_03_3cosmo-skymed/微波_03_3cosmo-skymed.fbx", 0.805, 12, CAT_MIC),
    ("ComSat_42-tdrs",          "通信卫星/通信_42-tdrs/42-tdrs-model.fbx",                0.489, 13, CAT_COM),
    ("ComSat_47_wgs",           "通信卫星/通信_47_wgs/47_wgs_model.fbx",                  0.154, 14, CAT_COM),
    ("ComSat_30_Milstar",       "通信卫星/通信_30-Milstar/30-Milstar-model.fbx",          0.542, 16, CAT_COM),
    ("ComSat_3_AEHF",           "通信卫星/通信_3-AEHF/3-AEHF-model.fbx",                  0.307, 17, CAT_COM),
    ("ComSat_45_thuraya",       "通信卫星/通信_45_thuraya/45_thuraya_model.fbx",          0.124, 18, CAT_COM),
    # DSP: legacy user-annotated model (DSP.blend, full model 1323_00 + parts).
    # fbx_rel None -> solid colors, no texture linking. Category: optical.
    ("DSP",                     None,                                                      1.0,   15, CAT_OPT),
]

# ======== Distance segment definitions ========
# 63 frames/satellite: 42 near + 11 + 10 far (63 x 50 combos = 3,150 images)
SEGMENTS = [
    ("lt70km",    172020, 190592, 450),   # 42 frames
    ("70_250km_0", 136787, 172019, 3400),  # 11 frames (before closest approach)
    ("70_250km_1", 190593, 225823, 3600),  # 10 frames (after closest approach)
]

# ======== Augmentation (v2.1) ========
FRAME_VARIATIONS = 5        # attitude perturbations per frame
ATTITUDE_JITTER_DEG = 90    # max random cone angle
SUN_PHASE_COUNT = 10        # 1 true angle + 9 random in [0,180] per frame
SUN_ENERGY_RANGE = "950,1770"  # irradiance W/m2 (0.7x-1.3x solar constant)
EXPOSURE_EV = -3.5          # film exposure for 1361 W/m2 (tuned: no clipping)
SAMPLES = 64
RESOLUTION = 2048
FOV = 0.08
CAMERA_MODE = "track"
MODEL_TYPE = "auto"
REQUIRED_VARS = 50          # 5 attitude x 10 sun = 50 files per frame

SUB_BATCH_SIZE = 15         # frames per Blender invocation (50 combos each)
BATCH_TIMEOUT_S = 14400     # 4h per sub-batch


def get_last_rendered_frame(sat_output_root, segment_tag, required_vars=REQUIRED_VARS):
    """Get highest frame number where all variation files exist AND all
    annotations (mask + yolo) are complete."""
    img_dir = os.path.join(sat_output_root, "images", segment_tag)
    if not os.path.isdir(img_dir):
        return None
    mask_dir = os.path.join(sat_output_root, "annotations",
                            "instance_masks", segment_tag)
    yolo_dir = os.path.join(sat_output_root, "annotations", "yolo", segment_tag)

    def scan(d, suffix):
        counts = Counter()
        if not os.path.isdir(d):
            return counts
        for f in os.listdir(d):
            if f.startswith("frame_") and f.endswith(suffix):
                base = f.replace(suffix, "")
                if "_v" in base:
                    fid = int(base.split("_v")[0].split("_")[1])
                else:
                    fid = int(base.split("_")[1])
                counts[fid] += 1
        return counts

    img_counts = scan(img_dir, ".png")
    mask_counts = scan(mask_dir, ".png")
    yolo_counts = scan(yolo_dir, ".txt")
    complete = sorted(fid for fid, c in img_counts.items()
                      if c >= required_vars
                      and mask_counts.get(fid, 0) >= required_vars
                      and yolo_counts.get(fid, 0) >= required_vars)
    return complete[-1] if complete else None


def run_sub_batch(tag, start, end, stride, model_scale, sat_class_id, fbx_path,
                  output_root, blend_path=None, category_id=None):
    """Run a single Blender sub-batch."""
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
        "--sun_phase_count", str(SUN_PHASE_COUNT),
        "--sun_energy_range", SUN_ENERGY_RANGE,
        "--exposure_ev", str(EXPOSURE_EV),
        "--render_device", "gpu",
        "--tag", tag,
    ]
    if category_id is not None:
        args += ["--sat_category_id", str(category_id)]
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
        print(f"\n  TIMEOUT after {BATCH_TIMEOUT_S}s (partial frames saved, "
              f"rerun to resume)")
        return False
    if result.returncode != 0:
        print(f"\n  ERROR: {result.stderr[-500:]}")
        return False
    return True


def main():
    only = None
    limit = None
    argv = sys.argv[1:]
    if '--only' in argv:
        only = argv[argv.index('--only') + 1]
    if '--limit' in argv:
        limit = int(argv[argv.index('--limit') + 1])

    for sat_name, fbx_rel, model_scale, sat_class_id, category_id in SATELLITES:
        if only and only not in sat_name:
            continue

        fbx_path = os.path.join(FBX_ROOT, fbx_rel) if fbx_rel else None
        if fbx_path is not None and not os.path.exists(fbx_path):
            print(f"[{sat_name}] SKIP: FBX not found at {fbx_path}")
            continue

        blend_path = os.path.join(PROJECT, "output", "blend_files",
                                  f"{sat_name}.blend")
        if not os.path.exists(blend_path):
            blend_path = None

        sat_output_root = os.path.join(OUTPUT_BASE, sat_name)
        print(f"\n{'='*70}")
        print(f"[{sat_name}] class={sat_class_id}, category={category_id}, "
              f"scale={model_scale}")
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
                est_min = n * REQUIRED_VARS * 7.0 / 60
                print(f"    Frames {next_start}-{sub_end-seg_stride} "
                      f"({n} frames, ~{est_min:.0f} min)...", end=" ", flush=True)

                ok = run_sub_batch(seg_name, next_start, sub_end, seg_stride,
                                   model_scale, sat_class_id, fbx_path,
                                   sat_output_root, blend_path, category_id)
                print("OK" if ok else "FAILED")
                if not ok:
                    break
                next_start = sub_end

            final = get_last_rendered_frame(sat_output_root, seg_name)
            final_n = (final - seg_start) // seg_stride + 1 if final is not None else 0
            print(f"  [{seg_name}] Final: {final_n}/{total}")

    print("\n=== v2.1 rendering complete ===")


if __name__ == "__main__":
    main()
