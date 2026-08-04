# STK 11.6 基础操作教程

> 适用版本：STK 11.6 | 编写日期：2026-07-17

---

## 1. STK 是什么？

STK（Systems Tool Kit）是由 AGI 公司（现为 Ansys 旗下）开发的**航天任务分析与可视化软件**。它用于：
- 卫星轨道设计与传播
- 传感器/载荷覆盖分析
- 访问时间计算（什么时候能看到目标？）
- 链路预算、通信分析
- 3D/2D 可视化

**STK 不是渲染引擎**——它的 3D 视图是工程可视化级别的，不是照片级渲染。

---

## 2. STK 界面概览

启动 STK 后你会看到三个主要区域：

```
┌──────────────────────────────────────┐
│  菜单栏 (File / Insert / Analysis)    │
├────────────┬────────────────────────-┤
│ 对象浏览器  │    3D 图形窗口           │
│ (Object    │   (3D Graphics)         │
│  Browser)  │                         │
│            │   地球 + 卫星轨道         │
│  📁 场景   │                         │
│   🛰 卫星A  │                         │
│   📷 传感器 │                         │
│   🛰 卫星B  │                         │
│            │                         │
├────────────┴────────────────────────-┤
│  时间控制条 (Animation Timeline)      │
│  [◀◀] [▶] [⏸] [▶▶]                  │
└──────────────────────────────────────┘
```

**关键面板：**
- **Object Browser（左侧）**：树状结构，显示场景中所有对象
- **3D Graphics（中间）**：三维可视化窗口
- **2D Graphics（可选）**：二维地面投影
- **Timeline（底部）**：控制仿真时间推进

---

## 3. 创建第一个场景

### 3.1 新建场景

1. 点击菜单 `File → New...` 或按 `Ctrl+N`
2. 在弹出的对话框中输入场景名称，例如 `MyFirstScenario`
3. 点击 `OK`

### 3.2 设置场景时间

1. 在 Object Browser 中双击场景名称（根节点）
2. 在 Properties 窗口中找到 **Basic → Time Period**
3. 设置：
   - **Start Time**: `1 Jul 2026 12:00:00.000 UTCG`
   - **Stop Time**: `1 Jul 2026 13:00:00.000 UTCG`
   - **Epoch**: 与 Start Time 相同
4. 点击 `Apply` → `OK`

---

## 4. 创建卫星（从轨道六根数）

轨道六根数（Keplerian / Classical Elements）是描述卫星轨道最常用的方式：

| 参数 | 符号 | 单位 | 说明 |
|------|------|------|------|
| 半长轴 | a (Semi-major Axis) | km 或 m | 轨道大小 |
| 偏心率 | e (Eccentricity) | 无 | 0=圆轨道, 0~1=椭圆 |
| 轨道倾角 | i (Inclination) | deg | 轨道面与赤道面的夹角 |
| 升交点赤经 | Ω (RAAN) | deg | 从春分点到升交点的角度 |
| 近地点幅角 | ω (Arg. of Perigee) | deg | 从升交点到近地点的角度 |
| 平近点角 | M (Mean Anomaly) | deg | 卫星在轨道上的位置 |

**操作步骤：**

1. 菜单 `Insert → Satellite → From Standard Object Database...`（或用 Orbit Wizard）
   - 或手动：`Insert → Satellite → Orbit Wizard...`

2. 在 Orbit Wizard 中：
   - Type: **Orbit Designer**
   - 选择 **Classical Elements**
   - 填入六根数数值

3. 或者用菜单 `Insert → Satellite → Default`
   - 然后双击卫星 → **Basic → Orbit**
   - Propagator: 选择 `J4Perturbation`（含 J2/J4 摄动）
   - Coordinate System: `J2000`
   - 在 **Orbit → Classical** 中填入六根数

4. 点击 `Apply` → `OK`

---

## 5. 创建传感器（Sensor）

传感器模拟成像载荷的视场范围。

**操作步骤：**

1. `Insert → new → Sensor → Insert Default`
2. 双击新建的 Sensor
3. 在 Properties 中设置：
   - **Basic → Definition → Sensor Type**: `EOIR`
   - **Field of View**: 输入半角（单位 deg）
     - 例如：0.06°（对应约 0.12° FOV 的窄视场传感器）
4. 点击 `Apply` → `OK`

---

## 6. 设置传感器/卫星指向目标

让观察卫星的传感器始终指向目标卫星：

**方法 1：设置卫星姿态（推荐，用于"第一视角"）**

1. 双击观察卫星（ObserverSat）
2. **Basic → Attitude**
3. `Target Pointing -> Select Targets`
4. Target: 选择目标卫星（TargetSat）
5. 点击 `Apply`

这样卫星本体和它的传感器都会指向目标。传感器会随着卫星姿态自动对准。

**方法 2：仅设置传感器指向**

1. 双击 Sensor
2. **Basic → Definition → Pointing**
3. Pointing Type: `Target`
4. Target: 选择目标卫星

---

## 7. 查看传感器视角（第一视角）

这是验证"相机看到什么"的关键功能：

1. 在3D窗口上的一排按钮处点击: View From/To
2. From Posiotion选择 `Sensor1`，To Positon选择另一颗卫星
3. 就会在3D窗口显示从该传感器视角看到的内容

在这个窗口中：
- 可以看到目标是否在 FOV 锥体范围内
- 可以看到背景（地球/深空）
- 可以使用时间控制条推进仿真

---

## 8. 导出数据

### 8.1 通过 Report 导出

1. 右键点击对象（卫星/Sensor） → `Report & Graph Manager...`
2. 选择需要的报告类型：
   - **Cartesian Position**: ECI 位置 (x, y, z)
   - **Cartesian Velocity**: ECI 速度 (vx, vy, vz)
   - **Classical Elements**: 轨道六根数
   - **Quaternions**: 姿态四元数
   - **Access**: 传感器到目标的可见性
3. 点击 `Generate...` → 可以保存为 CSV 文件

### 8.2 通过 MATLAB 脚本导出（自动化）

这是本项目使用的方式，参见 `matlab/+stk_helpers/exportAllEphemeris.m`。

MATLAB 中通过 `stkReport` 函数导出数据：
```matlab
[data, names] = stkReport('*/Satellite/ObsSat', ...
    'Cartesian Position', startTime, stopTime, stepSize);
```

---

## 9. 截图传感器视角

### 9.1 手动截图

1. 在 Sensor View 窗口中右键
2. 选择 `Copy to Clipboard` 或 `Save Snapshot...`

### 9.2 通过 MATLAB 脚本截图（自动化）

本项目中也提供自动截图方案。STK 的 COM 接口支持：
```matlab
% 通过 Connect 命令设置截图
stkConnect(conid, 'VO_3DView Snapshot', 'screenshot.png');
```

---

## 10. 常见问题

| 问题 | 解决方案 |
|------|---------|
| 卫星不显示在 3D 窗口中 | 检查时间是否在轨道历元范围内；右键卫星 → `Zoom To` |
| 传感器看不到目标 | 检查传感器 FOV 是否足够大（窄 FOV 需非常精确的指向） |
| 轨道看起来不对 | 检查六根数的单位和坐标系（STK 默认单位为 km，不是 m！） |
| STK 界面卡住 | 按 `Esc` 键取消当前操作；在动画控制中将时间步长减小 |
| 3D 窗口是黑的 | 检查显卡驱动；尝试 `View → Reset View` |

---

## 11. 下一步

完成手动操作后，运行 MATLAB 测试脚本验证自动化连接：

```matlab
cd '~/project/matlab'
test_stk_connection
```

然后进入阶段 2：自动化场景构建。
