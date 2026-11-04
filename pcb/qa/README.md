# V0.2 离线验收

本目录只读取发布文件，不连接 EDA。最终验收结果应写到本目录，避免修改被 `manifest.json` 冻结的发布目录。

```sh
pcb/qa/.venv/bin/python pcb/qa/check_release.py pcb/release_v02 --output pcb/qa/release_v02_acceptance.json
```

从项目根目录运行。返回值：`0 = PASS`、`1 = FAIL`、`2 = UNVERIFIED`。缺少资料、无法可靠解释的几何、未验证的依赖版本都不能得到 `PASS`。这项离线检查不能代替首件焊接、电源时序、负载温升及实物尺寸验证。

## 输入约定

`pcb/release_v02` 应包含：

- 本次最终原理图 `.esch` 和 PCB `.epcb`。
- 最终完整工程 `.epro2`，其中应包含所有元件的实际封装源；也接受逐个 `.efoo` / `.epru` 封装源。只提供 U1 封装不足以独立归属所有铜层焊盘。
- EDA 导出的原理图网表 JSON：顶层 `components`，元件含 `props`、`pinInfoMap`。接受工具返回的 `success/result` 包装。
- PCB 电气 BOM 的 CSV 或 TSV；表头含 `Designator` 或 `Reference`、`Manufacturer Part`、`Supplier Part`。外接件补充 BOM 可同时保留，但不代替 PCB 电气 BOM。
- 一份本次 Gerber ZIP，含顶铜、底铜、板框中心线、PTH 和 NPTH 钻孔。检查器直接读取 ZIP，不依赖预解压目录。
- `manifest.json`，记录所有发布文件的相对路径、SHA-256、字节数；不包含清单自身。

```json
{
  "release": "V0.2",
  "files": [
    {"path": "pcb_v02.epcb", "sha256": "64位十六进制摘要", "bytes": 12345}
  ]
}
```

清单中的文件必须存在且内容完全一致，发布目录也不能存在未列入的文件。同一原理图/PCB 的多个导出副本应具有相同的几何、电气和标注记录；显示颜色、编辑器选项及默认占位计数不作为设计差异。原生工程中的空记录是删除指令，解析时按同一 ID 的最后状态处理。

已按实际导出差异验证的规范化包括：编辑器 `zIndex`、缺省 `false`、缓存库名，以及在最终符号库中已确认不存在的引脚所遗留的 `NO_CONNECT` 属性；后者逐项列在报告中，有效引脚的 `NO_CONNECT` 差异仍会失败。SCH/PCB 网表比较会求值 `={Value}` / `={Manufacturer Part}` 显示公式，处理仅原理图具有的 `Symbol` 和默认顶面放置表示；位号、实际引脚网络、器件身份、采购属性仍须一致。回归专门确认这些处理不会放过旧版文字或旧保险丝。

## 覆盖范围

`check_release.py` 检查：

- 电源、雷达 UART、夜灯低侧 MOSFET、按键、I2C 和 C4/C5 去耦的核心引脚网络。
- JP2/JP3 分别位于 R4/R5 与雷达 UART 端之间，移除跳线帽能把两侧网络分开；JP1 电源分段保持独立。
- U1 超过第 14 脚的底部引脚不再接网；物理封装恰有 14 个独立 PTH，没有残留 SMD pad primitive。排距 15.24 mm、针距 2.54 mm，孔径和环宽在约定范围内。
- F1 为 `1206L110/16WR / C3761685`，D1 为 `SS14 / C2480`，Q1 为 `AO3400A / C20917`；原理图、网表、BOM 和 PCB Device ID 相符。
- 所有物理 PAD_NET primitive 均能解析到最终封装，原理图与 PCB 引脚网络一致，BOM 位号集合一致。
- 原生 66 × 56 mm 闭合矩形板框、四个 2.7 mm 安装孔及其位置；图纸与 PCB 标注为 V0.2。

`gerber_checks.py` 独立检查实际制造几何：

- 板框按中心线测量，避免将绘制线宽误算成板尺寸。
- 全部钻孔与原生封装/过孔位置、孔径、镀铜类型一一配准。EasyEDA 额外 Via 钻孔文件只有在证实为主 PTH 文件的精确子集后才去重。
- 按对象极性合成铜；先处理单个 aperture 的透明孔，避免错误擦除其他对象的铜。
- 扣除钻孔，只用确认镀铜且上下层有完整铜环的孔桥接两层。NPTH 不桥接铜层。
- 用实际焊盘铜面/铜环定位铜岛；检查同网全部焊盘连通、异网不短接。无连接引脚分别保留独立组。不会把电阻、保险丝、二极管或跳线帽当作裸板铜连接。
- 两档圆弧离散误差（0.0005 / 0.000125 mm）得到相同拓扑才通过，不通过膨胀铜图形来填补间隙。
- 顶层锡膏对全部 29 个 SMT 焊盘检查精确中心开口和完整焊盘面积覆盖，最终全窗目标为至少 98%；检查全部 THT 铜盘范围无锡膏、没有超出 SMT 铜盘加 0.02 mm 容差的开口或无归属开口。自定义缺口开口会准确记录覆盖率，不称为“完全漏开”。

解析器警告、不支持的坐标镜像/底面元件/盲埋孔/槽孔等会产生 `UNVERIFIED`。这不是完整制造 DRC；线宽、净距、阻焊、丝印压盘及制造能力仍应查看 EDA 的严格 DRC 和制造预览。

## 环境与回归

已有隔离环境 `.venv` 使用 Python 3.12。重建时可用 Python 3.12+ 创建虚拟环境，再安装 `requirements.txt` 中固定的两个版本；不要把未知版本的几何运算结果直接当作已验证结果。

```sh
pcb/qa/.venv/bin/python -m unittest discover -s pcb/qa -p 'test_release_checks.py' -v
```

回归包含旧保险丝、UART 跳线旁路、XIAO 多余 SMD 焊盘/旧 primitive、旧底部 GND、被修改的发布文件、错误板框等失效案例。

最终44项验收报告在`../release_v02_acceptance.json`，与`../release_v02/manifest.json`绑定。本仓库不包含早期中间预检数据。重新检查输出另存到本地报告文件，不覆盖冻结交付文件。

几何库来源：[Gerbonara](https://gerbolyze.gitlab.io/gerbonara/)、[Shapely](https://shapely.readthedocs.io/)。
