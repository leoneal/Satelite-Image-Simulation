# 卫星图像仿真项目

> Satellite Image Simulation Pipeline: STK 11.6 + MATLAB → Blender Cycles

## 项目目标

以观察卫星第一视角对目标卫星进行交会工况连续成像仿真，生成带像素级标注（检测/分割/位姿）的仿真图像数据集，用于空间目标感知算法验证。

**技术管线：** MATLAB 控制 STK 构建双星交会场景 → 导出 ECI 星历 CSV → Blender Cycles 批量渲染 2048×2048 图像 + 自动生成 COCO/YOLO/位姿标注。

## 环境路径

| 项 | 路径 |
|----|------|
| STK 11.6 | `E:\STK_11.6\` |
| STK MATLAB API | `E:\STK_11.6\bin\Matlab`（.m 包装函数）+ `E:\STK_11.6\bin`（.mexw64 二进制，**两个目录都必须 addpath**） |
| MATLAB | `E:\matlab\` |
| Blender 5.2 | `E:\Blender\blender.exe` |
| 项目根 | `F:\钱室\卫星图像仿真\` |
| 工况数据 | `orbit_data.xlsx`（34201 行瞬时根数，1 秒/行，a 单位米，角度单位弧度；原始中文名文件已复制为此 ASCII 名，**MATLAB 代码引用文件一律用 ASCII 名**，GBK 环境下中文路径会乱码） |

## 目录结构

```
config/scenario_config.m    用户配置（轨道参数、时间、传感器）
matlab/main.m               主入口
matlab/+stk_helpers/        STK 操作包（initSTK, buildScenario, exportAllEphemeris, kepler2cart, loadOrbitExcel）
matlab/test_stk_connection.m 连接诊断
blender/render_scene.py     Blender 批量渲染（-b 后台模式）
output/ephemeris/           星历 CSV（observer/target/sun/aux + scene_config.json）
output/images/              渲染帧
docs/stk_basics.md          STK 新手教程
```

## 工作规范（用户明确要求）

1. **渲染输出按批次分类建文件夹**：每批渲染输出到 `output/images/<批次tag>/`（render_scene.py 已支持 `--tag`，默认自动生成 `start_end_s{samples}_r{res}`）。annotations 下 instance_masks/yolo/pose 同样按批次分子目录。禁止不同批次混在一个目录。
2. **小批量验证后必须用户确认再跑大批量**：>100 帧的渲染批次启动前，先跑 ≤50 帧小批量并请用户确认效果，得到同意后才继续。

## 关键约束（踩坑记录，必须遵守）

### 编码
- **所有 .m 文件必须纯 ASCII**（英文注释）。中文 Windows MATLAB 按 GBK 读文件，UTF-8 中文注释必乱码；Write/Edit 工具默认写 UTF-8，写入中文会反复引入乱码。中文文档只放 .md 文件。
- **STK Connect 命令不接受中文路径**：`stkLoadEphemeris` 等把文件路径拼进 TCP 命令串，中文会编码错乱报 "unable to process command"。.e 文件一律先写到 `tempdir`（ASCII）再加载，项目目录只存归档副本。
- **MATLAB 代码引用的文件名一律 ASCII**（GBK 下中文路径字符串变乱码导致 file not found）。

### MATLAB 兼容性（用户版本 < R2019a）
- **没有 `readmatrix`**——用 `xlsread` 回退（自动跳过文本表头，返回数值矩阵）。
- `jsonencode` 不支持 `'PrettyPrint'` 参数——直接 `jsonencode(s)`。
- `datetime(..., 'Locale', 'en_US')` 必须显式指定，否则中文 locale 无法解析英文月份名。
- 包（+package）内函数互调**必须带包前缀**（`stk_helpers.func`），且新建包内文件后可能要 `rehash` 或重启 MATLAB。

### STK 连接
- **COM 启动 + Connect API 操作**的混合模式：`actxserver('STK11.Application')` 启动（或 `actxGetRunningServer` 接管已有实例），然后 `stkOpen(stkDefaultHost)` + `stkInit`。
- 纯 TCP Connect 启动 STK 不稳定：连接池会被失败连接占满（"maximum number of connections"），错误 10054（对端重置）频发。**失败后要任务管理器杀光 STK.exe / MATLAB.exe 进程再重试**。
- `stkOpen` **只能连接已在运行的 STK**，不能启动它。
- 函数返回的 `app` 是局部变量时 MATLAB 退出函数会回收 COM 对象导致 STK 被关掉——必须 `assignin('base', ...)` 保住。

### STK MATLAB API 单位与签名（容易错）
- `stkSetPropClassical(path, prop, coord, tStart, tStop, dt, orbitEpoch, a, e, i, w, RAAN, M, coordEpoch)`：**a 单位米，角度单位弧度**，14 参数（最后有 coordEpoch）。
- `stkSetEphemerisCBI(objPath, cb, time, pos, vel, eFilePath)`：一行完成写 .e 文件 + 加载 + 切换 StkExternal propagator。pos 为 3×N 米，time 为相对场景历元的秒。
- `stkEphemerisCBI/stkAttitudeCBI`：前者可靠；**后者不可靠**（内部走临时文件导出，常报 "not in correct attitude file format"）。姿态四元数改由位置/速度几何计算（观察星 Z 轴指向目标，目标星 Z 轴对地）。
- `stkPosVelCBI('Sun', t)` **不存在**——Sun 不是 propagated vehicle。太阳位置用 Meeus 天文算法解析计算（已实现于 exportAllEphemeris.m）。
- `stkObjNames()` 无参调用，不接受路径。
- 传感器/姿态的 Connect 命令（Define/SetAttitude/SetPointing）在本环境全部语法报错，**目前传感器 EOIR 配置和 Target Pointing 需在 STK GUI 手动完成**（脚本中已非致命化）。

### Blender 5.2
- `bpy.ops.object.delete()` 无 `use_confirm` 参数。
- `Material.use_nodes = True` 已弃用；材质节点必须**显式 new**（`ShaderNodeBsdfPrincipled` 等），不能 `nodes['Principled BSDF']` 按名取。
- **Track To 约束在 -b 后台模式不生效**——相机/太阳指向必须用旋转矩阵直接构造（camera 局部 -Z 朝目标；sun lamp +Z 朝太阳方向）。
- **物体的 `scale` 属性与 emission 材质存在兼容性问题**（scale≠1 时渲染不可见）——几何体用 `size=` 参数直接建成目标尺寸，或 scale 后 `bpy.ops.object.transform_apply(scale=True)`。
- **Denoising 会把 30px 的小目标抹掉**——太空小目标场景必须 `use_denoising = False`、`use_adaptive_sampling = False`。
- **`Render Result` 像素在第二次 `bpy.ops.render.render()`（无 write_still）后读取为空**——标注 mask 必须用 `write_still=True` 写临时 EXR 再 `bpy.data.images.load` 读回（EXR 保留 scene-linear 浮点）。
- `bpy.data.images.new()` 创建的图像 pixels 为空，foreach_set 报 "expected sequence size 4, got 0"——mask PNG 用标准库 zlib/struct 手写编码，绕开 Blender image API。
- PowerShell 调用：`& "E:\Blender\blender.exe" -b -P script.py -- --args`（`&` 前缀必需）。
- **`--ephem_dir` 传相对路径会导致输出写到 `C:\output\`**——脚本内已强制 `os.path.abspath`，但建议始终传绝对路径。

### 场景尺度
- Blender 场景统一用 **km**（m×0.001），相机 clip_start=0.00001 (10m), clip_end=200000 km。
- ECI(J2000) 与 Blender 世界坐标均为右手系 Z-up，**1:1 直接映射**，无需变换。四元数 STK(qx,qy,qz,qw) → Blender 构造 `Quaternion((qw,qx,qy,qz))`。

## 当前进度

- 阶段 1-3 完成：连接、场景构建、星历导出
- 阶段 4 进行中：单帧渲染成功（目标 ~30×30 px @ 117 km）
- **工况数据接入完成**：`orbit_data.xlsx`（34201 行瞬时根数）→ `loadOrbitExcel` 转换修复（4 行退化数据插值修复，误差 0.001 km）→ `stkSetEphemerisCBI` 加载 STK → 全工况 CSV 导出（距离剖面 16327→47.8→11198 km，太阳相位角 40-142°）
- Blender 抽帧渲染（--stride）验证批进行中

## 常用命令

```powershell
# Blender 批量渲染（后台）
& "E:\Blender\blender.exe" -b -P "F:\钱室\卫星图像仿真\blender\render_scene.py" -- --ephem_dir "F:\钱室\卫星图像仿真\output\ephemeris" --start 0 --end 5 --samples 64 --resolution 2048
```

```matlab
% MATLAB 主入口（STK 会被脚本自动启动）
cd 'F:\钱室\卫星图像仿真\matlab'
main
```
