# PRECHECK 03 圆形机械孔转换独立复核

归档说明：这是单独孔转换阶段的历史探针报告，原始输入已按字节归档。JSON见[hole_conversion_probe.json](hole_conversion_probe.json)。正式完整候选另见[PRECHECK_03制造检查](../../../release_v03_precheck03_fabrication.json)；文末检查器哈希代表当时版本，不代表现有文件哈希。

结果：**PASS**，15 项。只读复核原生候选和 Gerber 探针；未修改冻结发布目录。

四个同径 NPTH 焊盘替换为多层精确圆形挖槽。孔中心为 (5,5)、(61,5)、(5,51)、(61,51) mm，导出孔径均为 2.7 mm。
独立孔数仍为 42：38 个镀铜孔、4 个非镀铜安装孔。导出前后的中心、孔径、镀铜属性逐孔完全一致。
原生 23 个器件、63 个物理焊盘、网络/焊盘关联及安装孔以外的全部 492 条记录不变。
顶、底铜层各删除四个与 NPTH 同径的铜 flash。分别以 0.0005 mm 和 0.000125 mm 的曲线逼近精度进行布尔运算：扣除全部钻孔后，两版实际铜图形完全相等，对称差面积均为 0 mm²；差异全部在四个 NPTH 内，无新增铜。
此结论不把原始 Gerber 铜层宣称为相同；变更的目的正是去除孔内原有 copper flash。

| 检查 | 结果 |
|---|---|
| native_board_geometry | PASS |
| native_hole_geometry_plating | PASS |
| native_components_and_pad_nets | PASS |
| native_physical_pads | PASS |
| native_all_other_records | PASS |
| four_pad_to_circle_conversion | PASS |
| gerber_parser | PASS |
| exported_42_holes_unchanged | PASS |
| native_to_export_registration | PASS |
| exported_outline_unchanged | PASS |
| top_copper_after_drilling_0.0005 | PASS |
| bottom_copper_after_drilling_0.0005 | PASS |
| top_copper_after_drilling_0.000125 | PASS |
| bottom_copper_after_drilling_0.000125 | PASS |
| probe_electrical_geometry_checks | PASS |

官方依据：[嘉立创EDA专业版：放置挖槽区域](https://prodocs.lceda.cn/cn/pcb/place-slot-region/index.html)。文档说明 v1.9 起直径 ≤6.5 mm 的圆形挖槽进入 NPTH 钻孔文件。检查器仅新增这一精确圆形情况，未将非圆、多轮廓、无效数字或大孔按圆钻孔放行。

原生 path 单位为 mil，radius=53.1496，换算直径为 2.69999968 mm；Excellon 为 2.7 mm。width 是区域描边元数据，未加到孔径。

此报告仅绑定下列候选文件；正式导出仍须重跑完整发布验收并绑定新的完整工程 SHA-256。没有改写原冻结 V0.3 电气差异报告。

- [before_cutout.epcb](hole_conversion_probe_inputs/before_cutout.epcb)：`de0ef8f856bd6c5eaccb1fd8561e39b82bf6af3581dac94d972dadad82e2a78e`
- [after_cutout.epcb](hole_conversion_probe_inputs/after_cutout.epcb)：`f566c9c4b3accf840f25207ca9e930c29dd4d70cafe357832f90cf08e0bcdbc1`
- `pcb/preflight_v03/Mianguang_V0.3_DFM_PRECHECK_02.zip`：`b245381b710547aec874be0bb3018a74e3dfb0aaf2f7b20015833cee4b0f3a61`
- [holes_only_gerber.zip](hole_conversion_probe_inputs/holes_only_gerber.zip)：`564446269e21dd818b87e0eeeeabee02ec293297a11442d2e4c7c62e7f5cbf65`
- `pcb/release_v03/Mianguang_V0.3.epro2`：`e99b49c640c06d2a1bd36213682fdc1fc56e33b7090c582f66813078a78bd13e`
- `pcb/qa/check_release.py`：`d9d2fd195fda814dc66cf68e8af6cb49039eb23119ad0beae95d6437f5f72f91`
- `pcb/qa/gerber_checks.py`：`a4e813765c2f1fda8c44c01b058053fbcd3f2c25b78f55d263fb2ddd42ab0ca6`
