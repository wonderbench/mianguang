# 固件接入边界与最小改造

核对日期：2026-11-04。基准是仓库中固件 V0.2.0 与 PCB V0.2。本文件区分**已实现的本地能力**与**平台接入待开发项**；本轮只交付设计文档，没有增加联网固件、刷写设备或完成实机联调。

## 1. 当前固件实际能力

| 项目 | 当前行为 | 源码依据 |
|---|---|---|
| 雷达通信 | 115200 UART；一次仅一个查询在途；六字段轮询，不保证 1 Hz 原始采样 | [配置](../../firmware/include/board_config.h)、[查询顺序](../../firmware/lib/sleep_core/src/radar_client.cpp#L16) |
| 启动与状态 | 本地程序启动关闭 UART；启用后先等 10 秒并确认睡眠模式。`ready` 只表示完成模式确认 | [setup](../../firmware/src/main.cpp#L254)、[ready](../../firmware/lib/sleep_core/include/radar_client.h#L47) |
| 数据输出 | USB CDC 的 schema 1 JSONL；约每秒一条状态快照。输出依赖 USB 串口已连接且前一条发完，不能把它当成独立采集时钟 | [queueLog](../../firmware/src/main.cpp#L200)、[flushLog](../../firmware/src/main.cpp#L245) |
| 网络与身份 | 没有 Wi-Fi、HTTPS、MQTT、设备注册、持久设备 ID、`boot_id`、消息序号或 UTC 同步 | [完整主程序](../../firmware/src/main.cpp)、[构建配置](../../firmware/platformio.ini) |
| 本地灯控 | 自动/手动灯控、按键、渐亮渐灭与光照门控由本机运行；网络尚不参与 | [主循环](../../firmware/src/main.cpp#L269)、[夜灯逻辑](../../firmware/lib/sleep_core/src/monitor_logic.cpp#L234) |
| 记录工具 | `capture_serial.py` 仅监听显式 USB 端口并写本地文件，显式确认参数才发送串口命令 | [capture_serial.py](../../firmware/tools/capture_serial.py#L11) |

客户端数字状态为 `0 Disabled / 1 StartupWait / 2 ConfirmMode / 3 SetSleepMode / 4 ModeSwitchWait / 5 Running`。平台不能把 `ready=true` 单独解释为测量有效：链路、安装确认、占用、体动和每个字段的新鲜度仍需同时判断。[状态定义](../../firmware/lib/sleep_core/include/radar_client.h#L18)

## 2. 可复用字段与不能混用的语义

现有日志序列化定义集中在 [main.cpp L209](../../firmware/src/main.cpp#L209)。网络接入应从内部快照与质量结果生成，避免解析自己的 USB 文本。

| 现有字段 | 类型 / 单位 | 平台使用规则 |
|---|---|---|
| `version` | 固件版本字符串，当前宏值 `0.2.0` | 展示、联调追溯；不是设备身份 |
| `t_ms` | 本次开机累计毫秒，uint64 | 非日期时间；重启重新开始，不直接推算跨重启时长 |
| `clock_ms` | 回绕的 uint32 `millis()` | 内部相对时钟；不能用作 UTC 或平台消息序号 |
| `ready` / `client_state` | 布尔 / 0–5 | 握手与客户端状态；不代表链路、字段均健康 |
| `installation_confirmed` | 布尔 | 现场操作员确认，不是设备自动检测安装合格 |
| `transport_ok` / `fault_generation` | 布尔 / uint32 代次 | 传输健康与故障边界；代次会回绕，不是故障发生时间或稳定事件 ID |
| `presence` / `bed` | `raw` 为 0/1；各有 `available/valid/reason/age_ms` | 两者有效且均为 1 才是“有效在床观察”；任一无效或 `presence=0, bed=1` 为 unknown |
| `rr` / `hr` | 原值保存在整数中，单位均为次/分钟；各有独立质量和年龄 | `valid=false` 不显示为有效生命体征；不将 0、255、缺失或超量程翻译为疾病事件 |
| `low_motion` | `raw` 是转换后的 0/1，另有 `available/valid` | 1 表示静止；不是厂商 0/1/2 原始枚举。厂商“无信息”和“活动”都会变为 raw=0，须看 available 区分 |
| `vendor_stage` | 模组枚举与 `available/valid` | MVP 不展示临床睡眠分期，不据此生成深睡时长、评分或医疗报告 |
| `trend` | 60 个一秒桶的有效观测中位数、有效桶数 | 是滚动窗口；不可再对多个窗口中位数求中位数冒充整夜统计。不可把 `valid_buckets/60` 当持续有效时间占比 |
| `ambient` | `known/dark/calibrated` 布尔、`estimated_lux` 数值或 null | 未校准、故障或无新读数时未知；估计 lux 不是整机标定照度 |
| `lamp` | `mode=auto/manual`，`pwm/target` 为 0–255 | 反映本机灯状态；亮灯不等于发生了一次离床事件 |
| `parser` / `last_command` | 累计诊断计数 / 最近命令结果字符串 | 诊断用途；`last_command` 会重复出现在后续日志，不能当离散事件去计数 |

`available` 表示当前缓存是否可用；`valid` 是更严格的业务质量门控结果。`age_ms` 是 MCU 接受该字段响应后经过的时间，不证明雷达内部重新采样的时刻；字段不可用时现有日志会输出 `age_ms=0`，这个 0 不能被解释为刚收到数据。[时间年龄输出](../../firmware/src/main.cpp#L195)、[字段更新](../../firmware/lib/sleep_core/src/radar_client.cpp#L225)

当前规则：字段超过 5000 ms 为过期；RR 只接受 10–25、HR 只接受 60–100，且需要安装确认、链路健康、有效有人在床和静止。量程是本固件采用的模组工程量程，**不是老人正常值、异常告警阈值或诊断范围**。RR/HR 的 0、255 被主机当成缺失值处理，不声称它们是厂商定义的医学编码。[质量规则](../../firmware/lib/sleep_core/src/monitor_logic.cpp#L17)、[量程](../../firmware/lib/sleep_core/src/monitor_logic.cpp#L75)

现有 `reason` 字符串：`ok`、`missing`、`stale`、`transport_fault`、`installation_unconfirmed`、`invalid_value`、`out_of_range`、`occupancy_unknown`、`not_present`、`not_in_bed`、`motion_unknown`、`motion`、`conflicting_occupancy`；兜底值为 `unknown`。网络规范如采用更小的质量分类，应保留这些原因供诊断，不能把 unknown 映射为离床。[序列化映射](../../firmware/src/main.cpp#L51)

## 3. 最小联网改造范围

目标是在保留本机查询、质量门控、按键和夜灯的基础上，增加主动 HTTPS 上报。首版不引入 MQTT、常驻网关、远程命令、OTA 或历史补传。接口、类型和时间约束以[设备接入契约](device_protocol.md)及 [telemetry.schema.json](../contracts/telemetry.schema.json) 为唯一依据；这是下一次固件迭代的需求，V0.2.0 发布文件保持原样。

1. **拆出与 USB 无关的状态快照。** 从 `radar.snapshot()`、`evaluate()`、趋势、灯和诊断对象取不可变副本；USB 日志与网络上传分别消费，关闭串口监视器不影响联网。新增联网代码不得在 `queueLog()` 的 `if (!Serial)` 之后挂接。
2. **补充稳定身份与开机边界。** 配置持久的 `device_id` UUID、`binding_id` UUID 或 null、服务器地址、每台独立凭证；`boot_id` 改用拟开发的 NVS 持久启动计数，范围 1–4294967295；每次 MCU 启动加 1，成功提交并回读一致后才允许联网。`seq` 在单次开机内严格递增。版本、MAC、IP、房号均不能代替授权身份；换床关系由服务端管理，设备只携带不含个人信息的绑定编号，不上传老人姓名或房号。`uptime_ms` 取现有累计时钟，但线上限制为不超过 `2^53−1` 的非负整数；`seq` 最大 `2^32−1`，不得在同一 boot 内回绕复用，耗尽时停止上报并安排受控重启。已有设备的启动计数损坏、缺失、清除 NVS 或计数耗尽时必须停止上传；重新登记新 `device_id` UUID 并归档旧 Device，不能在旧身份下从 1 重新计数。
3. **隔离网络阻塞。** 用一个固定容量的最新快照槽和独立联网任务；主采集循环只复制数据。DNS、TLS、HTTP 超时与断网重连不得阻塞 UART 解析、100 ms 帧间超时处理、按键或灯的渐变。首版不建持久上传队列，恢复后按契约发送新快照。
4. **建立可信 HTTPS 和 UTC。** 发送前完成 SNTP 可信时间准备；快照采集时写入 `captured_at`（UTC、RFC3339、`Z` 后缀），不使用发送重试时刻覆盖它。没有可信 UTC 则不上报，并在本地记录时钟故障。校验服务端证书和主机名，证书/时钟出错时保留本机功能，禁止以 `setInsecure` 或关闭校验解决。凭证写入设备专用配置，不放入串口日志、示例文件或 Git；首次配置采用受控 USB 工具，不增手机配网应用。
5. **增加必要诊断。** 暴露联网是否已配置、最近上报结果和失败次数用于本地排错；服务端以接收记录判断平台在线状态，并与 `transport_ok` 的雷达链路状态分开。Wi-Fi 连通不等于雷达可用。

ESP32C3 的 Flash/RAM、TLS 握手峰值及任务并发尚未在该固件上实测。保留当前固定版本构建先做最小增量，不把“大版本升级框架”列为接入前置，也不宣称现有二进制已经具备上述能力。

### P0 上报映射

每 10 秒生成一次新快照，使用 `HTTPS POST /api/device/v1/telemetry`；最多一个请求在途、一个最新待发快照。`sample` 仅含 `radar_enabled`、`ready`、`installation_confirmed`、`transport_ok`、`presence`、`bed`、`rr`、`hr`、`low_motion` 和 `lamp`。`radar_enabled` 是新增序列化字段，取实际 UART 启用标志（`uart_enabled` / 对应客户端 `enabled()`），不能由 `ready` 推断。其余四个完整字段沿用 `raw/available/valid/reason/age_ms`；`low_motion` 沿用三属性结构。`firmware_version` 对应现有 `version` 宏。`vendor_stage`、`trend`、`ambient`、`parser`、`last_command` 不进入 P0 网络载荷，本地诊断继续保留。

采集时用同一时刻的 `TimedField` 计算年龄并运行 `evaluate()`，因此 10 秒上报周期不会把 5 秒新鲜度阈值扩大到 10 秒。服务端只接受 `captured_at` 在接收时刻前 20 秒至后 5 秒内的包，并执行设备级时间、持久 boot 顺序及同 boot 序号规则；过期/旧包不覆盖当前值。固定 5 秒是采集时质量窗口，平台显示的是带采集时间的最近观测，30 秒后快照失效，60 秒没有新鲜唯一报告判离线；不能把页面轮询展示当实时生命体征报警。

### 换床、换人和未绑定诊断

每次床位或住户绑定都生成不可变的新 `binding_id`，设备上传值必须与服务端 `Device.active_binding` 完全相同。变更时依次现场停止测量、在保持Device.enabled=true的换绑事务中关闭旧 Binding、新建 Binding、轮换设备 token，再由现场工具写入新 `binding_id` 和 token 并重启。重启清空待发快照、提交递增后的 boot 计数、重置现场启用与确认状态，不能把上一住户的缓存带入新绑定。

未绑定诊断仅在两端绑定均为 null 时接受，不进入任何住户趋势。新绑定最初 5 秒隔离，不接收入住数据；服务端要求 `captured_at >= binding.started_at + 5s`，按契约覆盖允许的 ±5 秒时钟误差边界。旧 token 返回 401，绑定不匹配返回 409；设备在本地提示现场重新配置，不能自行猜测新绑定或凭旧凭证继续上传。上报接口不下发远程绑定配置、雷达启用或安装确认。

以下是按契约构造的合成例，非实测；身份和采集时刻为文档占位，原样重放会因身份或时间规则被拒绝。

```json
{
  "schema_version": 1,
  "device_id": "4b9635de-4522-4fd1-8a6b-5eb3e4adba53",
  "binding_id": "5adf1692-09c4-4b8c-8e71-d06cd72a9a54",
  "boot_id": 7,
  "seq": 12,
  "captured_at": "2026-11-04T22:00:00Z",
  "uptime_ms": 120000,
  "firmware_version": "0.3.0-dev",
  "sample": {
    "radar_enabled": true,
    "ready": true,
    "installation_confirmed": true,
    "transport_ok": true,
    "presence": {"raw": 1, "available": true, "valid": true, "reason": "ok", "age_ms": 200},
    "bed": {"raw": 1, "available": true, "valid": true, "reason": "ok", "age_ms": 180},
    "rr": {"raw": 16, "available": true, "valid": true, "reason": "ok", "age_ms": 120},
    "hr": {"raw": 70, "available": true, "valid": true, "reason": "ok", "age_ms": 20},
    "low_motion": {"raw": 1, "available": true, "valid": true},
    "lamp": {"mode": "auto", "pwm": 0, "target": 0}
  }
}
```

`0.3.0-dev` 只是示例开发标签，不表示已有该版本发布。真实上传代码、设备身份初始化、持久启动计数、SNTP、证书配置和 HTTPS 任务均未实现。

## 4. 上电与现场确认仍是部署前提

PCB V0.2 没有雷达供电检测。`radar on` 只启用 UART，不控制雷达电源；`radar off` 只将通信引脚置高阻。当前上电默认关闭 UART，`install yes` 和 `ambient yes` 确认仅保存在内存中，重启后需现场重新确认。[UART 控制](../../firmware/src/main.cpp#L90)、[命令](../../firmware/src/main.cpp#L149)、[PCB 上电要求](../../pcb/release_v02/README_交付与装配.md)

因此首版平台应能接收到“设备在线，但待现场启用/安装未确认”的状态；不得以平台注册成功、床位已绑定、重启恢复联网来自动执行这些确认。P0不上传ambient，光照校准与未知状态仍在本机检查，不能声称平台页面已显示该项。短期只承诺有人值守的小规模试点。若要院内无人值守断电自恢复，需先另行完成供电检测/隔离与启动策略验证，不能只改成开机 `radar on`。

设备 USB 调试仍遵循外部 5 V 断开、JP1/JP2/JP3 全部拔下的既有要求；接口开发不改变这些装配约束。

## 5. 联调与验收

| 验收场景 | 必须观察到的结果 |
|---|---|
| 模拟多设备上报 | 每台凭证只对应本设备；接入契约的去重、顺序和错误返回得到覆盖，合成数据明确标记 |
| 没有串口监视器 | 新快照及上传持续工作，本地日志输出是否连接不改变采集状态 |
| DNS/TLS/HTTP 超时、断网和慢服务器 | 采集、帧解析、按键及夜灯继续运行；任务/队列内存有上限；恢复后不把缓存旧值伪装成当前测量 |
| 缺失与无效测量 | 0、255、过期、活动、安装未确认、串口故障均显示明确不可用状态，未知不变成离床 |
| 重启与时钟边界 | boot 计数持久递增，序号按契约重置；`clock_ms` 回绕不破坏本机算法；即使 UTC 有允许范围内偏差，旧 boot 也不能覆盖新 boot 当前状态 |
| 启动计数原子持久化故障 | 在 NVS 写入前、提交中、提交后与首包前断电；未成功持久化不得联网，重启不得复用已上报的 boot。模拟写失败、回读不一致、计数丢失、NVS 清除及达到上限，均停止上传并要求新身份登记，不能默默归零 |
| 重启后网络先恢复 | 平台显示在线但雷达待现场启用，三个现场确认不会从服务端自动恢复 |
| 配置与撤销 | 无凭证设备无法写数据；撤销后拒绝上传；日志不出现设备密钥；配置变更不写进健康数据 |
| 换床、换人及未绑定 | 旧 token 被拒绝，错 binding 返回 409；现场更新并重启后才接入新绑定；新绑定前 5 秒隔离；两端 null 的诊断不进入住户趋势 |
| 实机基线对比 | 联网开启/关闭分别记录 UART 错误、有效数据比例、按键响应和灯控，确认上传没有引入采集阻塞；这是后续待做的实机验收 |

保留现有原生与 mock 回归测试，并新增网络接口模拟测试；编译成功、模拟通过与真实机构网络试点分别记录。

现有 `summarize_log.py` 只对相邻间隔不超过 2000 ms 的本地日志积分，不能直接用于每 10 秒的平台快照。[离线时间规则](../../firmware/docs/logs.md)、[积分上限](../../firmware/tools/summarize_log.py#L11)。首版平台记录采样点与数据可用性，不据此推出连续整夜时长、真实离床次数或临床睡眠评分。`fixtures/demo_synthetic.jsonl` 专用于离线摘要测试，其中某些不参与摘要的字段并不符合真实固件组合；不要原封不动作为联网协议正常案例。
