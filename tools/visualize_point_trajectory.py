"""Visualize point target trajectory across frames: background + tracked positions."""
import os, csv, struct, zlib
import numpy as np

project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_png(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()
    ihdr_pos = data.find(b'IHDR')
    w = struct.unpack('>I', data[ihdr_pos+4:ihdr_pos+8])[0]
    h = struct.unpack('>I', data[ihdr_pos+8:ihdr_pos+12])[0]
    color_type = data[ihdr_pos+13]
    channels = 1 if color_type == 0 else 3
    pos = data.find(b'IDAT')
    raw = b''
    while pos != -1:
        length = struct.unpack('>I', data[pos-4:pos])[0]
        raw += data[pos+4:pos+4+length]
        pos = data.find(b'IDAT', pos+4+length)
    raw = zlib.decompress(raw)
    row_size = w * channels + 1
    arr = np.zeros((h, w, channels) if channels > 1 else (h, w), dtype=np.uint8)
    for y in range(h):
        offset = y * row_size + 1
        if channels == 1:
            arr[y] = np.frombuffer(raw[offset:offset+w], dtype=np.uint8)
        else:
            arr[y] = np.frombuffer(raw[offset:offset+w*3], dtype=np.uint8).reshape(w, 3)
    return arr


def save_png_rgb(arr, filepath):
    h, w = arr.shape[:2]
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    ihdr = struct.pack('>I', len(ihdr_data)) + b'IHDR' + ihdr_data
    ihdr += struct.pack('>I', zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff)
    raw = b''.join(b'\x00' + arr[y].tobytes() for y in range(h))
    idat_data = zlib.compress(raw, 6)
    idat = struct.pack('>I', len(idat_data)) + b'IDAT' + idat_data
    idat += struct.pack('>I', zlib.crc32(b'IDAT' + idat_data) & 0xffffffff)
    iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', zlib.crc32(b'IEND') & 0xffffffff)
    with open(filepath, 'wb') as f:
        f.write(sig + ihdr + idat + iend)


def draw_cross(img, cx, cy, size=10, color=(255, 50, 50), thickness=2):
    """Draw a crosshair at (cx, cy)."""
    h, w = img.shape[:2]
    cx_i, cy_i = int(cx), int(cy)
    for dx in range(-size, size+1):
        px = cx_i + dx
        if 0 <= px < w:
            for t in range(-thickness, thickness+1):
                py = cy_i + t
                if 0 <= py < h:
                    img[py, px] = color
    for dy in range(-size, size+1):
        py = cy_i + dy
        if 0 <= py < h:
            for t in range(-thickness, thickness+1):
                px = cx_i + t
                if 0 <= px < w:
                    img[py, px] = color


def draw_circle(img, cx, cy, radius=6, color=(255, 255, 100), thickness=2):
    """Draw a circle at (cx, cy)."""
    h, w = img.shape[:2]
    cx_i, cy_i = int(cx), int(cy)
    for dy in range(-radius, radius+1):
        for dx in range(-radius, radius+1):
            dist = (dx*dx + dy*dy) ** 0.5
            if radius - thickness < dist <= radius:
                px, py = cx_i + dx, cy_i + dy
                if 0 <= px < w and 0 <= py < h:
                    img[py, px] = color


def draw_line(img, x1, y1, x2, y2, color=(255, 255, 100), thickness=1):
    """Bresenham line."""
    h, w = img.shape[:2]
    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
    dx = abs(x2 - x1); dy = abs(y2 - y1)
    sx = 1 if x1 < x2 else -1
    sy = 1 if y1 < y2 else -1
    err = dx - dy
    while True:
        for tx in range(-thickness, thickness+1):
            for ty in range(-thickness, thickness+1):
                px, py = x1+tx, y1+ty
                if 0 <= px < w and 0 <= py < h:
                    img[py, px] = color
        if x1 == x2 and y1 == y2: break
        e2 = 2 * err
        if e2 > -dy: err -= dy; x1 += sx
        if e2 < dx: err += dx; y1 += sy


def main():
    batch_dir = os.path.join(project, 'output', 'dataset_point', 'test_20frames')
    labels_path = os.path.join(batch_dir, 'labels.csv')
    img_dir = os.path.join(batch_dir, 'images')

    # Load labels
    labels = []
    with open(labels_path) as f:
        for row in csv.DictReader(f):
            labels.append((int(row['frame_id']),
                          float(row['cx_px']), float(row['cy_px'])))

    # Load first frame as background
    bg_path = os.path.join(img_dir, f'frame_{labels[0][0]:04d}.png')
    bg = read_png(bg_path)
    if bg.ndim == 2:
        bg = np.stack([bg]*3, axis=-1)
    img = bg.copy()

    # Colors for trajectory
    start_color = (50, 255, 50)   # green = start
    end_color = (255, 50, 50)     # red = end

    # Draw trajectory lines and markers
    prev_x, prev_y = None, None
    for i, (fid, cx, cy) in enumerate(labels):
        # Interpolate color from green to red
        t = i / max(1, len(labels)-1)
        color = (int(50 + 205*t), int(255 - 205*t), 50)

        # Draw marker (first and last get crosses, others get dots)
        if i == 0 or i == len(labels)-1:
            draw_cross(img, cx, cy, size=12, color=color, thickness=2)
            # Label
            print(f'  Frame {fid}: ({cx:.1f}, {cy:.1f}) {"START" if i==0 else "END"}')
        else:
            draw_circle(img, cx, cy, radius=4, color=color, thickness=2)

        # Connect to previous
        if prev_x is not None:
            draw_line(img, prev_x, prev_y, cx, cy, color=color, thickness=1)

        prev_x, prev_y = cx, cy

    # Draw direction arrow on first segment
    if len(labels) >= 2:
        x1, y1 = labels[0][1], labels[0][2]
        x2, y2 = labels[1][1], labels[1][2]
        # Arrowhead
        dx, dy = x2-x1, y2-y1
        d = (dx*dx+dy*dy)**0.5
        if d > 0:
            dx, dy = dx/d*8, dy/d*8
            # Arrow head at midpoint of first segment
            mx, my = (x1+x2)/2, (y1+y2)/2
            draw_cross(img, mx, my, size=6, color=(255, 255, 100), thickness=1)

    out_path = os.path.join(project, 'output', 'sample_images',
                           'sample2_trajectory.png')
    save_png_rgb(img, out_path)
    print(f'\nTrajectory visualization saved: {out_path}')
    print(f'{len(labels)} frames, from ({labels[0][1]:.1f},{labels[0][2]:.1f}) '
          f'to ({labels[-1][1]:.1f},{labels[-1][2]:.1f})')


if __name__ == '__main__':
    main()
