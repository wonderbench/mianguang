# V0.3 PRECHECK02 贴片检查文件

本目录对应冻结的 **DFM_PRECHECK_02 / pcb/release_v03**。后续 PCB 修订应另建贴片检查目录，勿与本目录混用。

向嘉立创 DFM / 贴片平台提交同版 PCB 资料，并上传以下两份文件：

- `BOM_SMT_Mianguang_V0.3.csv`：9 组物料、14 件顶层 SMT，含原生采购编号。
- `CPL_SMT_Mianguang_V0.3.csv`：对应 14 个位号的中心坐标、顶层标记 T 和原生角度，坐标单位 mm。

`manual_assembly.csv` 单列 J1–J5、JP1–JP3、U1 共 9 件手工装配项，不加入上述贴片 BOM/CPL。U1 为 XIAO 模组配两条 1×7 排母，附加装配件仍以冻结发布中的《外接件与装配BOM》为准。

这些文件从 `pcb/release_v03` 的冻结原生导出派生。`validation.json` 记录源文件与输出 SHA-256、逐位号坐标一致性、数量及项目内实际焊盘分类，核对结果为 14 件 SMT + 9 件手工项 = 23 件，SMT 焊盘 29 个。运行 `python3 pcb/scripts/prepare_smt_preflight_v03.py` 可重建 CSV 和报告，冻结发布文件不会被改写。

后续候选可指定 `--release 新冻结发布目录 --output 新贴片目录`。脚本校验来源清单并拒绝用不同来源覆盖已有贴片包。

上传后仍需执行平台 BOM 匹配和 SMT 检查，核对采购编号、封装、库存、贴装预览，以及 D1、D2、Q1 的方向。当前仅完成本地文件核对，平台 SMT 检查尚未执行；未预设或擅自调整平台角度。若平台显示不同编号字段名，将“嘉立创元件编号”对应到 LCSC Part #。

格式依据：[嘉立创 DFM BOM 与坐标格式规范](https://www.jlc.com/portal/server_guide_48022.html)、[JLCPCB 坐标文件要求](https://jlcpcb.com/help/article/pick-place-file-for-pcb-assembly)、[JLCPCB BOM 要求](https://jlcpcb.com/help/article/bill-of-materials-for-pcb-assembly)（2026-11-05 查阅）。使用 CSV 单行表头，完整列出位号，BOM 数量与位号数一致；CPL 保留原生 Mid X / Mid Y，不替换为 Ref X / Ref Y。
