# 卫星图像仿真系统

> Satellite Image Simulation Pipeline
> STK + MATLAB → Blender Cycles

## 项目简介

基于 STK 11.6 和 MATLAB 构建精确的卫星交会仿真场景，导出轨道数据，在 Blender 中使用 Cycles 物理渲染引擎生成真实感仿真图像。

**应用场景：** 空间交会对接过程中，以观察卫星第一视角对目标卫星进行连续成像仿真，生成带有像素级标注的仿真图像数据集，用于目标检测、实例分割和位姿估计算法的验证。

## 技术路线

```
MATLAB (控制) → STK 11.6 (轨道计算) → CSV/JSON 数据 → Blender (真实感渲染) → 仿真图像+标注
```

## 目录结构

```
卫星图像仿真/
├── config/                     # 用户配置
│   └── scenario_config.m       # 轨道六根数 + 仿真参数（在此填写）
├── matlab/                     # MATLAB 脚本
│   ├── main.m                  # 主入口（一键运行）
│   ├── test_stk_connection.m   # STK 连接测试
│   ├── +stk_helpers/           # STK 操作函数包
│   │   ├── initSTK.m           #   连接 STK
│   │   ├── buildScenario.m     #   构建场景
│   │   └── exportAllEphemeris.m #  导出星历（阶段 3）
│   ├── +export/                # 数据导出函数包
│   └── +postprocess/           # 后处理（噪声等）
├── blender/                    # Blender Python 渲染脚本
├── data/                       # 静态资源
│   ├── earth_textures/         #   地球纹理贴图
│   └── sat_models/             #   卫星 3D 模型
├── output/                     # 生成的数据
│   ├── stk_sample_images/      #   STK 样例图像（阶段 2 验证用）
│   ├── ephemeris/              #   导出的星历 CSV 数据
│   ├── images/                 #   渲染的仿真图像
│   ├── annotations/            #   标注文件 (COCO/YOLO/位姿)
│   └── video/                  #   合成视频
└── docs/                       # 文档
    └── stk_basics.md           #   STK 基础操作教程
```

## 快速开始

### 第一步：环境验证

```matlab
cd 'F:\钱室\卫星图像仿真\matlab'
test_stk_connection
```

### 第二步：配置参数

编辑 `config/scenario_config.m`，填写：
- 两颗卫星的轨道六根数
- 仿真时间范围
- 传感器参数（FOV、分辨率）

### 第三步：构建场景

```matlab
main
```

STK 会自动打开并构建场景。在 STK 中你可以：
- 右键传感器 → `Sensor → View From Sensor` 查看第一视角
- 播放动画查看交会过程
- 检查生成的样例图像（`output/stk_sample_images/`）

### 后续步骤（开发中）

- 阶段 3：导出完整星历数据到 CSV
- 阶段 4：Blender 批量渲染 + 标注自动生成

## 系统要求

| 软件 | 版本 | 备注 |
|------|------|------|
| STK | 11.6 | 需含 MATLAB Connector |
| MATLAB | R2018b+ | 需支持 COM/ActiveX |
| Blender | 3.6 LTS 或 4.x | 用于真实感渲染 |
| Windows | 10/11 Pro | STK 仅支持 Windows |

## 文档

- [STK 基础操作教程](docs/stk_basics.md) — 适合 STK 新手
- 技术方案详情：见 `C:\Users\ssplk\.claude\plans\stk-matlab-*.md`
