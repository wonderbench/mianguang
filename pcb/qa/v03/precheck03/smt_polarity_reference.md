# PCB V0.3 PRECHECK 03 SMT 极性与朝向核对表

核对日期：2026-11-05。已从 PRECHECK 03 完整工程重新提取七个焊盘并与本表逐项核对。仅用于上传后的贴装预览复核；未操作 EDA，未确认平台贴装预览。

坐标取自最终完整工程内的实际封装焊盘、PCB实例和原理图网表，单位 mm；**从顶面看，板框左下角为 (0,0)，X 向右、Y 向上**。下表采用焊盘中心坐标，保留三位小数。所有三件均在顶面。

| 位号／物料 | 器件放置中心 (X,Y) | 原生 CPL Rotation | 预览必须满足的方向 |
|---|---|---|---|
| D1／SS14／C2480 | (37.000, 8.000) | 0° | 阴极 K／本板1脚在左侧（X较小）；阳极 A／2脚在右侧。SS14 色环端应落在 K 端。 |
| D2／SMF5.0A／C2980403 | (24.000, 14.000) | 90° | 本板设计阴极 K／1脚在下侧（Y较小，朝 y=0 板边），接5V_SYS；阳极 A／2脚在上侧接GND。器件色带与阴极的对应仍需按供应商当前包装图确认。 |
| Q1／AO3400A／C20917 | (49.000, 17.000) | 0° | 单独一只引脚在左侧，为3脚 D；右侧两脚中，下方为1脚 G、上方为2脚 S。 |

**Rotation 只是当前 EDA 封装坐标系的导出值，不等于嘉立创贴装物料库的零度定义。** 在平台预览中按实际针脚/阴极位置确认；如平台零度不同，应调整平台贴装角度后再核对，不能只比较角度数字。

| 位号 | 本工程焊盘号 | 端子功能 | 网络 | X | Y |
|---|---|---|---|---:|---:|
| D1 | 1 | K 阴极 | `5V_ISO` | 35.035 | 8.000 |
| D1 | 2 | A 阳极 | `5V_SYS` | 38.965 | 8.000 |
| D2 | 1 | K 阴极（设计针义） | `5V_SYS` | 24.000 | 12.415 |
| D2 | 2 | A 阳极（设计针义） | `GND` | 24.000 | 15.585 |
| Q1 | 1 | G 栅极 | `LED_GATE` | 50.000 | 16.050 |
| Q1 | 2 | S 源极 | `GND` | 50.000 | 17.950 |
| Q1 | 3 | D 漏极 | `LED_LOW` | 48.000 | 17.000 |

## 极性依据与待确认项

- **D1：已核对。** 原理图网表明确1=K、2=A；MDD 的 SS12～SS1200 系列原始手册（包含SS14）说明色带表示阴极。实际封装1号焊盘位于本表左侧。[MDD 原始资料（LCSC托管）](https://datasheet.lcsc.com/lcsc/2312180756_MDD-Microdiode-Semiconductor-SS14_C2480.pdf)
- **D2：设计方向已核对，实物标识尚未闭环。** 本项目单向TVS符号的阴极线位于1脚一侧，封装阴极丝印也位于1号焊盘一侧；网表为1→5V_SYS、2→GND。供方当前记录确认其为 GOODWORK 单向 SMF5.0A／SOD-123FL，但本轮原厂PDF下载返回403，未能目视核对色带标识，不能以其他品牌同型号图替代。[供方具体物料记录](https://jlcpcb.com/partdetail/GOODWORK-SMF50A/C2980403)、[原厂资料入口](https://www.lcsc.com/datasheet/C2980403.pdf)
- **Q1：已核对功能方位。** 原理图网表明确1=G、2=S、3=D；AOS 原始手册第1页 Top View 已目视复核：独脚侧为D、另侧为G/S，标记点靠G一端。该页用G/S/D而非数字标号，因此本表的1/2/3编号来源明确为工程网表，不把厂商未印出的数字说成手册原文。[AOS AO3400A 原始手册](https://www.aosmd.com/sites/default/files/res/datasheets/AO3400A.pdf)

本表不能替代贴装平台的封装匹配、实物包装方向和首件焊后极性检查。D2 当前标识待确认项应在SMT订单确认前闭环。

## PRECHECK 03 输入身份

| 文件 | SHA-256 |
|---|---|
| [Mianguang_V0.3.epro2](../../../release_v03_precheck03/Mianguang_V0.3.epro2) | `01f43cf3fcebcb7f2e6dfb590aaf878a952d3f6b54837cca8e0f2a40bde66e1f` |
| [Mianguang_V0.3.epcb](../../../release_v03_precheck03/Mianguang_V0.3.epcb) | `1b005cf1bb2e7d59b4584eca6a2bd83e2b9e46b83c3a32bf83ad4a90f7a16536` |
| [schematic_netlist.json](../../../release_v03_precheck03/schematic_netlist.json) | `a3bf7b12c05700409c9660422ad78a04a8fccd2f3696976095c76cc3358a5657` |
| [PickPlace_Mianguang_V0.3.csv](../../../release_v03_precheck03/PickPlace_Mianguang_V0.3.csv) | `c53d8d2d6d1a3afaca18bf15c87e625e6a3604dd6baf38c3b4521e5a87b64704` |

对应针脚和坐标的机器复核记录见 [electrical_delta_review.json](electrical_delta_review.json) 中 `precheck03_polarity_pad_reference` 与 `precheck03_polarity_cpl`。
