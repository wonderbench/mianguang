"""Historical 2026-10-28 document generator; outputs docs/generated only."""
from pathlib import Path
from docx import Document
from docx.shared import Mm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT
import json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs' / 'generated'
OUT.mkdir(parents=True, exist_ok=True)
doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Mm(210), Mm(297)
sec.top_margin, sec.bottom_margin = Mm(18), Mm(18)
sec.left_margin, sec.right_margin = Mm(20), Mm(20)
sec.header_distance, sec.footer_distance = Mm(8), Mm(8)

for name in ['Normal','Title','Subtitle','Heading 1','Heading 2','Caption']:
    sty = doc.styles[name]
    sty.font.name = 'Noto Sans CJK SC'
    sty.font.bold = False
    sty.font.italic = False
    sty.font.color.rgb = RGBColor(0,0,0)
    rf=sty._element.get_or_add_rPr().rFonts
    rf.set(qn('w:eastAsia'),'Noto Sans CJK SC')
    for attr in ['asciiTheme','hAnsiTheme','eastAsiaTheme','cstheme']:
        rf.attrib.pop(qn('w:'+attr),None)
    pp=sty._element.find(qn('w:pPr'))
    if pp is not None:
        for border in list(pp.findall(qn('w:pBdr'))): pp.remove(border)
    sty.paragraph_format.space_after = Pt(6)
    sty.paragraph_format.line_spacing = 1.18
doc.styles['Normal'].font.size = Pt(10.5)
doc.styles['Title'].font.size = Pt(25)
doc.styles['Heading 1'].font.size = Pt(18)
doc.styles['Heading 1'].paragraph_format.space_before = Pt(0)
doc.styles['Heading 2'].font.size = Pt(12)
doc.styles['Heading 2'].paragraph_format.space_before = Pt(9)
doc.styles['Caption'].font.size = Pt(9)
for s in ['Title','Heading 1','Heading 2']:
    doc.styles[s].font.bold = True

header = sec.header.paragraphs[0]
header.text = '毫米波睡眠监测与夜灯     方案设计与样机实施'
header.style = 'Caption'
for r in header.runs: r.font.size=Pt(8); r.bold=False
footer = sec.footer.paragraphs[0]
footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
footer.add_run('2026年10月28日  ·  原型设计 R0.2   |   ')
fld=OxmlElement('w:fldSimple'); fld.set(qn('w:instr'),'PAGE'); footer._p.append(fld)
for r in footer.runs: r.font.size=Pt(8)

def p(text, style=None):
    return doc.add_paragraph(text, style)
def h(text, level=1):
    return doc.add_heading(text, level)
def new(title):
    heading=h(title)
    heading.paragraph_format.page_break_before=True
def table(headers, rows, widths):
    t=doc.add_table(rows=1, cols=len(headers))
    t.alignment=WD_TABLE_ALIGNMENT.CENTER; t.autofit=False
    pr=t._tbl.tblPr
    borders=OxmlElement('w:tblBorders')
    for edge in ['top','left','bottom','right','insideH','insideV']:
        e=OxmlElement('w:'+edge); e.set(qn('w:val'),'single'); e.set(qn('w:sz'),'4'); e.set(qn('w:color'),'D9D9D9'); borders.append(e)
    pr.append(borders)
    for c,w in zip(t.columns,widths): c.width=Mm(w)
    for i,txt in enumerate(headers): t.rows[0].cells[i].text=txt
    repeat=OxmlElement('w:tblHeader'); t.rows[0]._tr.get_or_add_trPr().append(repeat)
    for row in rows:
        cells=t.add_row().cells
        for c,txt in zip(cells,row): c.text=str(txt)
    for ri,row in enumerate(t.rows):
        for i,c in enumerate(row.cells):
            c.width=Mm(widths[i]); c.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            cp=c._tc.get_or_add_tcPr(); mar=OxmlElement('w:tcMar')
            for edge in ['top','bottom','left','right']:
                e=OxmlElement('w:'+edge); e.set(qn('w:w'),'80'); e.set(qn('w:type'),'dxa'); mar.append(e)
            cp.append(mar)
            sh=OxmlElement('w:shd'); sh.set(qn('w:fill'),'DEE7EC' if ri==0 else ('F5F7F8' if ri%2==0 else 'FFFFFF')); cp.append(sh)
            for para in c.paragraphs:
                para.paragraph_format.space_after=Pt(1)
                para.paragraph_format.line_spacing=1.12
                for r in para.runs: r.font.size=Pt(9); r.bold=(ri==0)
    p('')
    return t
def link(label,url):
    para=p('')
    part=para.part; rid=part.relate_to(url,RT.HYPERLINK,is_external=True)
    hyp=OxmlElement('w:hyperlink'); hyp.set(qn('r:id'),rid)
    run=OxmlElement('w:r'); rp=OxmlElement('w:rPr'); color=OxmlElement('w:color'); color.set(qn('w:val'),'18577A'); rp.append(color)
    size=OxmlElement('w:sz'); size.set(qn('w:val'),'18'); rp.append(size);run.append(rp)
    tx=OxmlElement('w:t');tx.text=label;run.append(tx);hyp.append(run);para._p.append(hyp)
    para.paragraph_format.space_after=Pt(5)
    return para
def picture(path, caption, width=150):
    if path.exists():
        para=p('');para.alignment=WD_ALIGN_PARAGRAPH.CENTER
        para.add_run().add_picture(str(path),width=Mm(width))
        cp=p(caption,'Caption');cp.alignment=WD_ALIGN_PARAGRAPH.CENTER
        return True
    return False

p('毫米波睡眠监测与夜灯\n样机设计方案', 'Title')
p('单人床场景  ·  床头摆放与壁挂两用  ·  白色简约外观', 'Subtitle')
p('首版采用 C1001 成品 60 GHz 雷达模组与 XIAO ESP32C3 主控，设计一块低压接口承载板，并通过暖白夜灯提供手动照明和离床联动。优先验证在床状态、体动、呼吸趋势及整夜稳定性，再决定是否投入更高精度雷达算法。')
p('用户已确定两种安装方式兼容、优先尽快获得可验证样机。当前成果包括方案、EDA初稿、Blender外观结构和V0.2固件算法；固件已开展模拟验证，实机联调和生产放行仍属后续实施门槛。')
hero_candidates=[ROOT/'models/renders/hero.png',ROOT/'models/hero.png',ROOT/'models/renders/01_hero.png']
hero=next((x for x in hero_candidates if x.exists()),None)
if hero: picture(hero,'白色机身与暖白柔光夜灯  Blender概念渲染',132)
else:
    table(['设计项','首版决策'],[
        ['雷达与主控','C1001 SEN0623 + XIAO ESP32C3'],
        ['供电与灯光','USB-C 5 V；暖白可调光；不配电池'],
        ['结构形式','独立雷达支架 + 主板 + 下部光窗'],
        ['使用场景','单人床；可靠固定；朝向胸部']],[35,135])
p('定位为非接触式睡眠趋势原型。C1001公布的呼吸、心率量程较窄，不能据此承诺异常呼吸、心律失常或睡眠呼吸暂停的识别；“深睡、浅睡、睡眠评分”仅作为厂家算法估计。[1][2]','Caption')

new('1  资源筛选与功能边界')
table(['路线','可用资源与适用性','首版选择'],[
    ['DFRobot C1001','5 V、UART；现成在床及睡眠相关输出；Arduino库、安装图、STEP资料。[1][2]','主方案'],
    ['Seeed MR60BHA2','呼吸与心率方案、协议与ESPHome资源；静止单目标。远离有效距离可能保持旧数值。[3][4]','对照评估'],
    ['Seeed MR60BHA1','官方旧型号资料可参考，产品页标停产；不宜作为新设计采购基础。[5]','排除新BOM'],
    ['TI IWRL6432系列','芯片、评估板及Radar Toolbox；适合后续深入算法与RF开发。[6]','后续研究'],
    ['Infineon与Acconeer','可作为原始雷达信号与自研算法路线；本轮不冻结具体量产模组。','资料储备']],[35,108,27])
h('第一阶段可验证的输出',2)
p('在床与离床事件、体动次数及时间分布、有效窗口内的呼吸和心率趋势、每晚有效数据覆盖率、夜灯操作及联动事件。首版用有线日志或本地串口页面完成验证；无线数据通路由XIAO预留。')
h('量程和安装约束',2)
p('C1001官方资料列出：睡眠胸距0.4–2.5 m，呼吸与心率胸距0.4–1.5 m；呼吸10–25次/分、心率60–100次/分。睡眠模式视场40°×40°，推荐向下倾斜30–45°。这些是厂家规格或安装建议，不是本样机实测结果。[1]')
p('产品资料中的11 m最远探测距离及100°×100°视场不能直接用于睡眠指标设计。厂家百分比“精度”未提供完整评估口径，本项目不转换为医学准确率。双人同床、宠物、遮挡与明显体动应单独评估，不能默认适用。')

new('2  系统架构与电气设计')
p('首版把雷达射频与算法保留在成品模组内。主PCB负责供电分配、串口连接、夜灯开关、照度和按键接口，降低自研60 GHz天线及射频调试成本。')
table(['支路','连接与实现'],[
    ['电源输入','面板USB-C受电小板 → 2针主板输入 → 保险 → 5V_SYS。CC1/CC2各设独立5.1 kΩ Rd；仅5 V，不请求PD高压。'],
    ['雷达','5V_SYS → C1001；UART 115200、8N1。主控TX接雷达RX，主控RX接雷达TX，共地。'],
    ['主控','5V_SYS → 可断开隔离跳帽/二极管 → XIAO 5V；XIAO提供3.3 V逻辑电源。'],
    ['夜灯','5 V带独立限流的暖白LED板 → AO3400A低边开关；PWM经100 Ω栅极电阻，栅极100 kΩ下拉。'],
    ['交互','外接大按键；照度接口避开灯光直射；预留测试点与串口调试。']],[30,140])
table(['信号','XIAO接口','外设连接'],[
    ['雷达发送/接收','D6 / GPIO21；D7 / GPIO20','分别到C1001 RX、TX；自定义J2第3、4针'],
    ['夜灯PWM','D2 / GPIO4','MOSFET栅极电阻'],
    ['手动键','D1 / GPIO3','低电平有效，外部上拉与去抖'],
    ['照度I2C','D4 / GPIO6；D5 / GPIO7','SDA、SCL；外接模块须自带3.3 V上拉']],[30,56,84])
h('电源与布线设计要求',2)
p('采用合格5 V电源适配器。设计预算：雷达100 mA（厂家上限）、夜灯100 mA、主控与通信预留350 mA、其他50 mA，合计约600 mA；峰值和保险温升需实测。建议电源明确支持5 V/1 A及以上。PTC需按环境温度降额，不能把其保持电流视为恒定限流值。')
p('单个肖特基二极管不能完整隔离外供电和主控编程USB。调试时按硬件说明断开供电跳帽；禁止在未验证电源路径时同时连接两路电源。雷达断电时将串口引脚置高阻，核查防止GPIO反向供电。')
p('LED大电流回流直接回电源入口，避开雷达/主控信号回流；保持连续地参考，减少PWM环路面积。最终焊盘、铜宽、器件间距和地铜连接须经ERC/DRC及人工电源路径审查。')

new('3  两用安装与白色简约外观')
p('机身初稿100×116×44 mm，采用哑光白圆角壳体，上部布置雷达非金属透波区域，下部设置暖白漫射光窗。背部配置供电入口及安装接口，桌面支架与壁挂背板共用机身。支座的转轴、锁紧和全角度碰撞尚需结构细化。')
table(['结构项','设计约束'],[
    ['主PCB','66×56 mm，厚度目标1.6 mm；孔中心(5,5)、(61,5)、(5,51)、(61,51) mm，相对板角。'],
    ['雷达模组','C1001约22×22 mm；使用独立支架与线束，精确孔位/针序按厂家图纸和实物核验。[1]'],
    ['雷达窗','无金属涂层、金属标牌及导电漆。材质、厚度、天线间隙均为试验参数；制作不同厚度试片A/B测试。'],
    ['灯光与热','灯板位于下部，发热与反光金属件避开雷达正前方。漫射件遮蔽直视LED亮点。'],
    ['装配','给线束弯曲和拔插留空间；开孔、螺钉、支座阻尼、防滑与壁挂脱落需实体试装。']],[30,140])
h('安装方法',2)
p('壁挂优先参考厂商睡眠安装方式：床头上方安装、向下30–45°指向胸部，确认胸部在有效距离和40°睡眠视场内。床头柜模式需要调整机身位置、支架角度及床面相对高度；矮床头柜可能不能满足俯视条件，此时采用壁挂。两用结构兼容不等于两种姿态已通过监测验证。')
h('夜灯交互目标',2)
p('暖白目标色温约2200–2700 K，首版用带限流灯板控制最大功率不超过0.5 W。手动短按开关、长按调光；自动模式仅在暗环境且检测到可靠离床事件时亮灯，渐亮约1 s，延时约60 s后渐灭，均为可配置初值。')
p('环境阈值需实测标定，未标定照度接口不显示伪精确lux。先判定环境亮度再亮灯，并加滞回/保持，防止自身灯光导致反复开关。手动操作优先；通信失败不触发连续闪烁，启动时MOSFET硬件下拉保持灭灯。')

new('4  固件与数据有效性')
p('V0.2已实现独立协议解析、查询调度、数据质量、趋势与夜灯逻辑。JSONL记录原始值、有效标记、独立数据年龄、错误原因和本机固件版本；模块固件版本待实机采集登记。实现依据厂家源码核对，未直接复用其失败返回值。[2]')
table(['步骤','实现规则'],[
    ['初始化','默认UART高阻，确认雷达供电后启用；等待10 s，查询睡眠模式。需要切换时再等待10 s并读回确认。'],
    ['采集','6字段逐项查询，响应后间隔100 ms、超时500 ms；核验完整帧与响应命令，仅新接受字段更新时间。'],
    ['有效性','通信正常、数据新鲜、在床/存在、低体动、量程内同时满足才纳入趋势。不可测条件输出缺失，不补零。'],
    ['失效','单次通信故障即撤销旧证据，连续3次超时重新确认模式。零值、未知及越量程不推断呼吸停止。'],
    ['统计','当前1 s桶及前59桶计算中位数和观测覆盖率；不重复计缓存值。厂商阶段原码单独保留，不生成临床分期。'],
    ['保存','优先本地日志；导出前取得使用者同意。默认不上传云端，不采集音视频；记录身份使用匿名编号。']],[30,140])
h('软件验证与剩余边界',2)
p('已通过协议、状态机、趋势和夜灯模拟测试，覆盖坏帧、旧数据、8小时场景、25天故障恢复及跨49.7天计时回绕。接收层使用固定容量和完整校验，避免厂家库失败返回0/0xFF被当成有效读数。模拟通过不代表实机测量准确度已验证。')
p('C1001未在本方案中被假定可以实时提供准确胸距或多人数量。有效安装距离需由安装步骤和测距记录确认；若没有相应运行时证据，系统应显示“安装条件未确认”，而不是自动宣称数据可信。')
h('联动失效与隐私',2)
p('夜灯联动独立于睡眠评分，禁止因为评分低或心率超出模组量程而自动作医学报警。离线时保留手动照明，数据缺口可追踪。后续接入手机或家庭网络时，再确定配网认证、加密传输、存储周期与删除机制。')

new('5  样机验证与通过条件')
p('下表是拟定工程目标，不是已通过测试结果。先验证电气安全和数据链路，再测试安装与整夜数据。任何一项异常都记录条件、固件版本、波形或日志，调整后复测。')
table(['测试项','方法','初步通过条件'],[
    ['上电与电源','限流电源首次上电；测各支路电流与5 V/3.3 V；测试灯满亮及无线峰值','无异常发热/复位；电压满足器件手册；无主机回灌'],
    ['串口异常','断开TX/RX、模块断电、破坏帧校验、恢复连接','故障/缺失可见；不生成零呼吸事件；不延用旧帧作新数据'],
    ['距离和姿态','0.5/1.0/1.5 m；正躺、侧卧、翻身；桌面和壁挂各测','逐条件报告覆盖率；越界/干扰不伪造可信输出'],
    ['在床与离床','人工标注不少于30次上下床，记录夜灯联动','统计漏检、误触发及延时；优先目标≥95%事件识别'],
    ['呼吸趋势','同一时间窗与合适参考设备对比，每姿态至少10 min','目标有效覆盖率≥80%；有效窗口MAE≤2次/分'],
    ['心率观察','合适参考设备同步记录，分姿态和量程统计','仅报告误差/覆盖率，不宣称医学报警能力'],
    ['灯光干扰','关灯/满亮/调光扫频，与相同雷达条件A/B比较','无明显数据丢失增加和复位；低亮无可见闪烁'],
    ['外壳与热','裸模组/试片/整壳A/B；灯满亮、无线活动至少2 h','记录透波损失与温升；目标可触表面<40℃（25℃环境）'],
    ['整夜稳定','先空房一夜，再取得同意后单人试用至少3夜','日志完整、缺失可解释、无非预期持续强光或重启']],[26,76,68])
p('MAE和覆盖率必须同时报告，并记录参考设备的不确定度。短期单人测试只能用于工程迭代，不能据此建立老年人群临床有效性。任何健康判断应与经验证的监测手段区分。','Caption')

new('6  样机物料与实施顺序')
table(['物料','数量','采购和确认事项'],[
    ['C1001 SEN0623','1','官方同型号模组；核实版本、线束定义和睡眠模式'],
    ['XIAO ESP32C3','1','确认外置天线、排针高度及USB编程通道'],
    ['66×56 mm承载PCB','1','首版2层设想；生产前完成布线和检查'],
    ['USB-C受电小板','1','5 V；CC电阻完整；匹配面板固定方式'],
    ['LED板与漫射件','1组','暖白、5 V带限流、目标≤0.5 W，选实物核查热'],
    ['按键/照度元件/连接器','1组','按键尺寸适老；传感器量程及逻辑电平核查'],
    ['开关、保护与无源元件','1组','以EDA最终BOM为准，检查MOSFET3.3 V驱动规格'],
    ['外壳/两种支架/螺钉','1组','3D打印适配验证；不按外观渲染直接开模'],
    ['5 V电源/线材','1组','满足电流能力、压降和机械可靠性']],[53,17,100])
h('实施顺序',2)
p('第一步，用成品雷达和主控飞线验证模式、通信、安装位置及数据可用性，同时测试夜灯限流和调光。该步骤可以在PCB制造前排除场景不适配。')
p('第二步，按实物冻结连接器和模块封装；完善原理图与PCB布线，完成ERC、DRC、网络连通与电源回灌审查，再输出制板文件。未通过检查的初稿不得直接投板。')
p('第三步，打印外壳和两种支架，验证螺柱、线束、USB开孔、倾角保持和雷达窗。装配后重做灯光/射频干扰测试，再开展整夜试用。')
p('建议以1–2周作为首轮工程验证排期目标（不含器件物流和制板等待），以实际采购、固件调试和试装结果调整。当前未采购物料，未支付费用；本方案不提供未经询价的精确成本承诺。')

new('7  交付状态与官方资源')
p('资料集中在本地项目目录：research为来源，hardware为EDA工程，industrial为Blender模型，firmware为固件、算法与测试，docs为方案书。当前EDA按用户安排暂停，最后元件修改后的复核与一致性导出待恢复完成。')
status_path=ROOT/'docs/source/delivery_status_2026-10-28.json'
status=json.loads(status_path.read_text()) if status_path.exists() else [
    ['方案与资源','已形成首版；引用链接见下方'],
    ['嘉立创EDA','原理图与PCB初稿正在创建；最终检查记录另附'],
    ['Blender','外观与结构初稿正在创建；机械试装待验证'],
    ['样机与量产','固件联调、物料实测、投板和组装尚未进行']]
table(['交付项','当前状态'],status,[36,134])
p('以下资源均为官方资料或厂商代码仓库，访问日期2026年10月28日。型号、库和产品状态后续可能更新；采购前应固定版本。')
sources=[
('[1] DFRobot C1001 参数和安装指南','https://wiki.dfrobot.com.cn/SKU_SEN0623_C1001_mmWave_Human_Detection_Sensor'),
('[2] DFRobot HumanDetection 官方驱动与例程','https://github.com/DFRobot/DFRobot_HumanDetection'),
('[3] Seeed MR60BHA2 入门及资料','https://wiki.seeedstudio.com/getting_started_with_mr60bha2_mmwave_kit/'),
('[4] Seeed MR60BHA2 数据保持与使用条件','https://wiki.seeedstudio.com/ha_with_mr60bha2/'),
('[5] Seeed MR60BHA1 产品状态','https://www.seeedstudio.com/60GHz-mmWave-Radar-Sensor-Breathing-and-Heartbeat-Module-p-5305.html'),
('[6] TI IWRL6432 产品与设计资源','https://www.ti.com/product/IWRL6432'),
('[7] Seeed XIAO ESP32C3 硬件和引脚说明','https://wiki.seeedstudio.com/XIAO_ESP32C3_Getting_Started/'),
('[8] DFRobot C1001 英文安装指南','https://wiki.dfrobot.com/sen0623/docs/21502'),
]
for label,url in sources: link(label,url)
p('工程结论：C1001路线适合快速验证交互和有限条件下的睡眠趋势。如果后续要求跨姿态、宽量程的心率/呼吸可靠测量，需在模组评估与算法阶段重新选型，不能仅通过修改展示界面获得这些能力。')
doc.core_properties.title='毫米波睡眠监测与夜灯样机设计方案'
doc.core_properties.subject='资源选型、电气设计、白色两用外壳与验证计划'
doc.core_properties.author=''
doc.save(OUT/'毫米波睡眠监测与夜灯_样机设计方案.docx')
print(OUT/'毫米波睡眠监测与夜灯_样机设计方案.docx')
