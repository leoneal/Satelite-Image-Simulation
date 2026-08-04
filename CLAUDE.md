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
blender/render_scene.py     Blender 批量渲染（-b 后台模式）★ 主脚本
blender/fbx_minimal.py      FBX 正确加载参考实现
output/ephemeris/           星历 CSV（observer/target/sun/aux + scene_config.json）
output/images/              渲染帧（按批次 tag 分子目录）
output/annotations/         标注（instance_masks/yolo/pose/ + COCO JSON）
docs/开发手册.md            项目完整开发手册（架构、命令、踩坑、调试）
docs/stk_basics.md          STK 新手教程
```

## 当前进度（2026-08-04）

### 已完成
- 阶段 1-3：STK 连接、场景构建、星历导出
- 阶段 4 核心渲染：**DSP 卫星模型 segA/B/C 三个子段全部渲染完成**

### 渲染结果

| 段 | 帧数 | 模式 | FOV | 模型 | 路径 |
|------|------|------|-----|------|------|
| segA | 28 | stare | 14° | DSP ×10 | `segA_DSP_stare_22482_23165_s32_r2048_x10` |
| segB | 444 | track | 0.08° | DSP ×1 | `segB_DSP_full_23165_23608_s64_r2048` |
| segC | 28 | stare | 14° | DSP ×10 | `segC_DSP_stare_23608_24291_s32_r2048_x10` |

### 模型类型（`--model_type` CLI 参数）

| 值 | 来源 | 说明 |
|----|------|------|
| `dsp_blend` | `output/DSP.blend` | 用户手动分离标注面 + 完整模型 `1323_00`（剩余面）。Beauty 渲染两者都可见，Mask 渲染只显示标注面 |
| `simple` | Blender 几何体 | 手搭简易模型（5 部件：body + 2 panels + 2 antennas） |
| `auto` | 自动检测 | 优先 DSP.blend → FBX → simple（默认） |

### 模型缩放（`--model_scale` CLI 参数）
- segB：`--model_scale 1.0`（DSP 真实尺寸 ~6.3m，最近距离 307 px）
- segA/segC：`--model_scale 10.0`（放大到 ~63m，让远距目标达到 0.5–2.1 px 可见）

### 其他 CLI 参数
- `--fov`：相机视场角（默认 0.117°，segA/C 用 14°，segB 用 0.08°）
- `--camera_mode`：`track`（追踪目标）或 `stare`（固定 ECI 指向，segA/C 使用）
- `--no_annotations`：跳过标注生成（segA/C 使用，目标为亚像素点）

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

### Blender FBX 模型导入规范

导入外部 3D 模型（FBX/OBJ 等）必须按以下顺序处理：

1. **删除 FBX 带来的非 mesh 对象**（相机、灯光、空节点）——否则可能覆盖场景相机
2. **Unparent 所有 mesh**（`parent_clear(type='CLEAR_KEEP_TRANSFORM')`）——**必须先用 `select_set(True)` 选中对象，否则 operator 静默失败！**
3. **清除 FBX 自带材质**（`obj.data.materials.clear()`）——否则 FBX 灰色材质覆盖我们的 emission
4. **Bake 所有变换**（`transform_apply(location=True, rotation=True, scale=True)`）——FBX 可能带任意初始变换
5. **顶点数据居中**（几何中心归零）——使 `update_frame` 旋转围绕模型中心
6. **缩放到 km**（`KM_SCALE = 0.001` × model_scale）——统一场景单位
7. **最后加 emission+BSDF 材质**（85% emission, 15% BSDF）——此时 transform 已全部 bake，scale=1.0

参考成功案例：`blender/fbx_minimal.py`。

### 浮点精度——模型在 GEO 距离时几何扭曲的根因 ★★★

**问题发现过程：** 模型在 50m 近距离渲染正常，但在 segB 仿真距离（47.8 km）渲染为"薄片拼插"形状。排查数小时后发现根因不是旋转、不是材质、不是模型加载——是浮点精度。

**根因：** Blender 内部使用 32 位浮点数。在距场景原点 ~42164 km（GEO 轨道）处，float32 精度约 42164 / 2²³ ≈ **5 米**。DSP 卫星仅 6.3 米宽→顶点坐标被截断到 5 米粒度→几何彻底破坏。

**验证方法：** 在 50m 距离测试几何正确，在 47.8 km 绝对坐标下几何错误——两者使用相同的模型和渲染参数。

**修复：** `update_frame()` 将相机放在原点，所有物体用 Python float64 计算相对坐标：

```python
rel_tgt = tgt_pos - obs_pos       # Python float64，精度 ~1e-12 km
camera.location = Vector((0, 0, 0))
model.location = rel_tgt           # 模型在 ~48 km → float32 精度 ~6mm ✓
earth.location = -obs_pos          # 地球在 ~42164 km（精度需求低）
```

关键：相机 `matrix_world` 不再包含 `Translation(obs_pos)`，仅保留旋转矩阵。

### Blender 5.2 已知 bug
- `bpy.ops.object.delete()` 无 `use_confirm` 参数。
- `Material.use_nodes = True` 已弃用；材质节点必须**显式 new**（`ShaderNodeBsdfPrincipled` 等），不能 `nodes['Principled BSDF']` 按名取。
- **Track To 约束在 -b 后台模式不生效**——相机/太阳指向必须用旋转矩阵直接构造（camera 局部 -Z 朝目标；sun lamp +Z 朝太阳方向）。
- **物体的 `scale` 属性与 emission 材质存在兼容性问题**（scale≠1 时渲染不可见）——几何体用 `size=` 参数直接建成目标尺寸，或 scale 后 `bpy.ops.object.transform_apply(scale=True)`。
- **Denoising 会把 30px 的小目标抹掉**——太空小目标场景必须 `use_denoising = False`、`use_adaptive_sampling = False`。
- **`Render Result` 像素在第二次 `bpy.ops.render.render()`（无 write_still）后读取为空**——标注 mask 必须用 `write_still=True` 写临时 EXR 再 `bpy.data.images.load` 读回（EXR 保留 scene-linear 浮点）。
- `bpy.data.images.new()` 创建的图像 pixels 为空，foreach_set 报 "expected sequence size 4, got 0"——mask PNG 用标准库 zlib/struct 手写编码，绕开 Blender image API。
- **Operator 需要对象被选中才能生效**：`bpy.ops.object.parent_clear()` 和 `bpy.ops.object.transform_apply()` 操作的是**选中的对象**，仅设 `active` 不够，必须 `obj.select_set(True)`。

### 场景尺度
- Blender 场景统一用 **km**（m×0.001），相机 clip_start=0.01 km (10m), clip_end=200000 km。
- ECI(J2000) 与 Blender 世界坐标均为右手系 Z-up，**1:1 直接映射**，无需变换。四元数 STK(qx,qy,qz,qw) → Blender 构造 `Quaternion((qw,qx,qy,qz))`。

### 材质设置经验
- **太空小目标不可用纯 emission**（100% mix Fac）：所有面都是纯色自发光，立方体和平面看起来一样，完全没有 3D 深度感。
- **推荐配比**：85% emission（Strength 3.0）+ 15% BSDF（Roughness 0.4, Metallic 0.3）。BSDF 提供方向性光影，自发光保证太空可见性。
- Sun lamp energy = 60（BSDF 辅助照明，不宜过高否则过曝）。

### Beauty/Mask 双渲染模式
- **DSP.blend 模型**：完整模型（`1323_00`，剩余面）+ 标注组件（用户手动分离的面）。两者互补，一起构成完整卫星。
- **Beauty 渲染**：完整模型 + 标注组件都可见（`hide_render = False`）
- **Mask 渲染**：完整模型隐藏，标注组件显示纯色（pass_index 编码在红通道）
- 只需在标注组件上分离面→命名→保存 .blend，脚本自动处理 rest

## 工作规范（用户明确要求）

1. **渲染输出按批次分类建文件夹**：每批渲染输出到 `output/images/<批次tag>/`（render_scene.py 已支持 `--tag`，默认自动生成 `start_end_s{samples}_r{res}`）。annotations 下 instance_masks/yolo/pose 同样按批次分子目录。禁止不同批次混在一个目录。
2. **小批量验证后必须用户确认再跑大批量**：>100 帧的渲染批次启动前，先跑 ≤50 帧小批量并请用户确认效果，得到同意后才继续。

## 常用命令

### segB 核心段（DSP 模型，track，窄视场）
```powershell
& "E:\Blender\blender.exe" -b -P "F:\钱室\卫星图像仿真\blender\render_scene.py" -- `
  --ephem_dir "F:\钱室\卫星图像仿真\output\ephemeris" `
  --start 23165 --end 23609 --stride 1 `
  --samples 64 --resolution 2048 --fov 0.08 `
  --camera_mode track --model_type dsp_blend `
  --tag "segB_DSP_full_23165_23608_s64_r2048"
```

### segA/segC 远距段（DSP 模型 ×10，stare，宽视场）
```powershell
& "E:\Blender\blender.exe" -b -P "F:\钱室\卫星图像仿真\blender\render_scene.py" -- `
  --ephem_dir "F:\钱室\卫星图像仿真\output\ephemeris" `
  --start 22482 --end 23166 --stride 25 `
  --samples 32 --resolution 2048 --fov 14 `
  --camera_mode stare --model_scale 10.0 `
  --model_type dsp_blend --no_annotations `
  --tag "segA_DSP_stare_22482_23165_s32_r2048_x10"
```

### 手搭简易模型
```powershell
& "E:\Blender\blender.exe" -b -P "F:\钱室\卫星图像仿真\blender\render_scene.py" -- `
  --ephem_dir "F:\钱室\卫星图像仿真\output\ephemeris" `
  --start 23165 --end 23609 --stride 1 `
  --samples 64 --resolution 2048 --fov 0.08 `
  --camera_mode track --model_type simple `
  --tag "segB_Simple_23165_23608_s64_r2048"
```

### MATLAB 主入口
```matlab
% MATLAB 主入口（STK 会被脚本自动启动）
cd 'F:\钱室\卫星图像仿真\matlab'
main
```
