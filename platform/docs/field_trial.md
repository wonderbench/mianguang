# 三台设备 / 24 小时现场记录

**当前状态：未执行实机验收。** 本文件是执行步骤与空白记录模板；host 测试、编译、模拟设备和短时 CI 均不能填作真实设备结果。验收目标来自[开发计划](development.md)和[固件接入边界](firmware_integration.md)。不新增采集服务，复用本地 USB 记录、离线摘要和平台 CSV。

## 1. 开始前登记

由现场负责人为三台真实设备分别登记 UUID、独立凭证和当前绑定，按[USB 配置说明](../firmware/README.md)完成配置。凭证保存在受控位置，证据目录不收录 token、Wi-Fi 密码或人员姓名。记录固件 Git 提交 / 构建环境、PCB 版本、机构网络与供电方式、平台版本、UTC 开始时间和负责人。模拟设备另存一份记录，并标明“合成模拟非实测”。

现场按既有硬件要求确认雷达供电、位置、角度、范围和光照条件。USB 调试须先断开外部 5 V，拔下 JP1/JP2/JP3；不因验收需要改变此要求。重启后不自动恢复 `radar on`、`install yes` 或 `ambient yes`。现场确认步骤在每次重启后重新记录。

## 2. 保留三类证据

**USB 工程日志。** 为每台设备分别记录有明确起止时间的受控调试片段。下例仅观察 10 分钟，默认不发送启用和安装确认；只有完成实际现场检查时，才使用原工具提供的显式确认参数。

```sh
python firmware/tools/capture_serial.py --port /dev/ttyACM0 --output /private/trial/A.raw.jsonl --seconds 600
```

原始日志保持原样。新的 `type="network"` 诊断行不是旧工具的 schema 1 sample，直接把混合日志交给 `summarize_log.py` 会中断其时间积分。先提取网络诊断，生成供旧摘要使用的副本；只移除已解析的 network 行，保留坏行、非网络记录及 synthetic 元数据，让旧工具仍能识别这些边界：

```sh
python - /private/trial/A.raw.jsonl <<'PY'
import json
from pathlib import Path
import sys

source = Path(sys.argv[1])
with source.open(encoding="utf-8") as raw, \
        source.with_suffix(".samples.jsonl").open("x", encoding="utf-8") as samples, \
        source.with_suffix(".network.jsonl").open("x", encoding="utf-8") as network:
    for line in raw:
        try:
            record = json.loads(line)
        except ValueError:
            samples.write(line)
            continue
        target = network if isinstance(record, dict) and record.get("type") == "network" else samples
        target.write(line)
PY
python firmware/tools/summarize_log.py /private/trial/A.raw.samples.jsonl --json /private/trial/A.summary.json --markdown /private/trial/A.summary.md
```

以上路径对应 `.jsonl`；如采集为 `.gz`，先解压到另一份文件。合成日志须保留其 synthetic 标记，或显式给摘要传入 `--synthetic`。给原始文件与派生文件分别保存 SHA-256，并记录提取方法，摘要中的来源哈希仅对应派生文件。

**网络诊断。** 在受控 USB 会话中执行 `net status`，保存原始无密钥回复与现场 UTC 时间。记录配置状态、boot / seq、最近 HTTP 结果、失败次数，以及 `heap_free_bytes`（当前空闲堆）、`heap_min_free_bytes`（该次启动最低空闲堆）、`network_stack_min_free_bytes`（网络任务栈最低剩余）和 `wifi_connections`。累计计数须按 boot 分段，不能把每次重复出现的计数相加，也不能把一次 status 当成整个试验的最大值；没有输出或没有测量的项目写“未观测”，不填 0。

**平台记录。** 管理员从绑定详情选择 UTC 整分钟窗口并导出 CSV，保存请求范围、导出时间、绑定 UUID 和文件哈希。每次导出最多 24 小时、最近 7 天内的数据；换绑前后分别导出，不能合并成同一住户历史。未绑定诊断不进入住户 CSV，应另记平台实际接收状态。参见[查询与导出边界](data_api.md)。

24 小时运行段必须同时覆盖三台设备，并记录 USB / 串口监视器断开的时间，直接以平台接收记录证明上传不依赖 USB。前后各一条记录相隔 24 小时只证明跨度，仍需核对中间缺口、重启、拒收和有效点比例。平台 10 秒快照不能套用 USB 摘要的 2 秒积分规则；接受点数、上报完整度、有效点比例均不等于连续睡眠时长。

遵守接线要求后若重新连接 USB 必须断电，前一 boot 的 RAM 诊断会丢失，应记“该运行段未观测”，另做受控资源与按键测试。不能拿重启后的低失败数或空闲堆代替先前 24 小时的证据。USB 调试片段与不接 USB 的持续运行段分别列出。

## 3. 必做场景与观察口径

| 场景 | 记录的事实与期望 |
|---|---|
| 三台持续运行 ≥24 小时，无 USB / 串口监视器 | 三个独立身份均持续上报；记录各自缺口、接受 / 拒收、boot 变化、有效点比例；不能仅凭在线绿灯判通过 |
| Wi-Fi 中断、恢复与同步重连 | 记录断开与恢复时间、每 boot 的连接 / 失败计数、恢复第一条新快照；旧缓存不得显示为当前有效测量 |
| DNS、TLS、慢 HTTP 与不可达服务器 | 记录超时、HTTP 结果、UTC 状态；UART、按键和渐变灯继续响应，队列与内存有界；错误证书不得被绕过 |
| UART / 安装 / 数据质量边界 | 安装未确认、缺失、0 / 255、过期、活动或传输故障显示明确不可用；unknown 不变成离床 |
| 受控重启 | boot 持久递增，seq 重新开始；网络可先恢复，雷达启用、安装和光照确认不自动恢复 |
| NVS 故障与计数边界 | 用受控故障注入分别记录写入前 / 中 / 后、回读不一致、计数丢失及耗尽；不成功提交则不上传，不复用旧 boot；未做的阶段逐项留空 |
| 凭证撤销、换床和未绑定 | 旧 token 拒收；错 binding 拒收；同 device 换 token / binding 保留 boot；新绑定前 5 秒隔离；两端 null 不进入住户趋势 |
| 本地功能与资源对比 | 对照联网关闭 / 开启的 UART 错误、按键响应、灯渐变和有效数据；报告测量方式、样本数、堆与任务资源观察范围 |

物理故障、断电和换绑只在负责人安排的受控设备上执行。具体预期以[设备协议](device_protocol.md)为准。自动检查只支持相应软件边界，不能代替硬件故障注入、机构网络或人工观察。

## 4. 复制填写的记录模板

试验编号：____；负责人：____；固件提交 / 环境：____；平台提交：____；PCB：____。

总状态：**未执行**。可改为“执行中 / 未通过 / 有条件通过 / 已通过”，必须附真实证据与未覆盖项。记录时区：UTC。

| 项目 | 设备 A | 设备 B | 设备 C |
|---|---|---|---|
| device UUID / 绑定 UUID（不含凭证） | 未填写 | 未填写 | 未填写 |
| 开始 / 结束 UTC、实际跨度 | 未执行 | 未执行 | 未执行 |
| 无 USB 持续运行区间 | 未执行 | 未执行 | 未执行 |
| 平台接受点 / 预期点 / 上报完整度 | 未观测 | 未观测 | 未观测 |
| RR / HR 有效点比例与分母 | 未观测 | 未观测 | 未观测 |
| 缺口与拒收、boot 变化 | 未观测 | 未观测 | 未观测 |
| USB 可积分时间 / 段跨度（分列） | 未观测 | 未观测 | 未观测 |
| UART 错误、联网失败 / 重连（逐 boot） | 未观测 | 未观测 | 未观测 |
| 堆 / 栈资源测量与覆盖范围 | 未观测 | 未观测 | 未观测 |
| 原始日志 / CSV / 摘要及 SHA-256 | 未填写 | 未填写 | 未填写 |

每个场景复制填写一行；手工时间、平台时间和设备 uptime 不混用。

| 设备 / boot | 场景 | 操作起止 UTC | 实际观察、响应时间与测量方法 | 证据路径 / 行或时间范围 | 结果、未覆盖项、复核人 |
|---|---|---|---|---|---|
| 待填写 | 待填写 | 未执行 | 未观测 | 无 | 未执行 |

最终结论必须单独给出三台持续运行、网络与本地功能隔离、身份 / 计数故障、配置换绑、资源测量各项的证据。日志跨度达到 24 小时不会自动生成“通过”，未覆盖项目也不能由模拟数据补齐。
