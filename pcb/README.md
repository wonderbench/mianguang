# PCB设计 · V0.3 PRECHECK 03

最新载板为66 × 56 mm双层PCB，23个元件、18个电气网络，连接C1001雷达、XIAO ESP32C3和外接夜灯。已根据用户提供的PRECHECK02在线DFM报告修正机械孔表达、丝印距阻焊开窗/钻孔的间距和丝印笔画。

**03版在线PCB复检及SMT检查待完成，未制造放行。** 请手动上传[03版Gerber ZIP](preflight_v03/Mianguang_V0.3_DFM_PRECHECK_03.zip)，并使用同版[SMT BOM与坐标](preflight_v03/smt_precheck03/)。01/02上传包均为历史版本。

| 入口 | 内容 |
|---|---|
| [release_v03_precheck03/](release_v03_precheck03/) | 最新固定候选：完整工程、原理图/PCB源、完整BOM、Gerber、原生坐标、预览和manifest |
| [03完整交付包](releases/Mianguang_PCB_V0.3_PRECHECK03_2026-11-05.zip) | 最新工程、SMT文件、检查证据及可复核的历史源；SHA-256见同名`.zip.sha256` |
| [修订与装配说明](release_v03_precheck03/README_交付与装配.md) | 在线报告逐项处理、装配条件、工艺及接线 |
| [独立验收](release_v03_precheck03_acceptance.json) | 49/49 PASS：原生零提示、网表、BOM、铜连接、钻孔、锡膏 |
| [制造几何检查](release_v03_precheck03_fabrication.json) | 40/40 PASS：新增实际阻焊窗/钻孔避让≥0.25 mm、描线≥0.20 mm门槛，绑定冻结输入 |
| [03版独立复核](qa/v03/precheck03/) | 48项电气/机械差异、22项导出复核、极性表、孔转换及钻孔去重证据 |
| [02版在线报告与分析](qa/v03/online_dfm/) | 用户上传的原PDF、问题汇总及几何复现；不冒充03版结果 |
| [qa/](qa/) / [scripts/](scripts/) | 离线检查器、37项检查器回归、6项导出比对回归及受保护的导出流程 |
| [release_v03/](release_v03/) / [release_v02/](release_v02/) | PRECHECK02与V0.2历史冻结源，保持原字节和历史报告 |
| [LATEST.json](LATEST.json) | 最新候选、归档位置、哈希与状态 |

导入[Mianguang_V0.3.epro2](release_v03_precheck03/Mianguang_V0.3.epro2)查看和继续设计。当前原理图、PCB严格DRC均返回`true` / `[]`，检查记录绑定完整工程和源快照。后续修改应建立新候选，不能单独替换冻结目录内的文件。

四个Ø2.7 mm机械孔由非镀铜PAD改为圆形挖槽，消除孔内虚拟铜盘。原始铜层因此变化，但扣除钻孔后的实际顶/底铜图形与V0.2、PRECHECK02均相同；42个独立孔、63个物理焊盘、23个器件位置及全部引脚网络不变。[V0.2外壳](../models/v0.2/)的孔位和接口几何依据仍适用，固件维持V0.2.0。

8条插件到SMT焊盘间距提示是真实工艺条件：14件SMT先回流，9件通孔/模块后手工装配。本版未按波峰焊设计，尚需贴片方确认手工焊接空间、工艺边/定位点和极性预览。D2实物色带标识仍需供方包装图确认。数字检查不代替首件电气、热、射频和实物装配测试。
