# PRECHECK 03 → 04 电气与制造差异复核

日期：2026-11-05。几何/电气差异复核：**PASS**，37 项检查。只读比较03与04，不重写历史报告或发布文件。

**原始文件字节并非除顶丝印外全相同。** 新导出的时间戳、未被使用的孔径定义及D码编号发生变化；BOM XLSX仅元数据日期变化，SCH/PCB源仅DOCHEAD存储身份变化。不能把这些文件写成逐字节一致。比较解析后的全部有效制造图元及原生记录，确认实际改动仅为D1阴极丝印。

| 对象 | 03 → 04 结果 |
|---|---|
| 23 个器件位置、角度、面别和实例属性 | 全部相同 |
| 63 个物理焊盘及全部网络 | 全部相同 |
| 42 孔（38 PTH、4 NPTH） | 坐标、直径、属性相同；钻孔指令字节仅时间注释不同 |
| 两份网表、BOM CSV、CPL | 原始字节完全相同 |
| BOM XLSX | 所有工作表与非日期内容相同，仅core.xml创建/修改时间不同 |
| 独立SCH/PCB源 | 全部原生记录相同，仅DOCHEAD元数据变化 |
| 顶/底铜、阻焊、锡膏、板框、底丝印、文档/钻孔图层 | 毫米单位、含极性的有效图元序列逐项相同 |
| 顶丝印 | 仅删除D1原中央5笔，新增外置阴极线1笔 |

顶/底原始铜在0.0005 mm和0.000125 mm两档曲线精度下的对称差均为0 mm²；04没有任何新增/删除铜，也没有改孔或接口。

## D1 具体变化

工程封装UUID仍为 `8858b5826f676c7f`。删除顶丝印POLY `e7/e9/e10/e11`；`e8` 移到局部x=-3.8 mm、y=-0.6至+0.6 mm，线宽8 mil（0.2032 mm）。`e14/e17`、两个PAD和其他封装均保持原记录；另两个ELE_PLACEHOLDER内部计数值因图元删除变化。
导出Gerber中的新增线精确位于板坐标 **(33.2,7.4)→(33.2,8.6) mm**。独立按有效绘图原语逐项比对，删除5笔、新增1笔，没有波及其他顶丝印。
新阴极线整体位于D1源封装e4的4.2×2.6 mm壳体参考轮廓外；把双方线宽计入后净距为 **1.572979 mm**。标记在阴极1脚左侧，贴片后可从器件外侧核对。此处验证的是内嵌源轮廓；未把未嵌入工程的远程3D实体当作已完成的实物公差验证。

D1阴极/阳极网络不变；D2、Q1焊盘位置和朝向不变。D2实物色带对应仍须确认。新的[SMT极性表](smt_polarity_reference.md)已绑定04完整工程，而非只绑定仍未包含封装定义的独立PCB快照。

此报告确认预期修改范围，不代表04已通过在线DFM或SMT预览，也不取消此前开放的NPTH分类及装配间距提示。原生严格检查身份、有效制造图元哈希、各文件字节差异及逐项证据见[electrical_delta_review.json](electrical_delta_review.json)。

## 04 输入身份

| 文件 | SHA-256 |
|---|---|
| [Mianguang_V0.3.epro2](../../../release_v03_precheck04/Mianguang_V0.3.epro2) | `eeda9cb493a761e124751bb28a96701ce67f361e9a53b2b18eefafbfd03e3294` |
| [schematic_netlist.json](../../../release_v03_precheck04/schematic_netlist.json) | `a3bf7b12c05700409c9660422ad78a04a8fccd2f3696976095c76cc3358a5657` |
| [Mianguang_V0.3.epcb](../../../release_v03_precheck04/Mianguang_V0.3.epcb) | `41bd43f9068be79c6358d8010b176b31b3160c33373b3d082d8f9bda8168b380` |
| [pcb_netlist.json](../../../release_v03_precheck04/pcb_netlist.json) | `cb5814a05b2b1d082879ae17e289cbdd2538863a0fce2de213dbf72ffdeaa994` |
| [Gerber_Mianguang_V0.3.zip](../../../release_v03_precheck04/Gerber_Mianguang_V0.3.zip) | `915296951145847c9b6e229feffacc6bc4edb3c42af815d3ca696ad4964370c0` |
| [Mianguang_V0.3.esch](../../../release_v03_precheck04/Mianguang_V0.3.esch) | `19a75fdb22c19aef01568e1ea68b0694a9bfd540a5b8bb7f082c7af50701a158` |
| [native_checks.json](../../../release_v03_precheck04/native_checks.json) | `789663deb4585f66d5e9c9ea9f31f2e42adb70290f5bbae1ff5e51080f2571fc` |
