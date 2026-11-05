# V0.3 在线DFM预检文件

**当前文件为PRECHECK04，在线PCB及SMT复检已完成。** 最新[04报告](../qa/v03/online_dfm/PRECHECK_04_review.md)为PCB 0危险/16警告、SMT 0危险/0警告；D1本体丝印警告已关闭。源文件保持不变，尚未制造放行。以下为处理剩余孔分类、工艺设置和贴装确认时使用的同版资料：

1. 上传[04 Gerber ZIP](Mianguang_V0.3_DFM_PRECHECK_04.zip)，无需解压；与`../release_v03_precheck04/Gerber_Mianguang_V0.3.zip`字节一致。
2. 同一04板资料导入[SMT BOM](smt_precheck04/BOM_SMT_Mianguang_V0.3.csv)及[SMT坐标](smt_precheck04/CPL_SMT_Mianguang_V0.3.csv)，共9组14件SMT；9件手工项另列。核对全部位号、选料和[极性](../qa/v03/precheck04/smt_polarity_reference.md)，再执行PCB和SMT分析。
3. 核对4个Ø2.7 mm安装孔在DFM/CAM中归为NPTH，保持孔位孔径。若页面没有分类调整入口，提交板厂CAM确认；当前文件内已有NON_PLATED声明，不为消警增加铜盘或删孔。
4. 让装配方确认先SMT后手焊的8条间距提示、工艺边/定位点；将分析工艺与目标无铅喷锡统一。保存完整报告、问题位置和选料/方向预览后回传。

板参数：FR-4、2层、66 × 56 mm、厚1.6 mm、1 oz铜、绿色阻焊、白色丝印、目标无铅喷锡。03两份及04报告均为有铅喷锡；SMT勾选和无危险不代表所有贴装匹配及工艺条件都已接受。

04原生DRC零提示，本地验收49/49、制造检查40/40通过；最新在线复检已归档，但16条PCB警告及最终工艺接受仍待确认。上传包保留主PTH 38孔与主NPTH 4孔；只删除经验证重复的Via分类附表，[去重证据](../qa/v03/precheck04/gerber_drill_dedup.json)保存原始文件哈希。

01、02、03 ZIP及`smt/`、`smt_precheck03/`为历史资料；不与04混用。原始报告和当前结论分别归档，不改写已有冻结清单和旧交付ZIP。
