"""
Automated sub-batch rendering loop. Manages all segB batches and resumes
from whatever was last completed (checks existing output files).
"""

import os, subprocess, glob, sys

BLENDER = "E:/Blender/blender.exe"
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EPHEM_DIR = os.path.join(PROJECT, "dataset", "segB_v2", "ephemeris")

# ======== Batch definitions ========
BATCHES = [
    # (tag, start, end, stride, model_type, model_scale, frame_variations, jitter, sun, samples, res, fov, mode)
    # Batch 1: DSP < 70km
    ("dsp_lt70km",  172021, 190621, 62,  "dsp_blend", 1.0, 5, 90, "60,120", 64, 2048, 0.08, "track"),
    # Batch 2: DSP 70-250km (two ranges: approaching and departing)
    ("dsp_70_250km",      0, 172021, 352, "dsp_blend", 1.0, 5, 90, "60,120", 64, 2048, 0.08, "track"),
    ("dsp_70_250km", 190593, 362402, 352, "dsp_blend", 1.0, 5, 90, "60,120", 64, 2048, 0.08, "track"),
    # Batch 3: Simple < 70km
    ("sim_lt70km",   172021, 190621, 62,  "simple",    1.0, 5, 90, "60,120", 64, 2048, 0.08, "track"),
    # Batch 4: Simple 70-250km
    ("sim_70_250km",      0, 172021, 352, "simple",    1.0, 5, 90, "60,120", 64, 2048, 0.08, "track"),
    ("sim_70_250km", 190593, 362402, 352, "simple",    1.0, 5, 90, "60,120", 64, 2048, 0.08, "track"),
]

SUB_BATCH_SIZE = 50  # frames per Blender invocation (GPU: ~10 min for 50×15 combos)

def get_last_rendered_frame(tag, required_vars=15):
    """Get highest frame number where ALL variation files are present.
    Only frames with >= required_vars output files count as complete."""
    img_dir = os.path.join(PROJECT, "dataset", "segB_v2", "images", tag)
    if not os.path.isdir(img_dir):
        return None
    from collections import Counter
    counts = Counter()
    for f in os.listdir(img_dir):
        if f.startswith("frame_") and f.endswith(".png"):
            base = f.replace(".png", "")
            if "_v" in base:
                fid = int(base.split("_v")[0].split("_")[1])
            else:
                fid = int(base.split("_")[1])
            counts[fid] += 1
    complete = sorted(fid for fid, c in counts.items() if c >= required_vars)
    return complete[-1] if complete else None


def run_sub_batch(tag, start, end, stride, model_type, model_scale,
                  frame_vars, jitter, sun, samples, res, fov, mode):
    """Run a single Blender sub-batch."""
    args = [
        "--ephem_dir", EPHEM_DIR,
        "--start", str(start), "--end", str(end),
        "--stride", str(stride),
        "--samples", str(samples),
        "--resolution", str(res),
        "--fov", str(fov),
        "--camera_mode", mode,
        "--model_type", model_type,
        "--model_scale", str(model_scale),
        "--render_device", "gpu",
        "--tag", tag,
    ]
    if frame_vars > 1:
        args += ["--frame_variations", str(frame_vars),
                 "--attitude_jitter_deg", str(jitter)]
    if sun:
        args += ["--sun_phase_offsets", sun]

    cmd = [BLENDER, "-b", "-P",
           os.path.join(PROJECT, "blender", "render_scene.py"),
           "--"] + args
    result = subprocess.run(cmd, cwd=PROJECT,
                            capture_output=True, text=True,
                            encoding='utf-8', errors='replace',
                            timeout=7200)
    if result.returncode != 0:
        print(f"\n  ERROR: {result.stderr[-500:]}")
        return False
    return True


def main():
    for tag, start, end, stride, model_type, model_scale, frame_vars, jitter, sun, samples, res, fov, mode in BATCHES:
        total = len(range(start, end, stride))
        if total == 0:
            continue

        # Find last completed frame
        last_done = get_last_rendered_frame(tag)
        if last_done is not None and last_done >= start:
            next_start = last_done + stride
            n_done = (last_done - start) // stride + 1
        else:
            next_start = start
            n_done = 0

        if next_start >= end:
            print(f"[{tag}] Complete: {total}/{total}")
            continue

        remaining = total - n_done
        print(f"\n{'='*60}")
        print(f"[{tag}] {model_type}, {n_done}/{total} done, {remaining} remaining")

        while next_start < end:
            sub_end = min(end, next_start + stride * SUB_BATCH_SIZE)
            n = (sub_end - next_start - 1) // stride + 1
            print(f"  Frames {next_start}-{sub_end-stride} ({n} frames, "
                  f"~{n*15*5.5/60:.0f} min)...", end=" ", flush=True)

            ok = run_sub_batch(tag, next_start, sub_end, stride,
                              model_type, model_scale, frame_vars, jitter, sun,
                              samples, res, fov, mode)
            print("OK" if ok else "FAILED")
            if not ok:
                break
            next_start = sub_end

        final = get_last_rendered_frame(tag)
        final_n = (final - start) // stride + 1 if final is not None else 0
        print(f"[{tag}] Final: {final_n}/{total}")

    print("\n=== All batches complete ===")


if __name__ == "__main__":
    main()
