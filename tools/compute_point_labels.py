"""
Compute target satellite image-plane coordinates analytically from ECI data.
No Blender dependency - pure geometry from CSV positions + camera model.

Output: point_labels.csv with columns:
  frame_id, cx_px, cy_px, dist_km, target_px, tier

  where (cx_px, cy_px) = sub-pixel float coordinates in image space (0,0 = top-left)
  tier 1: target < 1 px  (point detection only)
  tier 2: 1-5 px        (point + simple bbox)
  tier 3: > 5 px        (full mask/COCO pipeline)
"""
import os, csv, math, sys
import numpy as np

# === Camera parameters (must match render_scene.py exactly) ===
TARGET_SIZE_M = 10.0             # approximate satellite diameter (meters)
KM_SCALE = 0.001                 # CSV coords in meters -> km for computation
# Note: projection math uses km-scale (same as Blender scene)


def load_csv(filepath):
    rows = []
    with open(filepath) as f:
        for row in csv.DictReader(f):
            rows.append({k: float(v) for k, v in row.items()})
    return rows


def main(ephem_dir, output_path, W=2048, H=2048, fov_deg=0.117, camera_mode='track'):
    FOV_H_rad = math.radians(fov_deg)
    obs_data = load_csv(os.path.join(ephem_dir, 'observer_state.csv'))
    tgt_data = load_csv(os.path.join(ephem_dir, 'target_state.csv'))
    N = len(obs_data)

    # In stare mode, capture initial boresight direction
    stare_dir = None
    if camera_mode == 'stare':
        ox0 = obs_data[0]['pos_x_m'] * KM_SCALE
        oy0 = obs_data[0]['pos_y_m'] * KM_SCALE
        oz0 = obs_data[0]['pos_z_m'] * KM_SCALE
        tx0 = tgt_data[0]['pos_x_m'] * KM_SCALE
        ty0 = tgt_data[0]['pos_y_m'] * KM_SCALE
        tz0 = tgt_data[0]['pos_z_m'] * KM_SCALE
        dx, dy, dz = tx0-ox0, ty0-oy0, tz0-oz0
        d = math.sqrt(dx*dx + dy*dy + dz*dz)
        stare_dir = (dx/d, dy/d, dz/d)

    results = []
    for i in range(N):
        # Extract ECI positions (meters -> km)
        ox = obs_data[i]['pos_x_m'] * KM_SCALE
        oy = obs_data[i]['pos_y_m'] * KM_SCALE
        oz = obs_data[i]['pos_z_m'] * KM_SCALE
        tx = tgt_data[i]['pos_x_m'] * KM_SCALE
        ty = tgt_data[i]['pos_y_m'] * KM_SCALE
        tz = tgt_data[i]['pos_z_m'] * KM_SCALE

        # Observer -> Target direction vector
        dx = tx - ox
        dy = ty - oy
        dz = tz - oz
        dist_km = math.sqrt(dx*dx + dy*dy + dz*dz)
        direction = (dx/dist_km, dy/dist_km, dz/dist_km)

        # In stare mode, use fixed boresight instead of tracking direction
        if camera_mode == 'stare' and stare_dir is not None:
            dir_x, dir_y, dir_z = stare_dir
            # Camera +Z points AWAY from the stare direction
            zx, zy, zz = -dir_x, -dir_y, -dir_z
        else:
            # Track mode: camera always points at current target
            zx, zy, zz = -direction[0], -direction[1], -direction[2]

        # Up vector = ECI Z (0,0,1)
        ux, uy, uz = 0.0, 0.0, 1.0

        # Handle degenerate case (camera looking parallel to Z axis)
        dot_zu = zx*ux + zy*uy + zz*uz
        if abs(dot_zu) > 0.9999:
            ux, uy, uz = 1.0, 0.0, 0.0

        # Camera X axis = up × Z
        xx = uy*zz - uz*zy
        xy = uz*zx - ux*zz
        xz = ux*zy - uy*zx
        nx = math.sqrt(xx*xx + xy*xy + xz*xz)
        xx, xy, xz = xx/nx, xy/nx, xz/nx

        # Camera Y axis = Z × X (re-orthogonalize)
        yx = zy*xz - zz*xy
        yy = zz*xx - zx*xz
        yz = zx*xy - zy*xx
        ny = math.sqrt(yx*yx + yy*yy + yz*yz)
        yx, yy, yz = yx/ny, yy/ny, yz/ny

        # Target position in camera frame: P_cam = R^T * (P - P_camera)
        tx_rel = tx - ox
        ty_rel = ty - oy
        tz_rel = tz - oz
        x_cam = xx*tx_rel + xy*ty_rel + xz*tz_rel
        y_cam = yx*tx_rel + yy*ty_rel + yz*tz_rel
        z_cam = zx*tx_rel + zy*ty_rel + zz*tz_rel

        # Perspective projection (camera looks along -Z)
        if z_cam >= 0:
            # Target behind camera - shouldn't happen in our scenario
            continue

        depth = -z_cam  # positive distance in view direction
        tan_half = math.tan(FOV_H_rad / 2.0)

        # NDC (Normalized Device Coordinates): -1 to 1
        ndc_x = x_cam / (depth * tan_half)
        ndc_y = y_cam / (depth * tan_half)

        # Pixel coordinates (0,0) = top-left, Y increases downward
        cx_px = (ndc_x + 1.0) * W / 2.0
        cy_px = (1.0 - ndc_y) * H / 2.0  # flip Y: Blender +Y up -> image +Y down

        # Target angular size and pixel footprint
        target_rad = TARGET_SIZE_M / (dist_km * 1000.0)  # radians
        target_px = target_rad / FOV_H_rad * W

        # Tier classification
        if target_px < 1.0:
            tier = 1
        elif target_px < 5.0:
            tier = 2
        else:
            tier = 3

        results.append((i, cx_px, cy_px, dist_km, target_px, tier))

    # Write output
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['frame_id', 'cx_px', 'cy_px', 'dist_km', 'target_px', 'tier'])
        writer.writerows(results)

    # Summary
    tiers = {1:0, 2:0, 3:0}
    for r in results:
        tiers[r[5]] += 1
    print(f"Point labels: {len(results)} frames")
    print(f"  Tier 1 (<1 px):    {tiers[1]} frames")
    print(f"  Tier 2 (1-5 px):   {tiers[2]} frames")
    print(f"  Tier 3 (>5 px):    {tiers[3]} frames")
    print(f"Written: {output_path}")


if __name__ == '__main__':
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ephem = os.path.join(root, 'output', 'ephemeris')
    out = os.path.join(root, 'output', 'annotations', 'point_labels.csv')
    fov_deg = 0.117
    camera_mode = 'track'

    # Parse optional args: --fov X --camera_mode stare
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--fov' and i+1 < len(args):
            fov_deg = float(args[i+1]); i += 2
        elif args[i] == '--camera_mode' and i+1 < len(args):
            camera_mode = args[i+1]; i += 2
        elif args[i] == '--output' and i+1 < len(args):
            out = args[i+1]; i += 2
        elif args[i] == '--ephem' and i+1 < len(args):
            ephem = args[i+1]; i += 2
        else:
            i += 1
    os.makedirs(os.path.dirname(out), exist_ok=True)
    main(ephem, out, fov_deg=fov_deg, camera_mode=camera_mode)
