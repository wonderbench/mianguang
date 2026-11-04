# RadarClient 查询调度与字段解码

`sleep_radar::RadarClient` 使用 `c1001_protocol.h` 的 `Frame` 和 `monitor_logic.h` 的 `sleep_core::SensorSnapshot`。它不依赖 Arduino、串口实现、线程、堆内存或阻塞等待。字节解析仍由已有 `Parser` 执行。

## 调用接口

```cpp
sleep_radar::RadarClient client;
client.reset(now_ms);                       // 启动十秒等待；保留配置和安装确认
client.setInstallationConfirmed(confirmed);
client.setEnabled(enabled, now_ms);

client.tick(now_ms);                        // 即使没有接收数据也持续调用
client.accept(validated_frame, now_ms);     // 只传入 Parser 完整校验通过的帧
sleep_radar::Frame outgoing;
if (client.poll(now_ms, outgoing)) {
    // encodeFrame() 后立即完整写入串口；写入失败调用 notifyTransportFault()
}

const auto& sample = client.snapshot();
const auto generation = client.faultGeneration();
```

`poll()` 返回 true 即将请求视为已发送并开始响应计时。不能把返回帧长时间留在待发送队列；若编码、串口写入或硬件发送失败，调用 `notifyTransportFault(now_ms)`。`poll(false)` 不修改输出帧。`accept()` 返回 false 表示该帧没有作为当前查询的正确响应被接受；返回 true 可能是正常数据，也可能是已确认的“无信息”测量状态，必须继续看字段的 `available`。

`enabled()`、`ready()`、`pending()`、`state()` 提供当前状态。`ready()` 表示本次握手确认过睡眠工作模式；单次查询故障可能保持该模式状态，因此它不能代替 `snapshot().transport_ok` 或字段质量检查。

## 启动、模式与周期查询

1. 初始化后先等待 10000 ms。显式 `reset(now)` 决定等待起点；没有调用 reset 时，从首次 `tick/poll/accept` 调用开始等待。
2. 发出 `02/A8`、payload `0F` 查询工作模式。只接受相同 control/command、长度恰为 1、值为 1 或 2 的响应。
3. 值为 2 时开始周期查询；值为 1 时发出 `02/08`、payload `02`，然后重新等待 10000 ms，再查询 `02/A8`。不使用设置命令的 ACK 证明模式已切换。若仍为 1，重复设置与等待；未知模式值拒绝并重试查询。
4. 按固定顺序查询 presence、motion、in-bed、RR、HR、stage，循环执行。任何时刻最多有一个未完成查询。

这些命令及十秒等待来自本地官方库 `research/vendor_library/DFRobot_HumanDetection.cpp` 的 `configWorkMode()`。该客户端不调用官方示例中的 LED 配置或额外复位命令。

| `ClientConfig` | 默认值 | 含义 |
|---|---|---|
| `enabled` | `true` | 是否启用；硬件尚未接入时可设置 false |
| `response_timeout_ms` | 500 | 从 `poll(true)` 起等待对应查询响应的最长时间 |
| `query_interval_ms` | 100 | 响应完成或失败后，到下一次发送的最小间隔 |
| `link_timeout_ms` | 5000 | 运行态距离上次已接受响应的最长间隔 |
| `max_consecutive_timeouts` | 3 | 达到此数量的连续查询超时或格式/值域错误后重新确认工作模式 |

这些是主机工程默认值，尚未由 C1001 实机更新周期验证。三个时间参数限制在 1 至 `0x7FFFFFFF` ms，重试阈值最低为 1。所有时间均使用同一单调回绕 `uint32_t` 毫秒时钟和无符号差值；包括启动等待、查询间隔、模式切换等待及超时，都支持跨回绕。

## 已核实的解码

control/command 对照本地官方库；枚举值补充核对于 2026-10-28 的[人体存在、呼吸与心率官方示例](https://wiki.dfrobot.com/sen0623/docs/21573)及[睡眠信息官方示例](https://wiki.dfrobot.com/sen0623/docs/21572)。示例确认 presence 0/1、motion 0/1/2、in-bed 0/1，以及 stage 0/1/2/3 的含义。

| 查询地址 | Snapshot 字段 | 接收与映射规则 |
|---|---|---|
| `80/81` | `presence` | 0→false、1→true；其他值拒绝 |
| `80/82` | `low_motion` | 1 静止→true；2 活动→false；0 无信息→available=false；其他值拒绝 |
| `84/81` | `in_bed` | 0 离床→false、1 在床→true；其他值拒绝 |
| `81/82` | `respiration_bpm` | 保留原始一字节数值；0、255→available=false |
| `85/82` | `heart_bpm` | 保留原始一字节数值；0、255→available=false |
| `84/82` | `module_sleep_stage` | 保留 0 深睡、1 浅睡、2 清醒；3 无→available=false；其他值拒绝 |

所有查询要求响应长度恰为 1；不会接受只有最低 command 位相同的帧，也不会把未请求的自动上报或其他查询的响应刷新进缓存。成功响应只更新对应字段及其时间戳；其它字段时间戳保持不变。stage=3 始终不可作为睡眠证据。

RR/HR 的 0、255 过滤是主机缺失值策略，不能据此断言某个数值具有厂家定义的疾病或故障含义。其他超出标称量程的原始数值保留，由已有 `evaluate()` 按呼吸 10–25、心率 60–100 做量程门控，并继续检查安装、有人、在床、体动和各字段新鲜度。

“设备正常回应，但没有生命体征/睡眠信息”不等于通信断开。因此已知 motion=0、stage=3、RR/HR=0或255仅使相应字段不可用，不清空其它占用字段，也不增加故障代次；否则正常离床时的无生命体征会不断打断夜灯的离床确认。

## 故障、恢复与夜灯连续性

每次查询超时、当前响应长度或枚举非法、显式串口/解析故障、失联、reset、启停切换，都会使全部字段 `available=false`、`transport_ok=false`，并增加 `faultGeneration()`。数值和原始时间戳可继续用于诊断，但不能视为新测量。重新接受合法响应可以恢复链路状态，但只恢复本次供应的字段；模式确认响应不会恢复旧字段。

单次查询失败按间隔重试同一字段；连续失败达到阈值后改为 `02/A8` 握手，再从 presence 开始。失联和显式传输故障也重新确认模式。重复调用 tick 不会为同一个已处理故障反复增加代次。启用 false 时取消未完成请求并停止发送；重新启用必须重新经过十秒等待和模式确认。安装确认的变化会清除缓存字段并增加故障代次，以中断旧的安装条件下的占用连续性，但不将其误报为串口断开。

主循环应保存上次已处理的 `faultGeneration()`，每次处理串口数据和 tick 后比较。只要发生变化，先取消夜灯的待确认离床过程，再使用当前样本继续计算；不能仅检查本轮结束时的 transport_ok，因为同一轮可能先出现解析错误又接受合法响应。仅使用 `!=` 比较代次，无需进行大小排序，可跨计数器回绕。

`Parser` 的 checksum、尾、长度和超时计数出现新错误时，应由串口适配层调用 `notifyTransportFault()`。该客户端不会自行读取 Parser 统计，也不会猜测串口是否写入成功。应用重启客户端时应一并重置 Parser，避免旧的部分帧跨越重启边界。

协议没有事务序号；严格地址匹配可以拒绝其它查询和未请求帧，但在相同查询重试期间到达的旧响应与新响应无法仅凭该帧区分。现有时间戳表示主机接受响应的时间，不证明传感器内部重新采样时间。这项限制需通过实机串口时序和测量新鲜度验证。

## 验证

独立原生测试覆盖启动等待、模式切换并重新确认、单未完成请求、查询顺序、错误地址/低位 command/重复帧拒绝、精确超时边界、连续丢包与握手恢复、失联、各字段枚举/长度检查、无信息值、stage=3、启停/reset、安装确认、固定对象大小及跨毫秒回绕。

`firmware/tests/test_pipeline.cpp` 另以编码后的请求/响应经过两个 Parser 模拟串口两端，串联 RadarClient、质量门控、趋势和夜灯。测试覆盖静止在床到暗环境离床、坏 checksum 后紧接完整帧、失联恢复，以及消费层在同一处理批结束时只看到健康快照的情况；故障代次提前向夜灯传入未知输入，确保此前未满三秒的离床过程不能跨故障继续累计。测试中的未消费故障事件的对照灯会提前开启，用来确认该断言实际覆盖了所防止的问题。各场景使用不到三十秒的模拟时钟，无真实等待。

```sh
clang++ -std=c++17 -Wall -Wextra -Wpedantic -Werror \
  -fsanitize=address,undefined -fno-omit-frame-pointer \
  -I firmware/lib/sleep_core/include \
  firmware/lib/sleep_core/src/c1001_protocol.cpp \
  firmware/lib/sleep_core/src/monitor_logic.cpp \
  firmware/lib/sleep_core/src/radar_client.cpp \
  firmware/tests/test_client.cpp -o /tmp/radar_client_test
/tmp/radar_client_test
```

将上述编译命令的 `firmware/tests/test_client.cpp` 换为 `firmware/tests/test_pipeline.cpp` 即可运行串口到夜灯的贯通测试。

这验证主机调度和解码行为；实际串口、供电、波束覆盖与传感器测量仍需实机验证。
