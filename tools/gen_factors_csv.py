"""
Post-hoc factors CSV generator: reconstruct per-image factors (distance,
sun phase angle, sun energy) for already-rendered batches from the
ephemeris CSVs. Used to repair satellites whose factors CSV / COCO
ranges were lost when a render sub-batch was killed mid-run.

Sun energy is replicated exactly: render_scene.py samples it with
random.seed(frame*1000 + combo + 9999) → random.uniform(60, 200), which
Python's random module reproduces deterministically.

Usage:
    python tools/gen_factors_csv.py <sat_output_root> [--energy 200.0]
                                       [--range start:end:stride ...]

Without --range, generates ONE CSV per segment (matching
tools/render_loop_v2.py SEGMENTS) and deletes the previous factors_*.csv
files for the satellite.
"""
import os
import re
import sys
import csv
import glob
import math
import random
import numpy as np

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EPHEM_DIR = os.path.join(PROJECT, "dataset", "segB_v2", "ephemeris")
KM_SCALE = 0.001
ENERGY_MIN, ENERGY_MAX = 60.0, 200.0  # must match render_loop_v2.py

# Combo order in render_scene.py: (0,0), then av 0..4 x offsets [0,60,120]
# skipping (0,0) → combo_idx % 3 cycles 0°, 60°, 120°.
OFFSET_CYCLE = [0.0, 60.0, 120.0]

# Segment definitions must match tools/render_loop_v2.py SEGMENTS
SEGMENTS = [
    (172020, 190592, 131),   # lt70km
    (136787, 172019, 1040),  # 70_250km_0
    (190593, 225823, 1040),  # 70_250km_1
]


def energy_for(frame, combo):
    """Replicate render_scene.py's deterministic sun energy sampling."""
    rng = random.Random(frame * 1000 + combo + 9999)
    return rng.uniform(ENERGY_MIN, ENERGY_MAX)


def stride_for(start):
    for seg_start, seg_end, seg_stride in SEGMENTS:
        if seg_start <= start < seg_end:
            return seg_stride
    raise ValueError(f'Frame {start} outside known segments')


def load_ephem_rows(frame_ids):
    """Load obs/tgt/sun rows for the given frame indices (row i = frame i)."""
    needed = set(frame_ids)
    obs = {}; tgt = {}; sun = {}
    for name, store in (('observer_state', obs), ('target_state', tgt),
                        ('sun_state', sun)):
        with open(os.path.join(EPHEM_DIR, f'{name}.csv'), 'r') as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                if i in needed:
                    store[i] = row
    return obs, tgt, sun


def sun_angle_deg(obs_row, tgt_row, sun_row, offset_deg):
    """Replicate update_frame's sun direction math (numpy)."""
    o = np.array([float(obs_row['pos_x_m']), float(obs_row['pos_y_m']),
                  float(obs_row['pos_z_m'])]) * KM_SCALE
    t = np.array([float(tgt_row['pos_x_m']), float(tgt_row['pos_y_m']),
                  float(tgt_row['pos_z_m'])]) * KM_SCALE
    s = np.array([float(sun_row['pos_x_m']), float(sun_row['pos_y_m']),
                  float(sun_row['pos_z_m'])]) * KM_SCALE

    rel_tgt = t - o
    rel_sun = s - o
    if offset_deg != 0.0:
        tgt_to_sun = s - t
        axis = np.cross(rel_tgt, tgt_to_sun)
        axis = axis / np.linalg.norm(axis)
        theta = math.radians(offset_deg)
        # Rodrigues rotation
        v = tgt_to_sun
        new_v = (v * math.cos(theta) +
                 np.cross(axis, v) * math.sin(theta) +
                 axis * np.dot(axis, v) * (1 - math.cos(theta)))
        sun_dir = (new_v + rel_tgt) / np.linalg.norm(new_v + rel_tgt)
    else:
        sun_dir = rel_sun / np.linalg.norm(rel_sun)

    cam_dir = rel_tgt / np.linalg.norm(rel_tgt)
    cosang = np.clip(np.dot(cam_dir, sun_dir), -1.0, 1.0)
    return math.degrees(math.acos(cosang))


def main():
    sat_root = None
    fixed_energy = None  # None → replicate seeded values; else fixed value
    custom_ranges = []
    argv = [a for a in sys.argv[1:]]
    if '--energy' in argv:
        fixed_energy = float(argv[argv.index('--energy') + 1])
        argv = argv[:argv.index('--energy')] + argv[argv.index('--energy') + 2:]
    while '--range' in argv:
        i = argv.index('--range')
        s, e, st = argv[i + 1].split(':')
        custom_ranges.append((int(s), int(e), int(st)))
        argv = argv[:i] + argv[i + 2:]
    if argv:
        sat_root = argv[0]
    if not sat_root or not os.path.isdir(sat_root):
        print('Usage: gen_factors_csv.py <sat_output_root> [--energy 200.0] '
              '[--range start:end:stride ...]')
        return

    ann_dir = os.path.join(sat_root, 'annotations')
    if custom_ranges:
        ranges = custom_ranges
    else:
        # Full per-segment coverage; delete old fragmented CSVs first
        for fp in glob.glob(os.path.join(ann_dir, 'factors_*.csv')):
            os.remove(fp)
        ranges = [(s, e - 1, st) for s, e, st in SEGMENTS]

    # Collect sampled frame ids
    frame_ids = set()
    for start, end, stride in ranges:
        frame_ids.update(range(start, end + 1, stride))
    print(f'Loading ephemeris rows for {len(frame_ids)} frames...')
    obs, tgt, sun = load_ephem_rows(frame_ids)

    for start, end, stride in ranges:
        rows = []
        for fid in sorted(frame_ids):
            if not (start <= fid <= end):
                continue
            if fid not in obs:
                print(f'  WARNING: frame {fid} missing from ephemeris, skipped')
                continue
            ox = float(obs[fid]['pos_x_m']); oy = float(obs[fid]['pos_y_m'])
            oz = float(obs[fid]['pos_z_m'])
            tx = float(tgt[fid]['pos_x_m']); ty = float(tgt[fid]['pos_y_m'])
            tz = float(tgt[fid]['pos_z_m'])
            dist_km = math.sqrt((tx-ox)**2 + (ty-oy)**2 + (tz-oz)**2) / 1000.0

            for combo in range(15):
                offset = OFFSET_CYCLE[combo % 3]
                angle = sun_angle_deg(obs[fid], tgt[fid], sun[fid], offset)
                if fixed_energy is None:
                    energy = energy_for(fid, combo)
                else:
                    energy = fixed_energy
                fname = (f'frame_{fid:04d}.png' if combo == 0
                         else f'frame_{fid:04d}_v{combo:03d}.png')
                rows.append({
                    'filename': fname,
                    'frame_id': fid,
                    'variation': combo,
                    'distance_km': f'{dist_km:.3f}',
                    'sun_phase_angle_deg': f'{angle:.2f}',
                    'sun_energy': f'{energy:.1f}',
                })

        out = os.path.join(ann_dir, f'factors_{start}_{end}.csv')
        with open(out, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=[
                'filename', 'frame_id', 'variation',
                'distance_km', 'sun_phase_angle_deg', 'sun_energy'])
            w.writeheader()
            w.writerows(rows)
        print(f'{out}: {len(rows)} rows')


if __name__ == '__main__':
    main()
