# 睡眠监测雷达选型证据与集成约束

检索日期：2026年10月28日。首版选择 **DFRobot C1001（SEN0623）成品雷达模组 + ESP32 承载板 + 独立暖白夜灯**。选择依据是已有睡眠状态接口、5 V 低功耗供电和官方 ESP32 示例，可先验证安装与整夜数据。这里的“已核实”表示官方文档有明确陈述，不表示本项目已完成实物验证。

## 首版模块的已核实条件

| 项目 | 证据与工程含义 |
|---|---|
| 供电 | C1001 为 5 V、≤100 mA。独立保留去耦与电源测试点；夜灯回流不穿过雷达支路。[官方产品页](https://www.dfrobot.com/product-2861.html) |
| 通信 | 官方例程采用 UART 115200、8N1，并将 TX/RX 直接接 ESP32-S3。3.3 V 主控兼容性有官方接线依据，但 UART 的绝对最大额定值和 VIH/VIL 尚未给出。[官方示例](https://wiki.dfrobot.com/sen0623/docs/21573) |
| 尺寸和针脚 | 官方尺寸图为 22 × 22 mm；单排 2.54 mm 焊孔。从图示天线面左侧自上而下为 VIN、GND、RX、TX、IO1、IO2。右侧两个安装孔中心距18 mm。尺寸图与原厂 STEP 已下载到 `datasheets/`；孔径、器件总高和接插件方向在实物到货后复核。[尺寸图](https://dfimg.dfrobot.com/5ea64bf6cf1d8c7738ad2881/wiki/4dca8a50b5a8a87f953c4d4a5ff854c6.png) |
| 检测范围 | 睡眠检测胸部距离0.4–2.5 m；呼吸/心率0.4–1.5 m；官方标称呼吸10–25次/分、心率60–100次/分。11 m是其他检测场景范围，不能写成睡眠生命体征距离。[官方规格](https://wiki.dfrobot.com/sen0623) |
| 视场与安装 | **睡眠模式40° × 40°**；100° × 100°属于跌倒模式。向下倾角30–45°；图示床头上方约1 m、胸部斜距≤1.5 m。壁挂可复现这一姿态；床头柜模式需使用支架并以胸部对准测试确认。[官方安装说明](https://wiki.dfrobot.com/sen0623/docs/21502) |
| 输出 | 官方例程包含在床、睡眠状态、体动、翻身、整夜统计、呼吸和心率字段。睡眠分期、评分和 apneaEvents 属于模组算法输出；没有据此建立本项目的临床有效性。[睡眠示例](https://wiki.dfrobot.com/sen0623/docs/21572) |

主板可使用项目自定义四针口：1=5V_RADAR，2=GND，3=MCU_TX→模块RX，4=MCU_RX←模块TX。该针序是本项目线束定义；装配时核对厂家焊孔丝印。IO1/IO2本版可不接，不能把跌倒模式电平输出直接当作睡眠模式在床信号。

首版功能限定为单人睡眠场景下的在床/离床、体动和有效测量区间内的呼吸/心率趋势。心率60以下或100以上、呼吸10以下或25以上不在该模组标称范围；超范围、零值、数据缺失不能自动解释为疾病、心搏停止或呼吸暂停。厂家本身也明确该模块不是经认证的医疗器械。[产品说明](https://www.dfrobot.com/product-2861.html)

## 候选路线比较

| 路线 | 已确认资源 | 本项目决定 |
|---|---|---|
| C1001 SEN0623 | 5 V UART模组；22 × 22 mm；睡眠接口、Arduino库和STEP公开 | 首版主选。现成算法用于快速评估，异常生命体征和临床分期不作承诺 |
| Seeed MR60BHA2 | 当前kit集成XIAO ESP32C6、BH1750和ESPHome；裸模组25 × 31.5 mm、3.3 V；裸模组和5 V kit不同 | 可购kit作为第二套对照；不要按5 V直接替换裸模组。算法闭源；现有官方文档仍提示心率/呼吸质量问题。[入门与资料](https://wiki.seeedstudio.com/getting_started_with_mr60bha2_mmwave_kit/) |
| Seeed MR60BHA1 | UART、呼吸/心率和睡眠模式文档较多；官方商店检索结果已标停产、缺货，页面直读返回403 | 不作为新设计采购基础；留作协议和算法字段参考。[官方资料](https://wiki.seeedstudio.com/Radar_MR60BHA1/) |
| TI IWRL6432 / IWR6843 | IWRL6432为57–64 GHz、2TX/3RX、M4F与HWA平台；官方有生命体征开发资源。IWR6843“Vital Signs with People Tracking”示例仅提供二进制 | 需要自有雷达算法、原始数据或多人研究时进入第二阶段；不在首版自绘60 GHz射频前端。[IWRL6432](https://www.ti.com/product/IWRL6432)、[IWR6843示例](https://dev.ti.com/tirex/explore/content/radar_toolbox_4_00_00_05/source/ti/examples/Industrial_and_Personal_Electronics/Vital_Signs/Vital_Signs_With_People_Tracking/docs/vital_signs_with_people_tracking_user_guide.html) |
| Infineon BGT60TR13C | 58–63.5 GHz，封装天线，1TX/3RX，SPI；官方列睡眠/心率应用和合作伙伴方案 | 芯片及算法开发路线，需要配套主控、信号处理与验证；芯片应用标签不等于提供量产心率/睡眠算法。[器件页](https://www.infineon.com/part/BGT60TR13C) |
| Acconeer A121 / XM125 | 60 GHz PCR；XM125含M4主控；有呼吸参考应用、I2C接口文档与实测用例 | 呼吸优先和可研究算法的备选；参考应用不提供完整睡眠分期或心率产品保证。[呼吸应用](https://docs.acconeer.com/en/latest/ref_apps/a121/breathing.html)、[XM125资源](https://developer.acconeer.com/home/a121-docs-software/xm125-xe125/) |

MR60SLEEP1未检索到足以确认型号、供货和接口的官方资料，不进入BOM。Seeed旧款睡眠模块MR24BSD1为24 GHz，官方页面标停产；不能与60 GHz型号混写。[官方商品页](https://www.seeedstudio.com/24GHz-mmWave-Radar-Sensor-Sleep-Breathing-Monitoring-Module-p-5304.html)

## 软件有效性与库审阅

官方 `DFRobot_HumanDetection` 库快照已保存于 `vendor_library/`，用于接口核对，不建议未经修订直接作为可靠性边界。审阅发现：

- `smHumanData()` 通信失败仍可能返回初始值0，造成“无人”歧义。
- `getSleepComposite()` 和整夜结构查询有默认全0返回；通信错误可能被解释为正常枚举或零频率。
- `getHeartRate()`、`getBreatheValue()`、`smSleepData()` 默认返回0xFF，不能当作真实测量。
- 底层 `getData()` 将通信结果与数据值分开，但上层部分接口丢失该状态。接收器应加入最大帧长度、完整帧尾与校验验证，仅在读到新字节时推进状态机。

因此固件设计应为每个字段保存 `value`、`valid`、`last_valid_frame_ms`、`error`。掉线、校验错误、超时、离床、明显体动和超标称范围时输出“不可用”；离床夜灯逻辑不能把通信故障当作离床事件。数据新鲜度阈值在确认模块更新周期后确定。[官方库源码](https://github.com/DFRobot/DFRobot_HumanDetection)

MR60BHA2官方特别说明：目标超出1.5 m时呼吸和心率可能保持上次测量；静止单人是必要条件，人数估计为实验性。若后续改用该模块，要独立做距离/有人/字段新鲜度门控，不能只检查UART仍在发送。[官方数据报告说明](https://wiki.seeedstudio.com/ha_with_mr60bha2/)

## 外壳与夜灯边界

以下为项目设计目标：雷达模块置于独立前上方透波区；夜灯、铜板、金属螺钉和导线不覆盖天线；暖白漫射发光面与雷达窗分离。可更换的白色PC/ABS雷达窗从约1.5 mm厚开始制样，最终厚度和空气间距通过不同材料、颜料、纹理样片与裸模块对比确定，不能把“非金属”视为零损耗。TI及Acconeer文档说明材料、厚度和形状都会改变透射与方向图。[TI透波罩指南](https://www.ti.com/lit/an/swra705/swra705.pdf)、[Acconeer结构指南](https://docs.acconeer.com/en/latest/hw_integration/a121/radome_and_mechanical_design.html)

## 待确认事项

1. C1001实际到货硬件/固件版本、供货周期、UART额定电平、孔径、板厚和连接器高度。
2. 双人床、厚被、侧卧/俯卧、风扇/窗帘、宠物、护理人员经过、床架振动对误报与有效数据占比的影响；首版不保证多人分离。
3. 睡眠状态、评分和apneaEvents的算法定义、时间窗、固件变更及与临床对照的性能；没有这些证据前仅保留为研究字段。
4. 床头柜与壁挂两种结构都应实测胸部距离和角度；机械兼容不等于同等监测性能。
5. 夜灯PWM满亮/最低亮、Wi-Fi发送、USB电源纹波、断电重启与通信断线时雷达数据的完整性。

以上资料未形成医疗诊断算法验证、射频认证或量产放行结论；工程样机验证通过后，再决定是否扩展性能指标与用途。
