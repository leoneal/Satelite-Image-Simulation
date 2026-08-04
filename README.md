# 卫星图像仿真系统

> Satellite Image Simulation Pipeline: STK 11.6 + MATLAB → Blender Cycles

## 项目简介

以观察卫星第一视角对目标卫星进行 GEO 交会工况连续成像仿真，生成带像素级标注（检测/分割/位姿）的仿真图像数据集，用于空间目标感知算法验证。

**技术路线：** MATLAB 控制 STK 构建双星交会场景 → 导出 ECI 星历 CSV → Blender Cycles 批量渲染 2048×2048 图像 + 自动生成 COCO/YOLO/位姿标注。

## 目录结构

```
├── config/
│   └── scenario_config.m         用户配置（轨道参数、时间、传感器）
├── matlab/
│   ├── main.m                    主入口
│   └── +stk_helpers/             STK 操作包
│       ├── initSTK.m             连接 STK (COM + Connect)
│       ├── buildScenario.m       构建双星交会场景
│       ├── exportAllEphemeris.m  导出星历 CSV + JSON
│       ├── kepler2cart.m         开普勒轨道根数 → ECI 坐标
│       └── loadOrbitExcel.m      Excel 轨道数据加载
├── blender/
│   ├── render_scene.py           ★ 主渲染脚本（-b 后台模式）
│   ├── fbx_minimal.py            FBX 模型正确加载参考
│   ├── inspect_model.py          检查 FBX 模型结构
│   └── check_*.py                纹理/材质/贴图验证工具
├── tools/
│   ├── build_coco.py             从 mask PNG 重建 COCO 标注
│   ├── compute_point_labels.py   亚像素点坐标分析
│   └── md2docx.py                Markdown → Word 转换
├── data/
│   ├── earth_textures/           地球贴图 (8K Blue Marble)
│   ├── sat_models/DSP/           卫星 3D 模型 (FBX)
│   └── star_bg/                  星空背景贴图
├── output/
│   ├── ephemeris/                星历 CSV (MATLAB 导出)
│   ├── images/<tag>/             渲染帧 (按批次分子目录)
│   └── annotations/              标注文件
│       ├── instance_masks/<tag>/ 实例分割 PNG
│       ├── yolo/<tag>/           YOLO 标注
│       ├── pose/<tag>/           位姿真值
│       ├── coco_detection_*.json
│       ├── coco_segmentation_*.json
│       └── splits.json           train/val 划分
└── docs/
    ├── 开发手册.md               完整开发手册（架构、命令、踩坑）
    ├── 仿真参数汇总.md           仿真分段参数速查
    ├── 仿真方案说明报告.md        技术报告
    └── stk_basics.md             STK 新手教程
```

## 快速开始

### 环境要求

| 软件 | 版本 | 备注 |
|------|------|------|
| STK | 11.6 | 需含 MATLAB Connector |
| MATLAB | R2018a+ | COM/ActiveX 支持 |
| Blender | 5.2 LTS | Cycles 渲染引擎 |
| Windows | 10/11 Pro | STK 仅支持 Windows |

### 第一步：MATLAB 生成星历

```matlab
cd '~/project/matlab'
main
```

STK 会自动启动，构建双星交会场景，导出星历 CSV 到 `output/ephemeris/`。

### 第二步：Blender 批量渲染

```powershell
# segB 核心段 (track 模式, 窄视场, 全标注)
blender -b -P blender/render_scene.py -- \
  --ephem_dir output/ephemeris \
  --start 23165 --end 23609 --stride 1 \
  --samples 64 --resolution 2048 --fov 0.08 \
  --camera_mode track --model_type dsp_blend \
  --tag "segB_DSP_full_23165_23608_s64_r2048"

# segA/segC 远距段 (stare 模式, 宽视场, 无标注)
blender -b -P blender/render_scene.py -- \
  --ephem_dir output/ephemeris \
  --start 22482 --end 23166 --stride 25 \
  --samples 32 --resolution 2048 --fov 14 \
  --camera_mode stare --model_scale 10.0 \
  --model_type dsp_blend --no_annotations \
  --tag "segA_DSP_stare_22482_23165_s32_r2048_x10"
```

### CLI 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--ephem_dir` | (必填) | 星历 CSV 目录 |
| `--start` / `--end` | 0 / all | 帧范围 |
| `--stride` | 1 | 帧间隔 |
| `--samples` | 64 | Cycles 采样数 |
| `--resolution` | 2048 | 正方形分辨率 |
| `--fov` | 0.117 | 相机视场角 (度) |
| `--camera_mode` | track | `track` (追踪) / `stare` (固定指向) |
| `--model_type` | auto | `auto` / `dsp_blend` / `simple` |
| `--model_scale` | 1.0 | 模型缩放倍数 |
| `--tag` | auto | 输出子文件夹名 |
| `--no_annotations` | false | 跳过标注生成 |

## 仿真分段

| 段 | 时间 (s) | 距离 (km) | 模式 | FOV | 帧数 | 标注 |
|------|----------|----------|------|-----|------|------|
| segA | 22482–23165 | 1000→250 | stare | 14° | 28 | 无 |
| segB | 23165–23608 | 250→47.8→250 | track | 0.08° | 444 | 全标注 |
| segC | 23608–24291 | 250→1000 | stare | 14° | 28 | 无 |

## 标注格式

支持 COCO (检测 + RLE 分割)、YOLO、位姿真值。5 个标注类别：body、solar_panel、phased_array_antenna、reflector_antenna、solar_panel_tripod。

## 文档

- [开发手册](docs/开发手册.md) — 完整架构、命令、踩坑记录、调试索引
- [仿真参数汇总](docs/仿真参数汇总.md) — 分段参数速查表
- [仿真方案说明报告](docs/仿真方案说明报告.md) — 详细技术报告
- [STK 基础教程](docs/stk_basics.md) — STK 新手入门
