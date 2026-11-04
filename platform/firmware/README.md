# 最小联网固件与 USB 配置

本目录放置平台联网代码；现有雷达、质量规则、按键和夜灯仍在 `firmware/`。上报契约见[设备协议](../docs/device_protocol.md)，硬件接线与现场前提见[固件接入说明](../docs/firmware_integration.md)。构建、host 模拟和真实设备验收分别记录，**本仓库中的工具和示例不代表三台设备已完成 24 小时实测**。

## 构建与运行边界

保持原 `xiao_esp32c3` 默认环境及 V0.2 发布包。新联网环境单独标记 `0.3.0-dev`，使用同一 espressif32 6.12.0 / Arduino 2.0.17 框架锁定，不引入 MQTT、OTA 或远程控制。

```sh
python -m pip install platformio==6.1.19 pyserial==3.5
pio run -d firmware -e xiao_esp32c3 -e xiao_esp32c3_platform
# 完成下述硬件接线检查后，在受控USB端口刷写开发版：
pio run -d firmware -e xiao_esp32c3_platform -t upload --upload-port /dev/ttyACM0
```

`network_core.cpp` 保存不可变快照及序列化；主循环每10秒复制一次，首次周期带0–2秒错峰，不依赖USB是否连接。`platform_network.cpp` 的独立任务持有一个在途快照和一个最新待发槽，按当前雷达质量结果生成载荷；断网不积压Flash历史。重试沿用原载荷，较新快照覆盖旧待发，超过15秒的快照不再启动请求，为服务端20秒窗口保留请求预算。

`platform_http.cpp` 使用异步DNS、非阻塞TLS及SDK HTTP解析器；所有阶段共享5秒请求期限，校验证书链、原主机名与SNI。TLS连接和响应正常释放，响应体最多512字节；不跟随重定向。429、5xx和网络失败按1/2/4/8秒递增至30秒并加有界抖动，支持不超过30秒的数字 `Retry-After`。401、403或绑定不匹配会停发，等待现场重配。

首次成功SNTP回调后才允许采集UTC；来源由配置的 `ntp_server` 决定，`utc_trusted` 表示已同步且处于可用日期范围，不代表SNTP本身提供加密认证。时钟回退或服务端拒绝时间窗口时停止使用旧时间并请求重新同步，绝不改写旧快照时间。

固件CI复用原生/主循环/日志回归，另用实际序列化结果调用现有服务端契约校验，并验证受控USB配置流程；构建产物以开发版artifact提供。构建报告的静态RAM不包含Wi-Fi、TLS与任务运行期峰值，现场应记录 `net status` 的堆/栈最低余量。完整实机断电、无线网络和灯控时序仍按[现场记录](../docs/field_trial.md)执行。

## 受控配置

先在平台登记设备，取得该设备的 UUID、独立 token 和当前 `binding_id`；未绑定诊断使用 null。准备可校验服务器证书链的 CA PEM。端点是完整的 `https://<host>/api/device/v1/telemetry`，不是只含主机的 origin，不允许 HTTP、重定向或关闭证书校验。

USB 调试须先断开外部 5 V，并拔下 JP1/JP2/JP3；配置操作不会改变既有接线要求。关闭串口监视器，显式指定端口。脚本需要 Python 3 和 `pyserial==3.5`，不会探测或自动选择设备。

```sh
python platform/tools/provision_device.py --port /dev/ttyACM0 --ca /private/server-ca.pem --new-identity
```

此命令交互输入设备配置，token 与 Wi-Fi 密码使用隐藏输入。`--new-identity` 表示已经在平台**重新登记的新 UUID**，也用于全新设备首次配置；不能用它在原 UUID 下重建启动计数。脚本只发送 `net status`、`radar off` 和 `net configure`，等待本地雷达关闭确认后才写入配置。它不会执行 `radar on`、安装确认或光照确认。

批量现场操作可使用权限为 `0600` 的独立 JSON 文件；不要将秘密放入命令行、Git、工单或共享日志。JSON 字段为 `device_id`、`binding_id`、`endpoint`、`token`、`wifi_ssid`、`wifi_password`、`ntp_server`、`ca_pem`。使用 `--ca` 时可省略文件内的 `ca_pem`，脚本从 PEM 文件填入。`new_identity` 由命令行开关显式生成，不放入配置文件。

```sh
chmod 600 /private/device.json
python platform/tools/provision_device.py --config /private/device.json --ca /private/server-ca.pem --check
python platform/tools/provision_device.py --port /dev/ttyACM0 --config /private/device.json --ca /private/server-ca.pem
```

`--check` 仅检查输入与线路长度，不打开串口，不能证明证书、Wi-Fi、NVS 或平台注册成功。成功发送后，固件先保存配置，再返回无密钥确认并自动重启；脚本的成功只表示收到了这个确认，随后仍需检查 `net status` 与平台实际接收记录。USB 中断或最终确认缺失时，先检查设备状态再决定是否重试。脚本不打印配置、原始串口文本或设备返回的任意错误内容。

### 配置上限

| 字段 | 约束 |
|---|---|
| `device_id` / `binding_id` | 36 字符 UUID；`binding_id` 可为 null |
| `endpoint` | 完整 HTTPS URL，最多 192 字节，路径固定为 `/api/device/v1/telemetry` |
| `token` | 平台签发的 43 字符 base64url token |
| `wifi_ssid` / `wifi_password` | 最多 32 / 64 个 UTF-8 字节；开放网络密码为空字符串 |
| `ntp_server` | DNS / IPv4 主机，最多 128 字节 |
| `ca_pem` | 信任的 CA PEM，最多 4096 字节 |

## USB 协议

串口为 115200，ASCII 单行，以 LF 结束。配置行最多 8191 字节（不含 LF）。JSON 使用 ASCII 转义，中文 SSID 通过 `\uXXXX` 发送，再由固件还原为 UTF-8。下面是字段示意，尖括号内容必须由现场真实登记值替换，不能原样发送。

```text
net status
net configure {"device_id":"<UUID>","binding_id":null,"endpoint":"https://<host>/api/device/v1/telemetry","token":"<43-character-token>","wifi_ssid":"<SSID>","wifi_password":"<password>","ntp_server":"pool.ntp.org","ca_pem":"<PEM>","new_identity":false}
```

所有联网回复为单行 JSON，`type` 固定为 `network`。`net status` 返回 `status="status"` 及无密钥诊断；配置可先返回 `status="configuring"`。成功行固定为：

```json
{"type":"network","status":"configured","restarting":true}
```

失败使用 `status="config_error"` 和固定原因码。回复不回读 token、Wi-Fi 密码、CA 或完整配置。命令仅在雷达 UART 关闭时接受；不能通过这个接口下发启用或安装确认。成功配置后停止旧身份上传并自动重启；重启后的雷达启用、安装、光照确认仍由现场人员分别完成。

## 换绑、凭证轮换与身份故障

同一设备更换绑定或 token：现场先停止测量，在平台完成换绑并轮换 token，然后用**同一 `device_id`**、新 `binding_id` / token 配置，不传 `--new-identity`。保留 NVS 启动计数，重启递增并清空待发快照与内存确认。平台对新绑定执行 5 秒隔离；不要因暂未接受样本而重复登记设备。

已有身份的 boot 计数缺失、损坏、无法提交、回读不一致或耗尽时，停止上传，不允许把原身份从 1 重新开始。归档旧 Device，在平台登记新的 UUID 与凭证，再用 `--new-identity` 配置。**不要通过擦除 NVS 来恢复旧 UUID。** 完整 Flash / NVS 擦除会同时丢失身份与计数，设备无法自行识别曾用身份；操作者仍必须执行新的平台注册流程。工具不会执行 Flash 擦除，也不会替操作者创建或归档平台 Device。

现场 24 小时记录与未执行项目见[验收记录说明](../docs/field_trial.md)。
