# 卫星图像仿真系统

> Satellite Image Simulation Pipeline: STK 11.6 + MATLAB → Blender Cycles

## 项目简介

以观察卫星第一视角对目标卫星进行 GEO 交会工况连续成像仿真，生成带像素级标注（检测/分割/位姿/成像条件）的仿真图像数据集，用于空间目标感知算法验证。

**技术路线：** MATLAB 控制 STK 构建双星交会场景 → 导出 ECI 星历 CSV → Blender Cycles 批量渲染 2048×2048 图像 + 自动生成 COCO/YOLO/位姿/影响因素标注。

## 数据集版本

| 版本 | 卫星数 | 图像数 | 说明 | 路径 |
|------|--------|--------|------|------|
| v1.0/v1.1 | 1 (DSP) | 4,700 / 15,000 | 早期单模型数据集 | `output/` |
| v2.0 | 13 | 40,950 | 彩色，5 姿态 × 3 光照 | `E:/sat_dataset/v2.0/` |
| **v2.1（当前）** | **14** | **44,100** | 灰度 + 太阳常数物理光照，5 姿态 × 10 光照角度，含卫星类别标签 | `E:/sat_dataset/v2.1/` |

数据集使用方式见 [数据集使用手册](docs/数据集使用手册.md)。

## 目录结构

```
├── config/
│   └── scenario_config.m         用户配置（轨道参数、时间、传感器）
├── matlab/
│   ├── main.m                    主入口
│   ├── test_stk_connection.m     STK 连接诊断
│   └── +stk_helpers/             STK 操作包
│       ├── initSTK.m             连接 STK (COM + Connect)
│       ├── buildScenario.m       构建双星交会场景
│       ├── exportAllEphemeris.m  导出星历 CSV + JSON
│       ├── kepler2cart.m         开普勒轨道根数 → ECI 坐标
│       └── loadOrbitExcel.m      Excel 轨道数据加载
├── blender/
│   ├── render_scene.py           ★ 主渲染脚本（-b 后台模式）
│   ├── fbx_minimal.py            FBX 模型正确加载参考
│   ├── regenerate_coco.py        mask 通道重渲染修复 COCO 标注
│   ├── setup_and_save.py         场景初始化保存 .blend
│   └── check_*.py                纹理/材质/贴图验证工具
├── tools/
│   ├── render_loop_v2.py         ★ v2.0 批量渲染入口（断点续传）
│   ├── render_loop_v2_1.py       ★ v2.1 批量渲染入口（14 颗卫星）
│   ├── gen_factors_csv.py        factors CSV 确定性重建工具
│   ├── fbx_to_blend.py           134 颗卫星 3ds Max → FBX 批量转换
│   ├── check_textures.py         模型纹理完备性检查
│   ├── build_coco.py             从 mask PNG 重建 COCO 标注
│   ├── md2docx.py                Markdown → Word 转换
│   ├── make_report_figures.py    报告插图生成
│   ├── dataset_builder.py        数据集打包（索引模式）
│   └── point_target_generator.py 分析式点目标图像生成
├── data/
│   ├── earth_textures/           地球贴图 (8K Blue Marble)
│   ├── sat_models/               134 颗卫星模型（.max 源 + .fbx + 纹理）
│   └── star_bg/                  星空背景贴图
├── output/
│   ├── blend_files/              手动标注的卫星 .blend（v2.x 渲染输入）
│   ├── ephemeris/                星历 CSV (MATLAB 导出)
│   ├── images/<tag>/             渲染帧 (按批次分子目录)
│   └── annotations/              标注文件
├── dataset/
│   └── segB_v2/ephemeris/        v2.x 渲染输入星历（200 Hz，362,401 帧）
└── docs/
    ├── 开发手册.md               完整开发手册（架构、命令、踩坑）
    ├── 数据集使用手册.md          数据集格式与使用指南
    ├── 手动标注教程.md            5 类部件手动标注流程
    ├── 仿真方案说明报告.md        技术报告（含领导版）
    ├── 内网迁移方案.md            内网环境迁移部署方案
    └── stk_basics.md             STK 新手教程
```

## 快速开始

### 环境要求

| 软件 | 版本 | 备注 |
|------|------|------|
| STK | 11.6 | 需含 MATLAB Connector；许可见 `C:\ProgramData\AGI\LicenseData\` |
| MATLAB | R2018b | COM/ActiveX 支持；代码按 <R2019a 兼容编写 |
| Blender | 5.2 LTS | Cycles 渲染引擎；GPU OptiX 需 NVIDIA 驱动 ≥ 591 |
| Python | 3.x | numpy / Pillow / matplotlib / python-docx / openpyxl |
| Windows | 10/11 Pro | STK 仅支持 Windows |

STK MATLAB API 需同时 addpath 两个目录：`E:\STK_11.6\bin\Matlab`（.m 包装函数）和 `E:\STK_11.6\bin`（.mexw64 二进制）。

### 第一步：MATLAB 生成星历

```matlab
cd 'F:\钱室\卫星图像仿真\matlab'
main
```

STK 会自动启动，构建双星交会场景，导出星历 CSV。

### 第二步：Blender 批量渲染

```powershell
# v2.1 全量渲染（14 颗卫星，自动断点续传）
python tools\render_loop_v2_1.py
python tools\render_loop_v2_1.py --only ComSat_45_thuraya   # 只渲染单颗
```

或直接调用渲染脚本（单批次）：

```powershell
& "E:\Blender\blender.exe" -b -P blender\render_scene.py -- `
  --ephem_dir dataset\segB_v2\ephemeris `
  --start 172020 --end 190592 --stride 450 `
  --samples 64 --resolution 2048 --fov 0.08 `
  --camera_mode track --model_type auto `
  --model_scale 0.067 --sat_class_id 5 --sat_category_id 19 `
  --frame_variations 5 --sun_phase_count 10 `
  --sun_energy_range "950,1770" --exposure_ev -3.5 `
  --output_root E:\sat_dataset\v2.1\NavSat_1_Beidou-GEO `
  --tag lt70km
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
| `--model_type` | auto | `auto` / `dsp_blend` / `simple`（auto 按 --blend_path → --fbx_path → DSP.blend → FBX → simple 优先级） |
| `--model_scale` | 1.0 | 模型缩放倍数 |
| `--blend_path` | 空 | 手动标注 .blend 路径 |
| `--fbx_path` | 空 | FBX 模型路径（无标注部件，自动分部件类） |
| `--output_root` | 空 | 输出根目录覆盖 |
| `--sat_class_id` | 空 | 整星检测 YOLO 类别（型号 5-18） |
| `--sat_category_id` | 空 | 卫星类别 YOLO 标签（19=导航/20=光学遥感/21=微波/22=通信） |
| `--tag` | auto | 输出子文件夹名 |
| `--no_annotations` | false | 跳过标注生成 |
| `--frame_variations` | 1 | 每帧姿态变体数量 |
| `--attitude_jitter_deg` | 0 | 最大随机姿态扰动角度 |
| `--sun_phase_count` | 0 | 光照角度变体数（1 真实 + N-1 随机 0-180°） |
| `--sun_energy_range` | 空 | 太阳辐照度范围 W/m²，如 `"950,1770"` |
| `--exposure_ev` | 0 | 曝光补偿 EV（v2.1 用 -3.5） |
| `--render_device` | gpu | `gpu` (OptiX) / `cpu` |

## 仿真分段

### v2.0/v2.1 数据集（当前）

200 Hz 星历，362,401 帧（47.7–999.9 km）。v2.1 每星 63 帧 × 50 变体（5 姿态 × 10 光照）= 3,150 张：

| 段 | 帧范围 | 距离 (km) | stride | 帧数 |
|------|----------|----------|--------|------|
| lt70km | 172020–190592 | 47.7–70 | 450 | 42 |
| 70_250km_0 | 136787–172019 | 250–70 | 3400 | 11 |
| 70_250km_1 | 190593–225823 | 70–250 | 3600 | 10 |

### segA/B/C 历史分段（v1.x）

| 段 | 时间 (s) | 距离 (km) | 模式 | FOV | 帧数 | 标注 |
|------|----------|----------|------|-----|------|------|
| segA | 22482–23165 | 1000→250 | stare | 14° | 28 | 无 |
| segB | 23165–23608 | 250→47.8→250 | track | 0.08° | 444 | 全标注 |
| segC | 23608–24291 | 250→1000 | stare | 14° | 28 | 无 |

## 标注体系

**YOLO 类别（23 类）：**

| 范围 | 含义 |
|------|------|
| 0-4 | 部件：body / solar_panel / phased_array / reflector / tripod |
| 5-18 | 卫星型号（整星 bbox） |
| 19-22 | 卫星类别（导航 / 光学遥感 / 微波遥感 / 通信） |

**五种标注格式**（每张图齐备）：YOLO txt、COCO 检测 JSON、COCO 分割 JSON（RLE）、实例分割掩码 PNG（像素值 = 实例编号 × 50）、位姿真值（四元数 + 相对位置）+ 影响因素 CSV（距离 / 光照角度 / 辐照度 / FOV）。

手动标注流程（5 类部件）见 [手动标注教程](docs/手动标注教程.md)。

## 文档

- [数据集使用手册](docs/数据集使用手册.md) — 数据集概况、标注体系、使用方法
- [开发手册](docs/开发手册.md) — 完整架构、命令、踩坑记录、调试索引
- [手动标注教程](docs/手动标注教程.md) — 卫星部件 5 类标注流程
- [仿真方案说明报告](docs/仿真方案说明报告.md) — 详细技术报告（另见领导版）
- [内网迁移方案](docs/内网迁移方案.md) — 内网环境打包与部署
- [134 卫星模型纹理检查报告](docs/134卫星模型纹理检查报告.md) — 模型纹理完备性
- [STK 基础教程](docs/stk_basics.md) — STK 新手入门
