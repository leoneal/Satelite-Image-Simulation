"""
Generate synthetic point-target images for far-range detection algorithm training.
No Blender dependency — pure analytical projection + Gaussian PSF synthesis.

Output per batch:
  dataset_point/<tag>/
    images/frame_XXXXX.png       # 8-bit grayscale PNG
    labels.csv                   # frame_id, cx_px, cy_px, brightness, dist_km, sun_phase_deg
"""

import os, csv, math, sys, struct, zlib
import numpy as np

KM_SCALE = 0.001
TARGET_SIZE_M = 63.0  # DSP satellite ×10 model_scale (for 1-3 px visibility)


def load_csv(filepath):
    rows = []
    with open(filepath) as f:
        for row in csv.DictReader(f):
            rows.append({k: float(v) for k, v in row.items()})
    return rows


def psf_gaussian(size=5, sigma=0.7):
    """2D Gaussian PSF kernel (normalized, sum=1.0)."""
    ax = np.linspace(-(size-1)/2, (size-1)/2, size)
    x, y = np.meshgrid(ax, ax)
    kernel = np.exp(-(x**2 + y**2) / (2 * sigma**2))
    return kernel / kernel.sum()


def generate_starfield(H, W, n_stars=2000, seed=42):
    """Generate a starfield background: sparse bright pixels with power-law brightness.
    Returns (star_ys, star_xs, star_brightness) arrays."""
    rng = np.random.RandomState(seed)
    xs = rng.randint(0, W, n_stars)
    ys = rng.randint(0, H, n_stars)
    # Power-law brightness: many dim stars, few bright ones
    brightness = rng.pareto(0.8, n_stars) * 80.0
    brightness = np.clip(brightness, 30, 250)
    return ys, xs, brightness


def apply_starfield(img, star_ys, star_xs, star_brightness, psf_kernel):
    """Add stars to image using PSF kernel."""
    ps = psf_kernel.shape[0] // 2
    H, W = img.shape
    for y, x, b in zip(star_ys, star_xs, star_brightness):
        for ky in range(-ps, ps + 1):
            for kx in range(-ps, ps + 1):
                px, py = x + kx, y + ky
                if 0 <= px < W and 0 <= py < H:
                    img[py, px] += b * psf_kernel[ky + ps, kx + ps]
    return img


def save_grayscale_png(data, filepath):
    """Save uint8 2D array as 8-bit grayscale PNG (pure stdlib, no PIL)."""
    h, w = data.shape
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>IIBBBBB', w, h, 8, 0, 0, 0, 0)
    ihdr = struct.pack('>I', len(ihdr_data)) + b'IHDR' + ihdr_data
    ihdr += struct.pack('>I', zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff)
    raw = b''.join(b'\x00' + data[y].tobytes() for y in range(h))
    idat_data = zlib.compress(raw, 6)
    idat = struct.pack('>I', len(idat_data)) + b'IDAT' + idat_data
    idat += struct.pack('>I', zlib.crc32(b'IDAT' + idat_data) & 0xffffffff)
    iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', zlib.crc32(b'IEND') & 0xffffffff)
    with open(filepath, 'wb') as f:
        f.write(sig + ihdr + idat + iend)


def main(ephem_dir, output_dir, tag, start=0, end=None, stride=1,
         W=2048, H=2048, fov_deg=0.117, camera_mode='track',
         psf_sigma=0.7, bg_noise_std=3.0, min_brightness=0.3, max_brightness=1.0):
    """Generate point-target images and labels."""
    FOV_H_rad = math.radians(fov_deg)

    obs_data = load_csv(os.path.join(ephem_dir, 'observer_state.csv'))
    tgt_data = load_csv(os.path.join(ephem_dir, 'target_state.csv'))
    sun_data = load_csv(os.path.join(ephem_dir, 'sun_state.csv'))
    aux_data = load_csv(os.path.join(ephem_dir, 'aux_data.csv'))

    N = len(obs_data)
    if end is None:
        end = N
    else:
        end = min(end, N)

    frame_indices = list(range(start, end, stride))

    # Output directories
    img_dir = os.path.join(output_dir, 'images')
    os.makedirs(img_dir, exist_ok=True)
    labels_path = os.path.join(output_dir, 'labels.csv')

    # In stare mode, capture initial boresight
    stare_dir = None
    if camera_mode == 'stare':
        ox0 = obs_data[start]['pos_x_m'] * KM_SCALE
        oy0 = obs_data[start]['pos_y_m'] * KM_SCALE
        oz0 = obs_data[start]['pos_z_m'] * KM_SCALE
        tx0 = tgt_data[start]['pos_x_m'] * KM_SCALE
        ty0 = tgt_data[start]['pos_y_m'] * KM_SCALE
        tz0 = tgt_data[start]['pos_z_m'] * KM_SCALE
        d = math.sqrt((tx0-ox0)**2 + (ty0-oy0)**2 + (tz0-oz0)**2)
        stare_dir = ((tx0-ox0)/d, (ty0-oy0)/d, (tz0-oz0)/d)

    # PSF kernel for target
    psf = psf_gaussian(sigma=psf_sigma)

    # Generate starfield once (stars are fixed in the image for stare mode)
    star_ys, star_xs, star_brightness = generate_starfield(H, W, n_stars=10000)
    star_psf = psf_gaussian(size=5, sigma=0.7)

    labels = []
    for frame_idx, actual_idx in enumerate(frame_indices):
        obs = obs_data[actual_idx]
        tgt = tgt_data[actual_idx]
        aux = aux_data[actual_idx]

        ox = obs['pos_x_m'] * KM_SCALE
        oy = obs['pos_y_m'] * KM_SCALE
        oz = obs['pos_z_m'] * KM_SCALE
        tx = tgt['pos_x_m'] * KM_SCALE
        ty = tgt['pos_y_m'] * KM_SCALE
        tz = tgt['pos_z_m'] * KM_SCALE

        dx, dy, dz = tx - ox, ty - oy, tz - oz
        dist_km = math.sqrt(dx*dx + dy*dy + dz*dz)
        direction = (dx/dist_km, dy/dist_km, dz/dist_km)

        if camera_mode == 'stare' and stare_dir is not None:
            zx, zy, zz = -stare_dir[0], -stare_dir[1], -stare_dir[2]
        else:
            zx, zy, zz = -direction[0], -direction[1], -direction[2]

        ux, uy, uz = 0.0, 0.0, 1.0
        if abs(zx*ux + zy*uy + zz*uz) > 0.9999:
            ux, uy, uz = 1.0, 0.0, 0.0

        xx = uy*zz - uz*zy
        xy = uz*zx - ux*zz
        xz = ux*zy - uy*zx
        nx = math.sqrt(xx*xx + xy*xy + xz*xz)
        xx, xy, xz = xx/nx, xy/nx, xz/nx

        yx = zy*xz - zz*xy
        yy = zz*xx - zx*xz
        yz = zx*xy - zy*xx
        ny = math.sqrt(yx*yx + yy*yy + yz*yz)
        yx, yy, yz = yx/ny, yy/ny, yz/ny

        tx_rel, ty_rel, tz_rel = tx - ox, ty - oy, tz - oz
        x_cam = xx*tx_rel + xy*ty_rel + xz*tz_rel
        y_cam = yx*tx_rel + yy*ty_rel + yz*tz_rel
        z_cam = zx*tx_rel + zy*ty_rel + zz*tz_rel

        if z_cam >= 0:
            continue

        depth = -z_cam
        tan_half = math.tan(FOV_H_rad / 2.0)
        ndc_x = x_cam / (depth * tan_half)
        ndc_y = y_cam / (depth * tan_half)
        cx_px = (ndc_x + 1.0) * W / 2.0
        cy_px = (1.0 - ndc_y) * H / 2.0

        # Target apparent size and brightness
        target_rad = TARGET_SIZE_M / (dist_km * 1000.0)
        target_px = target_rad / FOV_H_rad * W

        # Brightness: drop with distance², modulate by sun phase
        sun_phase = aux.get('sun_phase_deg', 90.0)
        ref_dist = 100.0
        dist_factor = (ref_dist / max(ref_dist, dist_km)) ** 2
        phase_factor = 0.3 + 0.7 * (1.0 - abs(math.cos(math.radians(sun_phase))))
        brightness = min_brightness + dist_factor * phase_factor * (max_brightness - min_brightness)

        # Generate image: dark background with Gaussian noise
        img = np.abs(np.random.normal(0, bg_noise_std, (H, W))).astype(np.float32)

        # Apply starfield background
        apply_starfield(img, star_ys, star_xs, star_brightness, star_psf)

        # Place PSF at nearest integer pixel (1-3 px visible spot)
        cx_int, cy_int = int(round(cx_px)), int(round(cy_px))
        ps = psf.shape[0] // 2
        # Peak: clearly visible as 2-3 px bright spot (target 100-200 counts)
        peak = brightness * 2500.0
        for ky in range(-ps, ps + 1):
            for kx in range(-ps, ps + 1):
                px, py = cx_int + kx, cy_int + ky
                if 0 <= px < W and 0 <= py < H:
                    weight = psf[ky + ps, kx + ps]
                    if weight > 0.001:
                        img[py, px] += peak * weight

        img = np.clip(img, 0, 255).astype(np.uint8)

        fname = f'frame_{actual_idx:04d}.png'
        save_grayscale_png(img, os.path.join(img_dir, fname))

        labels.append((actual_idx, f'{cx_px:.3f}', f'{cy_px:.3f}',
                       f'{brightness:.4f}', f'{dist_km:.1f}', f'{sun_phase:.1f}'))

        if (frame_idx + 1) % 100 == 0:
            print(f"  [{frame_idx + 1}/{len(frame_indices)}] Frame {actual_idx}: "
                  f"({cx_px:.1f}, {cy_px:.1f}) px, dist={dist_km:.1f} km, "
                  f"brightness={brightness:.3f}")

    with open(labels_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['frame_id', 'cx_px', 'cy_px', 'brightness', 'dist_km', 'sun_phase_deg'])
        writer.writerows(labels)

    print(f"\nPoint target dataset: {len(labels)} frames")
    print(f"  Images: {img_dir}")
    print(f"  Labels: {labels_path}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--ephem_dir', required=True)
    parser.add_argument('--output_dir', required=True)
    parser.add_argument('--tag', default='point_default')
    parser.add_argument('--start', type=int, default=0)
    parser.add_argument('--end', type=int, default=None)
    parser.add_argument('--stride', type=int, default=1)
    parser.add_argument('--resolution', type=int, default=2048)
    parser.add_argument('--fov', type=float, default=14.0)
    parser.add_argument('--camera_mode', default='stare')
    parser.add_argument('--psf_sigma', type=float, default=0.7)
    parser.add_argument('--bg_noise_std', type=float, default=3.0)
    args = parser.parse_args()

    output_dir = os.path.join(args.output_dir, args.tag)
    main(args.ephem_dir, output_dir, args.tag,
         start=args.start, end=args.end, stride=args.stride,
         W=args.resolution, H=args.resolution,
         fov_deg=args.fov, camera_mode=args.camera_mode,
         psf_sigma=args.psf_sigma, bg_noise_std=args.bg_noise_std)
