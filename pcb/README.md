# PCB设计 · V0.3 PRECHECK04

最新载板为66 × 56 mm双层PCB，23个元件、18个电气网络，连接C1001雷达、XIAO ESP32C3和外接夜灯。04只修正D1本体中央的丝印：将阴极竖线移到本体外左侧，保留D1位号及上下轮廓。

**04在线复检已完成：PCB 0危险/16警告，SMT 0危险/0警告；尚未制造放行。** 最新[04报告复核](qa/v03/online_dfm/PRECHECK_04_review.md)确认D1本体丝印警告关闭；插件到贴片间距8条、NPTH文件上的Pth无Pad 8条仍待工艺/识别确认。

| 入口 | 内容 |
|---|---|
| [04完整工程](release_v03_precheck04/Mianguang_V0.3.epro2) / [交付目录](release_v03_precheck04/) | 同版SCH/PCB源、23件完整BOM、Gerber、原生坐标、预览、冻结清单及装配说明 |
| [04在线上传包](preflight_v03/Mianguang_V0.3_DFM_PRECHECK_04.zip) / [04 SMT文件](preflight_v03/smt_precheck04/) | 用于人工上传PCB和SMT分析，不与03候选混用 |
| [04独立验收](release_v03_precheck04_acceptance.json) | 49/49 PASS：严格原生检查、网表/BOM、铜连接、钻孔、锡膏 |
| [04制造检查](release_v03_precheck04_fabrication.json) | 40/40 PASS：online-preflight配置，含实际阻焊窗/钻孔避让和笔画门槛 |
| [04独立复核](qa/v03/precheck04/) | 03→04差异、D1标记位置、导出一致性、极性与保存重开证据 |
| [安装孔与装配间隙处置](qa/v03/mounting_and_clearance_review.md) | 16条警告的处置判断、下单确认文字、M3螺钉头与焊脚等外壳补充要求 |
| [在线报告归档](qa/v03/online_dfm/) | 02、03两份及04原PDF与各自复核；04的SMT已零危险零警告 |
| [04完整交付ZIP](releases/Mianguang_PCB_V0.3_PRECHECK04_2026-11-05.zip) | 统一工程与检查证据；SHA-256见同名`.zip.sha256` |
| [LATEST.json](LATEST.json) | 当前候选、最新04报告及上一份03报告，含哈希和未完成项 |
| [检查程序](qa/) / [导出程序](scripts/) | 冻结保护、检查器及回归；本次未改程序 |

03→04仅有D1顶丝印的设计变化，其他制造文件可能因导出时间戳改变字节；差异复核区分实际制造指令和元数据。孔位、63个物理焊盘、23个器件放置、全部引脚网络维持，既有[V0.2外壳](../models/v0.2/)仍按原孔位与接口几何适用。

剩余处置：四个安装孔保持Ø2.7 mm NPTH，文件明确NON_PLATED，需DFM/CAM确认分类；14件SMT先回流、9件通孔/模块后手工焊接，8条间距提示需装配方确认。04报告仍为有铅喷锡，与目标无铅喷锡不一致。还需核对14个位号、选料、封装与极性、D2实物色带、工艺边/定位点。数字检查不代替首件电气、热、射频和实物装配测试。

04完整ZIP形成于收到04在线报告之前，保持原字节；新报告及复核另存于仓库[在线报告目录](qa/v03/online_dfm/)，不在该ZIP中。

历史冻结源[PRECHECK03](release_v03_precheck03/)、[PRECHECK02](release_v03/)和[V0.2](release_v02/)保持原字节；04冻结源也保持原字节；其中“等待报告”等文字是导出时状态，最新进展以当前索引为准。
