"""
Post-hoc factors CSV generator: reconstruct per-image factors (distance,
sun phase angle, sun irradiance, fov) for already-rendered batches from
the ephemeris CSVs. Used to repair satellites whose factors CSV ranges
were lost when a render sub-batch was killed mid-run.

Deterministic values are replicated exactly (same seeds as
render_scene.py): sun angle = seed(frame*10000 + sun_idx + 777) →
uniform(0,180); irradiance = seed(frame*1000 + combo + 9999) →
uniform(range). Python's random module reproduces them.

Usage:
    python tools/gen_factors_csv.py <sat_output_root> [--energy 200.0]
                                       [--range start:end:stride ...]
                                       [--version v2.0|v2.1]

Without --range, generates ONE CSV per segment (matching the render
loop SEGMENTS for the version) and deletes the previous factors_*.csv
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
FOV_DEG = 0.080

# v2.0 config (render_loop_v2.py)
V20_SEGMENTS = [
    (172020, 190592, 131),   # lt70km
    (136787, 172019, 1040),  # 70_250km_0
    (190593, 225823, 1040),  # 70_250km_1
]
V20_ENERGY = (60.0, 200.0)
V20_OFFSET_CYCLE = [0.0, 60.0, 120.0]  # fixed 3 sun phases

# v2.1 config (render_loop_v2_1.py): 5 attitude x 10 sun (1 true + 9 random)
V21_SEGMENTS = [
    (172020, 190592, 450),   # lt70km
    (136787, 172019, 3400),  # 70_250km_0
    (190593, 225823, 3600),  # 70_250km_1
]
V21_ENERGY = (950.0, 1770.0)
V21_NUM_SUN = 10


def energy_for(frame, combo, energy_range):
    """Replicate render_scene.py's deterministic sun irradiance sampling."""
    rng = random.Random(frame * 1000 + combo + 9999)
    return rng.uniform(energy_range[0], energy_range[1])


def sun_offset_for(frame, sun_idx, version):
    """Replicate render_scene.py's sun angle selection."""
    if version == 'v2.1':
        if sun_idx == 0:
            return 0.0  # true physical angle
        rng = random.Random(frame * 10000 + sun_idx + 777)
        return rng.uniform(0.0, 180.0)
    else:  # v2.0 fixed offsets
        return V20_OFFSET_CYCLE[sun_idx % 3]


def stride_for(start, segments):
    for seg_start, seg_end, seg_stride in segments:
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
    version = 'v2.1'
    argv = [a for a in sys.argv[1:]]
    if '--version' in argv:
        version = argv[argv.index('--version') + 1]
        argv = argv[:argv.index('--version')] + argv[argv.index('--version') + 2:]
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
        print('Usage: gen_factors_csv.py <sat_output_root> [--version v2.0|v2.1] '
              '[--energy 200.0] [--range start:end:stride ...]')
        return

    segments = V21_SEGMENTS if version == 'v2.1' else V20_SEGMENTS
    energy_range = V21_ENERGY if version == 'v2.1' else V20_ENERGY
    num_sun = V21_NUM_SUN if version == 'v2.1' else 3
    num_combos = 5 * num_sun

    ann_dir = os.path.join(sat_root, 'annotations')
    if custom_ranges:
        ranges = custom_ranges
    else:
        # Full per-segment coverage; delete old fragmented CSVs first
        for fp in glob.glob(os.path.join(ann_dir, 'factors_*.csv')):
            os.remove(fp)
        ranges = [(s, e - 1, st) for s, e, st in segments]

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

            for combo in range(num_combos):
                sun_idx = combo % num_sun
                offset = sun_offset_for(fid, sun_idx, version)
                angle = sun_angle_deg(obs[fid], tgt[fid], sun[fid], offset)
                if fixed_energy is None:
                    energy = energy_for(fid, combo, energy_range)
                else:
                    energy = fixed_energy
                fname = (f'frame_{fid:04d}.png' if combo == 0
                         else f'frame_{fid:04d}_v{combo:03d}.png')
                row = {
                    'filename': fname,
                    'frame_id': fid,
                    'variation': combo,
                    'distance_km': f'{dist_km:.3f}',
                    'sun_phase_angle_deg': f'{angle:.2f}',
                }
                if version == 'v2.1':
                    row['sun_irradiance_w_m2'] = f'{energy:.1f}'
                    row['fov_deg'] = f'{FOV_DEG:.3f}'
                else:
                    row['sun_energy'] = f'{energy:.1f}'
                rows.append(row)

        out = os.path.join(ann_dir, f'factors_{start}_{end}.csv')
        with open(out, 'w', newline='') as f:
            fieldnames = ['filename', 'frame_id', 'variation', 'distance_km',
                          'sun_phase_angle_deg']
            if version == 'v2.1':
                fieldnames += ['sun_irradiance_w_m2', 'fov_deg']
            else:
                fieldnames += ['sun_energy']
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        print(f'{out}: {len(rows)} rows')


if __name__ == '__main__':
    main()
