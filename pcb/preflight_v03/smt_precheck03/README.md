# V0.3 PRECHECK03贴片检查文件

本目录只对应冻结的`pcb/release_v03_precheck03`，与上级`Mianguang_V0.3_DFM_PRECHECK_03.zip`一起使用。**平台SMT检查尚未执行，本地文件匹配通过不等于贴装放行。**

- `BOM_SMT_Mianguang_V0.3.csv`：9组物料、14件顶层SMT，含嘉立创元件编号。
- `CPL_SMT_Mianguang_V0.3.csv`：同14个位号的原生中心坐标、角度和顶层标记T，单位mm。
- `manual_assembly.csv`：J1–J5、JP1–JP3、U1共9件后续手工项；排母等附加件另见完整交付中的《外接件与装配BOM》。
- `validation.json`：源清单及文件哈希、输出哈希、逐位号和坐标检查记录；14件SMT + 9件手工项 = 23件，29个SMT焊盘。

上传后执行BOM匹配与SMT检查，核对采购编号、封装、库存和贴装预览，特别是D1、D2、Q1的实际引脚方向，见[极性核对表](../../qa/v03/precheck03/smt_polarity_reference.md)。平台零度定义可能不同，不能仅照抄角度数字判断方向；D2实物阴极色带需供方包装图确认。8条插件到SMT间距提示按后续手工焊接条件提交贴片方确认；工艺边/定位点也需由贴片方确定。

重建：`python3 pcb/scripts/prepare_smt_preflight_v03.py --release pcb/release_v03_precheck03 --output pcb/preflight_v03/smt_precheck03`。脚本验证冻结清单，拒绝用另一来源覆盖已有贴片包。

格式依据：[嘉立创DFM BOM与坐标规范](https://www.jlc.com/portal/server_guide_48022.html)、[JLCPCB坐标文件要求](https://jlcpcb.com/help/article/pick-place-file-for-pcb-assembly)（2026-11-05查阅）。坐标保留原生Mid X/Mid Y，不替换为Ref X/Ref Y；若平台字段名不同，将“嘉立创元件编号”映射到LCSC Part #。
