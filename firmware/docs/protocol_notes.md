# C1001 协议核对与实现边界

本模块以仓库内保存的 DFRobot 官方库为核对依据：

- `research/vendor_library/DFRobot_HumanDetection.cpp`，文件头 V1.0、2024-06-03；帧收发见 `getData()`（第 783 行起），校验见 `sumData()`（第 929 行起）。
- `research/vendor_library/DFRobot_HumanDetection.h`，睡眠综合结构体从第 52 行、睡眠统计结构体从第 68 行开始。
- 上游来源：[DFRobot/DFRobot_HumanDetection](https://github.com/DFRobot/DFRobot_HumanDetection)。本文对本地快照负责，不声称该快照等于任何后续固件版本。

## 帧与查询

```text
53 59 control command lenHi lenLo payload... checksum 54 43
```

长度为大端 16 位数，仅计算 payload。总字节数为 `9 + length`。校验为从首字节 `53` 至 payload 最后一字节的累加和取低 8 位；不含 checksum 或帧尾。

官方查询函数使用一个字节的 `0F` 作为 payload。`query(control, command)` 原样保留传入的 control 和 command，生成 `length=1, payload[0]=0x0F`。调用者必须选用明确的查询 command；本函数不做 `command | 0x80`、清除高位或其他变换。

`getData()` 的 `CMD_CONFIG` / `CMD_CMD` 状态明确检查响应 control 和 command 与发送值相同。因此，官方库能够接收的心率查询响应为 `85/82`，不能根据习惯直接改成 `85/02`。源码没有独立的自动上报解码路径，不能据此证明所有低位 command 对应的自动上报语义。

独立校验示例：

```text
心率查询：53 59 85 82 00 01 0F C3 54 43
心率72示例响应：53 59 85 82 00 01 48 FC 54 43
```

以上响应是按官方接收规则构造的测试向量，并非实机串口抓包。

## 睡眠模式查询字段

下表“读取字节数”是官方函数实际读取的数据宽度，不等于源码验证了该响应总长度。上层解码必须自行验证 payload 长度。`u16 BE` 表示源码明确按高字节在前组装。

| 函数或字段 | control / command（查询及库接受的响应） | 读取字节数与读取方式 |
|---|---|---|
| `getWorkMode()` | `02 / A8` | 1；工作模式枚举：跌倒 `01`，睡眠 `02` |
| `smHumanData(eHumanPresence)` | `80 / 81` | 1；presence 原始值 |
| `smHumanData(eHumanMovement)` | `80 / 82` | 1；movement 原始值 |
| `smHumanData(eHumanMovingRange)` | `80 / 83` | 1；头文件注明范围 0–100 |
| `smHumanData(eHumanDistance)` | `80 / 84` | 2；u16 BE |
| `getHeartRate()` | `85 / 82` | 1 |
| `getBreatheState()` | `81 / 81` | 1；头文件注明 1 正常、2 过快、3 过慢、4 无呼吸 |
| `getBreatheValue()` | `81 / 82` | 1 |
| `eInOrNotInBed` | `84 / 81` | 1 |
| `eSleepState` | `84 / 82` | 1 |
| `eWakeDuration` | `84 / 83` | 2；u16 BE |
| `eLightsleep` | `84 / 84` | 2；u16 BE |
| `eDeepSleepDuration` | `84 / 85` | 2；u16 BE |
| `eSleepQuality` | `84 / 86` | 1 |
| `eReportingmode` | `84 / 8C` | 1 |
| `getSleepComposite()` | `84 / 8D` | 8；见下表 |
| `eSleepDisturbances` | `84 / 8E` | 1 |
| `getSleepStatistics()` | `84 / 8F` | 官方结构体复制存在歧义，见下文 |
| `eSleepQualityRating` | `84 / 90` | 1 |
| `eAbnormalStruggle` | `84 / 91` | 1 |
| `eUnattendedState` | `84 / 92` | 1 |
| `eAbnormalStruggleSwitch` | `84 / 93` | 1 |
| `eUnattendedSwitch` | `84 / 94` | 1 |
| `eUnattendedTime` | `84 / 95` | 1；不得与跌倒模式四字节无人计时混用 |
| `esleepDeadline` | `84 / 96` | 1 |

`getSleepComposite()` 对八个连续 `uint8_t` 成员进行复制，能确认以下顺序：

| payload 偏移 | 官方字段 | 头文件含义 |
|---|---|---|
| 0 | `presence` | presence 状态，源码未给出值域映射 |
| 1 | `sleepState` | 睡眠状态，源码未给出值域映射 |
| 2 | `averageRespiration` | 平均呼吸 |
| 3 | `averageHeartbeat` | 平均心率 |
| 4 | `turnoverNumber` | 翻身次数 |
| 5 | `largeBodyMove` | 大幅体动百分比 |
| 6 | `minorBodyMove` | 小幅体动百分比 |
| 7 | `apneaEvents` | 呼吸暂停事件数 |

源码不能单独证明 presence、在床或睡眠状态的数值映射、独立时长查询的单位、距离单位、心率/呼吸的无效值编码。不要把库函数自身的失败返回值（如 `0xFF`）认作传感器无效值协议。业务层应保留原始值，并将尚未核实的语义单独标注。

### 睡眠统计结构体不可直接当作线格式

`sSleepStatistics` 字段顺序为 `sleepQualityScore:uint8`、`sleepTime:uint16`、`wakeDuration:uint8`、`shallowSleepPercentage:uint8`、`deepSleepPercentage:uint8`、`timeOutOfBed:uint8`、`exitCount:uint8`、`turnOverCount:uint8`、`averageRespiration:uint8`、`averageHeartbeat:uint8`、`apneaEvents:uint8`。头文件将 `sleepTime` 注释为分钟。

这些成员的逻辑宽度合计 12 字节，但官方函数使用 `memcpy(..., sizeof(sSleepStatistics))`，未声明打包，也未显式处理 `uint16_t` 字节序。不同平台的结构体对齐可能让 `sizeof` 变成 14，不能据此确定传感器回包长度、每字段偏移或 `sleepTime` 的端序。本协议层只输出原始 payload；在取得明确协议说明或实际抓包前，不将该复制方法移植为跨平台解码器。

## 设置命令及其他已核对映射

以下是官方库中明确出现的写入命令，不能从查询 command 统一减 `0x80` 推导：

| 功能 | control / command | payload |
|---|---|---|
| 切换工作模式 | `02 / 08` | 1 字节；睡眠 `02`、跌倒 `01` |
| 复位 `sensorRet()` | `01 / 02` | `0F` |
| 人体存在 LED 设置 / 查询 | `01 / 03`、`01 / 83` | 设置 1 字节；查询 `0F` |
| 跌倒 LED 设置 / 查询 | `01 / 04`、`01 / 84` | 设置 1 字节；查询 `0F` |
| 睡眠上报模式设置 | `84 / 0F` | 1 字节；注意查询是 `84 / 8C` |
| 异常挣扎设置 | `84 / 13` | 1 字节 |
| 无人计时开关设置 | `84 / 14` | 1 字节 |
| 无人计时时间设置 | `84 / 15` | 1 字节 |
| 睡眠截止时间设置 | `84 / 16` | 1 字节 |

LED 枚举名对应的声明数字与实现中的 command 不是同一用途；应按函数分支核对。头文件对 LED 设置与查询状态的开关说明也不完全一致，不以其推断业务状态。`begin()` 实际查询 `01/83`，先等待 10 秒；工作模式切换和复位也有 10 秒等待。这些属于官方库的启动/事务策略，不是本解析器的字节间超时。

跌倒模式相关查询也逐项核对如下，供避免 command 混用；本模块不解释这些数据：

| 查询 | control / command | 官方读取宽度 |
|---|---|---|
| 安装角度 x/y/z | `06 / 81` | 6，三个 BE16 |
| 安装高度 | `06 / 82` | 2，BE16 |
| 自动测高 | `83 / 90` | 2，BE16 |
| 人体存在 / 运动 / 体动 | `80 / 81`、`80 / 82`、`80 / 83` | 各 1 |
| 轨迹开关 | `83 / 94` | 1 |
| 静止 / 运动水平距离 | `80 / 8D`、`80 / 8E` | 各 2，BE16 |
| 轨迹 x/y | `83 / 8E` | 4，两个 BE16 |
| 轨迹频率 | `83 / 93` | 4，BE32 |
| 无人计时 | `80 / 92` | 4，BE32 |
| 跌倒状态 | `83 / 81` | 1 |
| 跌倒高度 | `83 / 91` | 2，BE16 |
| 高度比开关 | `83 / 95` | 1 |
| 静态驻留状态 / 开关 | `83 / 85`、`83 / 8B` | 各 1 |
| 跌倒灵敏度 | `83 / 8D` | 1 |
| 跌倒时间 | `83 / 8C` | 4，BE32 |
| 静态驻留时间 | `83 / 8A` | 4，BE32 |
| 高度累计时间 | `83 / 8F` | 4，BE32 |

## 解析器行为

- 固定 `std::array` 容量：payload 上限 64 字节，线帧上限 73 字节。解析、编码及查询构造均无动态分配、无 Arduino 依赖。
- 只有长度、checksum 和两个尾字节全部有效时，`feed()` 才返回 `true` 并更新 `out`。其他情况保持调用方原有 `out` 不变。未知 control/command 仍是合法传输帧，其业务含义由上层判断。
- 传输层允许长度为 0；这不表示设备支持无 payload 查询。
- 异常长度在六字节头部齐备时立即拒绝。坏 checksum 或坏尾字节在可判断时立即拒绝，保留后缀重新寻找 `53 59`，包括重叠 `53 53 59` 和错误字节恰为下一帧 `53` 的情况。合法 payload 内的头尾字节序列不触发重新同步。
- `tick()` 和 `feed()` 均执行字节间超时检查。连续 100 ms 未收到下一字节即丢弃部分帧；这是一项主机实现参数，不是厂商规定的查询响应超时。上层仍须实现单独的查询响应期限、重试与数据新鲜度。
- 时间差使用 `uint32_t(now - last)`，支持 32 位毫秒时钟回绕；调用方应持续提供同一单调毫秒时钟，不能在间隔超过一次完整回绕后再期望恢复真实经过时间。
- `reset()` 仅清空接收状态，保留统计。需要清零全部诊断时可重新构造 `Parser`。
- `frames` 计数完整合法帧；`checksum_errors` 计数错误累加和；`framing_errors` 计数错误尾字节；`length_errors` 计数大于 64 的长度；`timeouts` 计数被超时放弃的部分帧。无效同步前缀和其他空闲噪声不增加错误计数。
- `encodeFrame()` 对过长 payload、空指针或不足的输出容量返回 0，且不改写输出缓冲区。

官方 `getData()` 没有对尾字节值进行检查，并包含接收循环和长度状态的特殊处理。此模块按帧格式校验，不复制这些行为。单元测试使用独立手算帧，覆盖分片、连续帧、噪声、重叠头、损坏恢复、合法 payload 内同步字节、零/最大/超限长度、100 ms 边界与时钟回绕；另逐一遍历 0–64 字节长度。

从项目根目录运行独立测试：

```sh
clang++ -std=c++17 -Wall -Wextra -Wpedantic -Werror \
  -fsanitize=address,undefined -fno-omit-frame-pointer \
  -I firmware/lib/sleep_core/include \
  firmware/lib/sleep_core/src/c1001_protocol.cpp \
  firmware/tests/test_protocol.cpp -o /tmp/c1001_protocol_test
/tmp/c1001_protocol_test
```

测试通过表示主机协议逻辑验证通过，不表示已经完成 C1001 实机串口联调。
