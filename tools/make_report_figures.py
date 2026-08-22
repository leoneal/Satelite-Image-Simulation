"""Generate figures for the leadership report:
1. satellite_gallery.png — 13 satellites' beauty renders at closest approach
2. annotation_sample.png — beauty + colorized instance mask example
"""
import os
import numpy as np
from PIL import Image
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

ROOT = "E:/sat_dataset/v2.0"
DOCS_IMG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "docs", "images")
os.makedirs(DOCS_IMG, exist_ok=True)

FRAME = "frame_181190.png"  # closest approach sample (~47.7 km)

SATS = [
    ("NavSat_1_Beidou-GEO", "导航卫星"),
    ("NavSat_5_gps2", "导航卫星"),
    ("NavSat_3_galileo-sat", "导航卫星"),
    ("OptSat_41_sbirs-high", "光学遥感卫星"),
    ("OptSat_46-soho", "光学遥感卫星"),
    ("OptSat_2_aqua", "光学遥感卫星"),
    ("MicSat_12_terraSAR", "微波遥感卫星"),
    ("MicSat_03_3cosmo-skymed", "微波遥感卫星"),
    ("ComSat_42-tdrs", "通信卫星"),
    ("ComSat_47_wgs", "通信卫星"),
    ("ComSat_30_Milstar", "通信卫星"),
    ("ComSat_3_AEHF", "通信卫星"),
    ("DSP", "光学遥感卫星"),
]


def crop_center(img, size):
    """Center-crop a square region (satellite is at image center)."""
    w, h = img.size
    left = (w - size) // 2
    top = (h - size) // 2
    return img.crop((left, top, left + size, top + size))


def make_gallery():
    n = len(SATS)
    cols, rows = 4, 4
    fig, axes = plt.subplots(rows, cols, figsize=(12, 12.5))
    for i, (name, cat) in enumerate(SATS):
        ax = axes[i // cols][i % cols]
        fp = os.path.join(ROOT, name, "images", "lt70km", FRAME)
        if not os.path.exists(fp):
            ax.text(0.5, 0.5, "缺失", ha='center', va='center')
            ax.set_xticks([]); ax.set_yticks([])
            continue
        img = Image.open(fp)
        crop = crop_center(img, 900)
        ax.imshow(np.array(crop))
        # Display name: strip category prefix for brevity
        parts = name.split('_', 1)
        short = parts[1] if len(parts) > 1 else name
        ax.set_title(f"{short}\n{cat}", fontsize=11)
        ax.set_xticks([]); ax.set_yticks([])
    # Hide last (empty) subplot
    axes[3][3].axis('off')
    fig.suptitle("13 颗卫星仿真渲染（最近距离 47.7 km，2048×2048 原图中心裁剪）",
                 fontsize=15)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    out = os.path.join(DOCS_IMG, "satellite_gallery.png")
    fig.savefig(out, dpi=110)
    plt.close(fig)
    print(f"Gallery: {out}")


def make_annotation_sample():
    sat = "NavSat_1_Beidou-GEO"
    beauty_fp = os.path.join(ROOT, sat, "images", "lt70km", FRAME)
    mask_fp = os.path.join(ROOT, sat, "annotations", "instance_masks",
                           "lt70km", FRAME)

    beauty = crop_center(Image.open(beauty_fp), 900)
    mask_img = np.array(crop_center(Image.open(mask_fp), 900))

    # Colorize mask values (x50 encoding): 0=bg, 50=body, 100/150=panels, 250=cap
    cmap = ListedColormap(['#000000', '#ffd54f', '#4fc3f7', '#81c784',
                           '#e57373', '#ba68c8', '#ffb74d'])
    bounds = [0, 1, 99, 149, 199, 249, 255]
    norm = BoundaryNorm(bounds, cmap.N)
    masked = np.ma.masked_where(mask_img == 0, mask_img)

    fig, axes = plt.subplots(1, 2, figsize=(12, 6))
    axes[0].imshow(np.array(beauty))
    axes[0].set_title("渲染图像（Beauty）", fontsize=13)
    axes[0].set_xticks([]); axes[0].set_yticks([])

    axes[1].imshow(np.array(beauty))
    axes[1].imshow(masked, cmap=cmap, norm=norm, alpha=0.75,
                   interpolation='nearest')
    axes[1].set_title("实例分割标注（彩色叠加）", fontsize=13)
    axes[1].set_xticks([]); axes[1].set_yticks([])

    fig.suptitle("标注示例：北斗 GEO 卫星（部件级实例分割）", fontsize=15)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out = os.path.join(DOCS_IMG, "annotation_sample.png")
    fig.savefig(out, dpi=110)
    plt.close(fig)
    print(f"Annotation sample: {out}")


if __name__ == '__main__':
    make_gallery()
    make_annotation_sample()
