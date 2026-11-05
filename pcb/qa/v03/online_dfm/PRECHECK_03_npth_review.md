# PRECHECK 03：NPTH 与“Pth无Pad”专项复核

日期：2026-11-05。冻结文件本地复核：**PASS**，14 项检查；线上该项仍为 **8 条警告，待分类确认**。未修改 EDA、源文件、Gerber 或冻结包。

结论：四孔是有意设计的无镀铜机械安装孔，源与导出一致，两面都具有充足铜避让。未发现需要增加铜焊盘的缺陷；不能为消除“Pth无Pad”提示给四个机械孔补铜。
NPTH 可没有铜环；嘉立创官方说明将其用于机械安装，并与要求铜环的镀铜孔区分。[官方 NPTH 指南](https://jlcpcb.com/blog/npth-design-guide)

## 在线报告能证实什么

[用户提供的 PDF](PRECHECK_03_report.pdf) 第1页（长页）已按 PDF 技能目视核对。报告时间 2026-11-05 20:48:56，文件名为 `Mianguang_V0.3_DFM_PRECHECK_03`。钻孔分析的“Pth无Pad”行列明 `Drill_NPTH_Through.DRL`，危险0、警告8、良好0，结果字段为 `null`。报告没有逐项孔坐标或服务端实际孔属性。
**4 个 NPTH × 2 个铜层 = 8** 与汇总数量一致，是合理推断；没有证据证明服务端一定按此算法计数，也不能把“误报”或“已豁免”写成确定事实。
该 PDF 仅勾选 PCB DFM；另有8条插件到贴片间距警告。本文不将本地孔审计通过改写为线上零警告、SMT通过或制造放行。PDF没有输入ZIP哈希，报告与冻结包的关联依据用户提交、文件名和预览，不是服务端密码学绑定。

## 原始钻孔声明及可识别性

| 文件 | 第1行 | 第2行 | 孔数与孔径 |
|---|---|---|
| `Drill_NPTH_Through.DRL` | `;TYPE=NON_PLATED` | `;Layer: NPTH_Through` | 4 × Ø2.70000 mm |
| `Drill_PTH_Through.DRL` | `;TYPE=PLATED` | `;Layer: PTH_Through` | 4 × Ø0.29997 + 34 × Ø1.10002 mm |

两文件都以 `M48` 开始头部，声明 `METRIC,LZ,0000.00000`，使用显式小数坐标、`G05` 钻孔模式、`G90` 绝对坐标和 `M30` 结束；没有把4个安装孔混入主PTH文件。上传包仅有两个主钻孔文件，原重复Via分类附表已在此前有证据的去重步骤中移除。
不只是文件名携带镀铜意图：把输入在内存中改用中性文件名 `neutral_name.drl`，Gerbonara 1.6.3 仍从内容识别 NPTH=False、PTH=True。分别只保留 `;TYPE=` 或 `;Layer:` 之一仍可识别；同时移除二者后属性变为未知。此控制实验只处理内存字符串，未更改冻结文件。
这两种标记是原生导出的语义注释。文件中**没有** Ucamco XNC 的标准 `; #@! TF.FileFunction,...` 属性；不能把厂商注释说成XNC标准属性，也不能保证所有CAM/在线DFM都支持。XNC规范区分孔几何与镀铜等元数据。[Ucamco XNC 2019.02.16，§4.1](https://www.ucamco.com/the_xnc_file_format_specification.pdf)
独立解析的唯一提示为 `G90 header statement found after end of header`：源导出把G90置于 `%` 后。解析器仍明确读取绝对坐标，42孔与源逐孔一致。没有证据把该格式位置提示与NPTH分类警告建立因果关系；不因此手工改写原生文件。

## 源机械孔与实际铜避让

完整工程和独立 PCB 源中的4孔均为 layer12、多层、无网络、SOLID 的单一 `CIRCLE` FILL；无机械PAD残留。半径53.1496 mil，对应直径2.69999968 mm，导出量化为2.70000 mm。该方式符合官方圆形挖槽≤6.5 mm输出NPTH的说明。[嘉立创EDA挖槽说明](https://prodocs.lceda.cn/cn/pcb/place-slot-region/index.html)
下表测量孔边到原始铜图形的最短距离，未先扣孔或扩张铜避让来隐藏重叠。以0.0005 mm和0.000125 mm两档曲线逼近复核，四孔两面孔内铜面积均为0；以下列出精细档。

| 孔中心/mm | 直径/mm | 顶层孔边到铜/mm | 底层孔边到铜/mm |
|---|---:|---:|---:|
| (5, 5) | 2.700 | 9.780988 | 9.780988 |
| (61, 5) | 2.700 | 9.300770 | 9.300770 |
| (5, 51) | 2.700 | 7.348618 | 7.348618 |
| (61, 51) | 2.700 | 10.839430 | 13.164142 |

最小净距为7.348618 mm，远大于本项目采用的0.2 mm NPTH到铜门槛。公开工艺页的NPTH到走线要求为0.2 mm；其另列的“NPTH pad annular ring”建议针对有意设置的铜焊盘，不应反推为所有纯机械NPTH必须增加铜环。[嘉立创工艺能力](https://jlcpcb.com/capabilities/pcb-capabilities)
另核对38个主PTH：两层共76个孔/层位置均有覆盖钻孔的铜焊盘和正的环宽，没有发现它们是缺铜的PTH。全部42孔与原生源的坐标、孔径、镀铜属性一一对应。详细原始钻孔内容、源图元、最近铜点和PTH逐孔记录均保留在JSON。

## 最小处理建议

保留当前四孔机械NPTH几何和铜避让。下一步核对检测端将 `Drill_NPTH_Through.DRL` / T01 Ø2.7 mm 识别为何种孔，并由平台或板厂确认这一警告的适用范围。应确认的事实是四个不镀铜机械孔，而不是给孔补铜以迎合一项标签。
嘉立创公开软件文档说明可编辑VIA/PTH/NPTH属性，但这不能证明当前网页DFM具备完全相同的菜单或操作；应以实际界面或板厂回复为准。[属性编辑说明](https://www.jlc.com/portal/server_guide_39122.html)
在得到分类/工艺确认前，这8条仍标为开放项。本次没有联系外部人员、修改检测端属性、申请豁免或制造放行。

## 输入身份

| 文件 | SHA-256 |
|---|---|
| [Gerber_Mianguang_V0.3.zip](../../../release_v03_precheck03/Gerber_Mianguang_V0.3.zip) | `8e786b7bfa3eb609b283f079b3bb2ccddcab58149d3979a5f0926bc297206811` |
| [PRECHECK_03_report.pdf](PRECHECK_03_report.pdf) | `d3689c3b8a3cae97806bd7f69210ab852bbf2b0d308eebeef730b48e138e13e3` |
| [Mianguang_V0.3_DFM_PRECHECK_03.zip](../../../preflight_v03/Mianguang_V0.3_DFM_PRECHECK_03.zip) | `8e786b7bfa3eb609b283f079b3bb2ccddcab58149d3979a5f0926bc297206811` |
| [Mianguang_V0.3.epcb](../../../release_v03_precheck03/Mianguang_V0.3.epcb) | `1b005cf1bb2e7d59b4584eca6a2bd83e2b9e46b83c3a32bf83ad4a90f7a16536` |
| [Mianguang_V0.3.epro2](../../../release_v03_precheck03/Mianguang_V0.3.epro2) | `01f43cf3fcebcb7f2e6dfb590aaf878a952d3f6b54837cca8e0f2a40bde66e1f` |
| [manifest.json](../../../release_v03_precheck03/manifest.json) | `b4005dd1d23cf3f2f2d47bcd8de1533c190a3120a7a414f98ee6ad758b45a51f` |

机器证据：[PRECHECK_03_npth_review.json](PRECHECK_03_npth_review.json)。
