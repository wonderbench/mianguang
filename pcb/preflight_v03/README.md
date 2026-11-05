# V0.3 在线DFM预检文件

**最新为PRECHECK03，待用户重新上传PCB DFM和SMT检查。** 02版报告已收到并归档；03版仅完成本地检查，尚未制造放行。

1. PCB图层分析上传[Mianguang_V0.3_DFM_PRECHECK_03.zip](Mianguang_V0.3_DFM_PRECHECK_03.zip)，无需解压。它与`../release_v03_precheck03/Gerber_Mianguang_V0.3.zip`字节一致。
2. SMT分析在同一03版PCB资料上上传[贴片BOM](smt_precheck03/BOM_SMT_Mianguang_V0.3.csv)和[贴片坐标](smt_precheck03/CPL_SMT_Mianguang_V0.3.csv)：14件顶层SMT、9组物料。另9件手工项不混入这两份文件。
3. 检查平台选料、方向和贴装预览。D1/D2/Q1的方向见[极性表](../qa/v03/precheck03/smt_polarity_reference.md)。保存PCB及SMT完整报告、问题位置图和采用的工艺参数，再回传。

板参数：FR-4、2层、66 × 56 mm、厚1.6 mm、1 oz铜、绿色阻焊、白色丝印，目标为无铅喷锡。02报告使用有铅喷锡，03分析时请与目标工艺保持一致。

03原理图/PCB严格DRC均零提示，独立验收49/49、制造几何40/40通过；后者增加实际阻焊窗/钻孔间距≥0.25 mm、笔画≥0.20 mm门槛。孔位与钻孔后铜图形保持不变。仍保留8条插件到贴片间距工艺提示，采用先贴片、后手工焊接，不写为零警告通过。

03上传包仅移除已证明属于主PTH精确子集的`Drill_PTH_Through_Via.DRL`分类附表，保留全部制造层成员原字节。38个PTH加4个NPTH，共42个独立孔；[原始导出及去重证据](../qa/v03/precheck03/gerber_drill_dedup.json)可追溯。

历史文件保留：01版已被取代；02版及`smt/`对应[用户回传报告](../qa/v03/online_dfm/PRECHECK_02_report.pdf)，不能和03版混用。
