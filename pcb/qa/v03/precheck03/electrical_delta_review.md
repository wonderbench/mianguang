# V0.3 PRECHECK 03 电气与机械差异复核

日期：2026-11-05。结果：**PASS**，48 项检查。对比基线为冻结 V0.2 与 V0.3 PRECHECK 02。只读检查，未修改候选或历史发布文件。

| 比较项目 | V0.2 → 03 | 02 → 03 |
|---|---|---|
| 23 个器件位置、角度、面别 | 相同 | 相同 |
| 63 个物理焊盘几何与网络 | 相同 | 相同 |
| 全部原理图、PCB 引脚网络 | 相同 | 相同 |
| 42 个孔：38 PTH + 4 NPTH | 孔位、孔径、镀铜属性相同 | 孔位、孔径、镀铜属性相同 |
| 66 × 56 mm 板框、布线和层叠 | 相同 | 相同 |
| 扣孔后实际顶/底铜层 | 两档精度对称差均 0 mm² | 两档精度对称差均 0 mm² |

上述表格仅在本报告总结果 PASS 时成立；逐项证据与失败项见配套 JSON。

四个安装孔由同径 NPTH PAD 改为多层精确圆形 FILL 挖槽。孔中心仍为 (5,5)、(61,5)、(5,51)、(61,51) mm，导出孔径均 2.7 mm。
原始顶、底铜层各删除四个孔内铜 flash，所以原始铜图形不再相同。用 0.0005 mm 与 0.000125 mm 两档曲线逼近进行独立布尔比较：无新增铜，所有去除图形恰好为四个 NPTH 圆；扣孔后实际铜图形与两个基线均完全相等。
23 个器件、63 个物理焊盘、所有引脚网络及接口位置保持不变，已有 V0.2 外壳安装柱与接口位置继续兼容。这一结论针对导出几何，不替代装配公差和实物插拔验证。

允许的变化已逐项检查：PCB/封装顶丝印的位置、字号、线宽、形状；四个机械孔表示法；已知库默认值和 UI/序号元数据。C1/C4 相对 V0.2 补全的采购资料与 C15850 编号不改 CL21A106KAYNNNE 型号、0805 焊盘或网络；相对 02 的所有已解析器件属性完全一致。
已知锡膏全开窗通过新的 Gerber 导出选项实现；本报告不声称锡膏或阻焊与历史文件相同，其覆盖范围和可制造性由制造检查报告验证。
D1 与六个双针连接器相对 V0.2 的远程 3D 库 UUID 变化已保留在 JSON；采购料号、模型标题和放置变换相同。完整工程不含远程模型二进制，因此不声称远程资源逐字节相同。

完整检查证据、封装差异与各输入 SHA-256：[electrical_delta_review.json](electrical_delta_review.json)。
SMT 极性核对：[smt_polarity_reference.md](smt_polarity_reference.md)。D2 实物色带标识待确认项保持开放。

## PRECHECK 03 输入身份

| 文件 | SHA-256 |
|---|---|
| [Mianguang_V0.3.epro2](../../../release_v03_precheck03/Mianguang_V0.3.epro2) | `01f43cf3fcebcb7f2e6dfb590aaf878a952d3f6b54837cca8e0f2a40bde66e1f` |
| [schematic_netlist.json](../../../release_v03_precheck03/schematic_netlist.json) | `a3bf7b12c05700409c9660422ad78a04a8fccd2f3696976095c76cc3358a5657` |
| [Mianguang_V0.3.epcb](../../../release_v03_precheck03/Mianguang_V0.3.epcb) | `1b005cf1bb2e7d59b4584eca6a2bd83e2b9e46b83c3a32bf83ad4a90f7a16536` |
| [pcb_netlist.json](../../../release_v03_precheck03/pcb_netlist.json) | `cb5814a05b2b1d082879ae17e289cbdd2538863a0fce2de213dbf72ffdeaa994` |
| [PickPlace_Mianguang_V0.3.csv](../../../release_v03_precheck03/PickPlace_Mianguang_V0.3.csv) | `c53d8d2d6d1a3afaca18bf15c87e625e6a3604dd6baf38c3b4521e5a87b64704` |
| [Gerber_Mianguang_V0.3.zip](../../../release_v03_precheck03/Gerber_Mianguang_V0.3.zip) | `8e786b7bfa3eb609b283f079b3bb2ccddcab58149d3979a5f0926bc297206811` |
| [Mianguang_V0.3.esch](../../../release_v03_precheck03/Mianguang_V0.3.esch) | `b494a8e15ba99069df280d1bf1b303a56567f9630c81d65edbb9577ea9c99854` |
| [native_checks.json](../../../release_v03_precheck03/native_checks.json) | `d019784048903375f49939a4a7d1bb6c6f5b3694c9f70d5bb6e448294f4fa198` |
