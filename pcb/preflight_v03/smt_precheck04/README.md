# V0.3 PRECHECK04贴片检查文件

本目录仅对应`pcb/release_v03_precheck04`及上级`Mianguang_V0.3_DFM_PRECHECK_04.zip`。04只移动D1丝印阴极标记，14件SMT的料号、坐标和原生旋转角不变；文件仍从04冻结源重新派生并绑定哈希。

- `BOM_SMT_Mianguang_V0.3.csv`：9组、14件顶层SMT。
- `CPL_SMT_Mianguang_V0.3.csv`：同14个位号，原生Mid X/Mid Y，单位mm，顶层T。
- `manual_assembly.csv`：J1–J5、JP1–JP3、U1共9件手工项，不混入贴片文件。
- `validation.json`：来源清单、输出哈希、位号、数量、坐标和29个SMT焊盘检查。

03第二份报告已包含SMT分析，报D1本体中央丝印警告1项；04已在源中修正，**04在线PCB/SMT复检尚未执行**。使用同版04三文件复测，不将03报告作为04通过记录。

在平台核对全部14个位号、物料匹配、封装及实际引脚方向，见[04极性表](../../qa/v03/precheck04/smt_polarity_reference.md)。D1阴极在左侧，新竖线位于本体外；D2阴极设计向下、实物色带仍需供方包装图确认；Q1单脚D在左。原生角度不等于贴片库零度。

还应确认NPTH识别、后续手工焊接、工艺边/定位点及目标无铅喷锡。03的PCB 16条警告不因本地检查通过自动关闭。

重建命令：`python3 pcb/scripts/prepare_smt_preflight_v03.py --release pcb/release_v03_precheck04 --output pcb/preflight_v03/smt_precheck04`。
