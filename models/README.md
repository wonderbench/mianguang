# 眠光 V0.2 外壳与安装支架

最新入口是 [Mianguang_Enclosure_V0.2.blend](v0.2/Mianguang_Enclosure_V0.2.blend)。本版按冻结 PCB V0.2 调整四孔、23 个元件位置、XIAO 插座和 USB 检修空间，保持白色简约机身、独立暖白夜灯与顶部按键。共用后座兼容桌面 0–30°、壁挂 0–45° 的俯角范围；桌面基座为 100×120×5 mm。

这是供打印配合验证的工程样机结构。采购件尺寸、线束、打印公差和实物测试尚未冻结；数字检查不等于装配、透波、温升、抗倾覆或墙面承载通过。

## 最新文件

| 文件 | 用途 |
|---|---|
| [Blender 工程](v0.2/Mianguang_Enclosure_V0.2.blend) | 可编辑模型及桌面、后侧、壁挂、展开四个场景 |
| [完整模型包](releases/Mianguang_Enclosure_V0.2_2026-11-04.zip)、[版本索引](LATEST.json) | 模型、STL、效果图、依据、脚本和装配文档；附 SHA-256 清单 |
| [11 个 STL](v0.2/stl/) | 毫米制打印零件；两种支架均包含，使用时择一安装 |
| [桌面效果](v0.2/renders/01_hero.png)、[后侧](v0.2/renders/02_rear.png)、[壁挂](v0.2/renders/03_wall_45deg.png)、[展开](v0.2/renders/04_exploded.png) | 四张观察图；不代表实测光效或量产效果 |
| [装配与结构 BOM](mechanical/assembly_v02.md) | 装配次序、紧固件、采购尺寸约束和检修步骤 |
| [PCB 机械基准](mechanical/pcb_v02_reference.json)、[接口证据](mechanical/interface_evidence.md) | 四孔、针位、平面包络、来源 SHA-256，以及已确认尺寸与设计假设 |
| [几何检查](v0.2/geometry_checks.json)、[网格检查](v0.2/mesh_checks.json) | 按报告逐项查看核对范围、结果及未覆盖事项 |
| [机械尺寸示意图](v0.2/Mechanical_Layout_V0.2.svg) | PCB 孔位、叠层和两种支架的主要空间关系 |
| [设计参数](v0.2/fit_parameters.json) | 构建参数与 PCB 清单指纹；其中的 `design_conditions` 不能代替独立几何复核 |
| [构建脚本](scripts/build_enclosure_v02.py)、[支架脚本](scripts/mount_v02.py)、[支架说明](mechanical/mount_notes.md) | 可追溯模型来源 |

Blender 使用米作为内部单位、界面显示毫米；STL 顶点为毫米，每件最低点平移至 Z=0，仍需自行选择打印朝向与支撑。PCB 到外壳的映射为 `X=x−33`、`Z=y+56`，板中心 Y=12.2 mm，元件面朝 −Y。

本次独立复核为 **15 项通过、0 项失败**；11 件均闭合且单一连通。桌面 63 个、壁挂 93 个离散姿态检查通过；桌面最小避让约 3.97 mm，壁挂机身及外接 USB 插头预算至墙面最小约 11.15 mm。方法、模型指纹和条件限制见[复核记录](mechanical/review_v02.md)。

## 重建与查看

在独立仓库副本中，从仓库根目录运行以下命令；将 `blender` 换成本机可执行文件。构建会更新 `v0.2/` 的工程、STL 和构建记录，渲染会更新四张图片；重建后需重新生成独立几何检查报告，不能沿用旧报告。

模型包解压后可直接打开 Blender 和 STL；从源码重建还需要本仓库的冻结 `pcb/release_v02/`，应在完整仓库副本中运行。

```sh
blender --background --factory-startup --python models/scripts/build_enclosure_v02.py
blender --background models/v0.2/Mianguang_Enclosure_V0.2.blend --python models/scripts/verify_enclosure_v02.py
blender --background models/v0.2/Mianguang_Enclosure_V0.2.blend --python models/scripts/render_enclosure_v02.py
```

安装后仍须对准胸部并验证距离和角度；支架机械可调范围不等于所有姿态均适用于睡眠检测。前板 1.6 mm 白色无金属聚合物、雷达间隙和夜灯扩散效果均为样件起点。

`Sleep_Radar_Nightlight_Concept.blend`、根目录旧 `stl/`、旧 `renders/` 及旧检查记录作为历史概念版保留；新打样与装配请使用上述 `v0.2/` 文件，避免混用旧版孔径和支架尺寸。
