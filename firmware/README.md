# 眠光 V0.2 固件与验证

目标板为 **Seeed XIAO ESP32C3**，雷达为 **DFRobot C1001 SEN0623**。样机固件已完成目标板编译：独立协议解析、睡眠模式查询、数据质量门控、呼吸/心率趋势、夜灯控制和本地日志。测试与实机验证分开记录；当前没有上传到开发板，也没有雷达实测结果。

[固件源码](src/) · [构建产物说明](releases/v0.2.0/README.md) · [验证记录](reports/VERIFICATION.md)

## 实现范围

- 固定容量接收缓冲，核验帧头、长度、校验和、帧尾、字节超时；拒绝未知查询响应，不把失败解释成离床。
- 启动等待 10 秒，查询并确认睡眠模式；需要切换时再次等待 10 秒。6 个字段顺序查询，单请求在途，默认每次响应后间隔 100 ms、响应期限 500 ms。周期受实际响应速度影响，不保证 1 Hz。
- 字段独立时间戳，默认新鲜度 5 秒。呼吸仅接纳 10–25 次/分钟、心率 60–100 次/分钟，且安装、在床、存在、静止和通信同时有效。这些是采用模组的标称量程，不是健康判定阈值。
- 60 个一秒桶统计有效观测中位数及覆盖率；不以缓存数据填补缺口，不输出临床睡眠分期或疾病报警。
- 自动灯：先有效在床，再有连续 3 秒、持续更新的离床证据；照度已确认且暗才亮。默认 1 秒渐亮、事件后 60 秒开始渐灭。手动照明独立可用。
- 支持选装 BH1750（地址 `0x23`）环境光模块；5/10 估计 lux 滞回阈值需通过外壳后的实测确认。未接入、故障或未确认时环境为 unknown。
- 每秒输出 JSONL，包含独立有效标记、错误原因、数据年龄、趋势、通信统计和灯状态。Wi-Fi、蓝牙及云上传均未启用。

## 引脚与连接

| XIAO 引脚 | GPIO | 用途 |
|---|---:|---|
| D6 | 21 | TX → C1001 RX，板上串联 100 Ω |
| D7 | 20 | RX ← C1001 TX，板上串联 100 Ω |
| D2 | 4 | 20 kHz、8 位 PWM → MOSFET 控制带限流灯板 |
| D1 | 3 | 低有效按键，板上 10 kΩ 上拉与 100 nF |
| D4 / D5 | 6 / 7 | BH1750 SDA/SCL；上拉只接 3.3 V |

雷达使用 5 V 供电与共地；UART 电平在接线前实测确认。夜灯必须使用 **5 V 自带限流灯板，目标不超过 0.5 W**，不要把裸 LED 直接接入。BH1750 板外模块按 3.3 V 接口选择，不能向 I²C 引脚上拉到 5 V。

V0.2 载板没有雷达电源检测。固件上电时 UART TX/RX 设为高阻，必须确认雷达真实供电后执行 `radar on`；拔掉雷达电源前执行 `radar off`。这两条命令只控制通信引脚，不能开关实际电源，也不能自动发现突然掉电。

编程前断开外部 5 V，取下 JP1、JP2 和 JP3；所有跳线都只在两路电源断开后切换。JP1断开主控外供电支路，JP2/JP3分别断开两条UART线。外供电与电脑USB受控联调时JP1保持拔下、JP2/JP3装上，两路电源稳定后再执行 `radar on`。完整接线与上电步骤见[PCB V0.2交付说明](../pcb/release_v02/README_交付与装配.md)。

## 编译与测试

项目使用 PlatformIO Core 6.1.18、Espressif32 平台 6.12.0、Arduino ESP32 2.0.17、C++17。无需启动 EDA 或 Arduino 编辑器。

从项目根目录运行：

```sh
python3 -m venv .tooling/pio
.tooling/pio/bin/python -m pip install platformio==6.1.18
.tooling/pio/bin/pio run -d firmware
python3 firmware/tools/run_native_tests.py
python3 firmware/tests/run_main_mock.py
python3 -m unittest discover -s firmware/tests -p 'test_*.py'
```

编译输出位于 `firmware/.pio/build/xiao_esp32c3/`，发布副本及校验在 `firmware/releases/`；[验证记录](reports/VERIFICATION.md)区分软件通过项与实机待测项。烧录用显式端口（需要实物接入与电源检查）：

```sh
.tooling/pio/bin/pio run -d firmware -t upload --upload-port /dev/cu.usbmodem实际端口
.tooling/pio/bin/pio device monitor -d firmware --port /dev/cu.usbmodem实际端口
```

上述端口为占位文字，不能原样使用。固件编译通过不表示已烧录、实机通信通过或医疗有效性得到验证。

## 串口命令与按键

命令以换行结束、全小写。确认只保存在内存中，重新上电后需重新确认。

| 命令 | 行为 |
|---|---|
| `radar on` / `radar off` | 确认有电后启用 / 将雷达 UART 引脚置高阻 |
| `install yes` / `install no` | 确认 / 撤销实际安装位置、角度、距离验证 |
| `ambient yes` / `ambient no` | 确认 / 撤销光传感器及整机阈值检查；随后还必须收到新光读数 |
| `light toggle` | 进入手动，切换开/关 |
| `light level` | 进入手动，循环 3 档亮度；灭灯时不会因此开灯 |
| `light auto` | 恢复自动并渐灭，重新等待有效在床 |
| `status` | 在下一条日志中记录状态请求 |

按键释放时识别动作：短按开关；按住 1.5–5 秒切亮度；按住至少 5 秒恢复自动。去抖 30 ms。上电时已被按住的按键需先释放，不会误执行动作。

`install yes` 只表示操作员确认，设备没有自动测量安装几何或多人数量。自动夜灯是辅助照明；未知、断连或无数据不能用作离床证据。关机时设置不写入 Flash，避免样机在移动后沿用错误安装结论。

## 本地记录与离线摘要

记录工具默认只监听，不主动启用雷达。明确供电、安装及环境光条件后才添加对应确认参数：

```sh
.tooling/pio/bin/python firmware/tools/capture_serial.py \
  --port /dev/cu.usbmodem实际端口 --output logs/night_001.jsonl \
  --confirm-powered --confirm-installation --confirm-ambient
```

Ctrl-C 停止；不会覆盖已有日志。使用 `.jsonl.gz` 后缀可压缩记录（摘要前先解压，或以摘要工具支持格式为准）。记录可能包含个人睡眠作息，请保存在使用者认可的位置。解析与统计说明见 [logs.md](docs/logs.md)。

## 验证边界与后续实机步骤

1. 在供电正常且不接灯负载时抓取模式查询与六字段原始帧，核对实际固件版本、枚举、时延及 UART 电平。当前测试帧由官方库规则构造，不是实机抓包。
2. 测按键、PWM、LED 限流与温升；再接灯测试雷达读数是否受干扰。
3. 测 BH1750 缺失、拔插、遮挡、自身夜灯照射和环境阈值；传感器位置或窗材改变后重新确认。
4. 测身体静止、翻身、离床、被褥、桌面/壁挂安装、断连恢复及整夜稳定性。覆盖率与误触发都要记录。
5. 与参考设备同步对照有效区间；不要从当前算法推导睡眠呼吸暂停、疾病报警或临床睡眠评分。

协议细节：[protocol_notes.md](docs/protocol_notes.md) · [client_notes.md](docs/client_notes.md)。算法口径：[logic_notes.md](docs/logic_notes.md)。主要来源：[DFRobot C1001 官方库](https://github.com/DFRobot/DFRobot_HumanDetection)、[睡眠字段示例](https://wiki.dfrobot.com/sen0623/docs/21572)、[存在/运动示例](https://wiki.dfrobot.com/sen0623/docs/21573)、[XIAO PlatformIO 配置](https://docs.platformio.org/en/latest/boards/espressif32/seeed_xiao_esp32c3.html)、[BH1750 开源驱动 1.3.0](https://github.com/claws/BH1750/tree/1.3.0)。BH1750 驱动核对了模式、测量时间与换算路径；估计 lux 仍需整机光学标定。
