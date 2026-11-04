# 设备接入契约 v1

服务端已按本契约实现；联网固件仍待接入。它与现有USB日志`schema=1`是不同契约。类型见[JSON Schema](../contracts/telemetry.schema.json)，完整载荷见[有效合成例](../examples/telemetry.synthetic.valid.json)与[未启用合成例](../examples/telemetry.synthetic.unavailable.json)。样例不是已发布固件输出，身份和历史时间不能原样提交到真实平台。

## 1. 唯一设备写入口

`POST /api/device/v1/telemetry`，HTTPS、`Content-Type: application/json`、`Authorization: Bearer <device_token>`；请求体最多4 KiB，不接受压缩体或JSON批次。设备生成间隔10秒，启动增加0–2秒随机错峰；每台最多一个请求在途、一个最新待发快照。令牌只授权该设备的写入口，不能访问用户页面、读床位或操作其他设备。

平台登记设备时生成UUID与32字节密码学随机token，只存SHA-256摘要；身份以认证凭证对应Device为准，载荷`device_id`必须一致。设备显示编号/MAC/IP不参与授权。禁用或轮换后旧token立即失效。凭证必须走请求头，不能放URL、日志、Git或CSV。

| 顶层字段 | 语义 |
|---|---|
| `schema_version` | 必须为1；不支持的版本拒绝，不默默按旧版解释 |
| `device_id` | 注册UUID |
| `binding_id` | 当前绑定UUID；未绑定诊断为null，不含老人身份资料 |
| `boot_id` | 每设备持久递增的uint32启动计数，1..2^32−1；每次MCU启动原子加1并落盘成功后才能联网 |
| `seq` | 当前boot下严格递增的uint32，从0开始；达到上限时受控重启、递增boot_id再重置序号，不复用同一组合 |
| `captured_at` | 采集快照时的UTC RFC3339字符串，必须以Z结尾；精确到毫秒可选 |
| `uptime_ms` | 同一boot内单调的累计毫秒，0..2^53−1；不能拿32位millis替代 |
| `firmware_version` | 1–64字符版本标识，非身份凭据 |
| `sample` | `radar_enabled/ready/installation_confirmed/transport_ok`、`presence/bed/rr/hr/low_motion/lamp` |

`presence/bed/rr/hr`各含`raw/available/valid/reason/age_ms`。`low_motion`沿用现有三属性`raw/available/valid`，不臆造已有日志中不存在的年龄；`lamp`含`mode=auto|manual`、`pwm/target` 0..255。不传住户姓名、房号、睡眠分期、音视频、原始雷达波形或临床结论。

## 2. 时间、重试和去重

设备必须先准备可信UTC，正确校验TLS证书与主机名；时钟/证书不可信就不上报，保留本地故障记录，不能关闭证书校验。NTP来源在部署时配置；这不是声明普通SNTP本身具有加密认证。平台写入不可由设备提供的`received_at`。

服务端要求新包 `received_at−20s ≤ captured_at ≤ received_at+5s`。超过范围返回422 `clock_out_of_window`，不续在线、不写历史。20秒只是接入迟到容限；页面30秒展示时效另行计算。若时钟回拨导致排序回退，宁可暂时缺失，不能用服务器接收时间重写采集时间来掩盖问题。

DNS/连接/TLS/HTTP单次整体超时目标5秒，必须在独立任务执行；5xx/网络超时/429按1、2、4、8、最大30秒带抖动退避。成功后恢复10秒节奏。始终只保留最新待发，较新的快照替代旧待发；没有Flash积压和离线补传。一次重试保持原`boot_id/seq/captured_at/uptime_ms/payload`不变，不能为旧数据换新时间。产生的新快照分配新seq，跳号允许。

服务端处理顺序：

1. 验证TLS入口、方法/大小、token/启用状态、JSON结构和`device_id`；解析拒绝重复JSON键、NaN/Infinity、字符串布尔和未知属性。
2. 在事务中锁Device行；重新确认token摘要、enabled和device_id，防止轮换或停用竞态；要求载荷`binding_id`与当前绑定完全相等。错误绑定不降级为未绑定数据。
3. 查唯一键`(device_id, boot_id, seq)`：同键同规范化JSON内容返回200 `duplicate`；同键不同内容409 `duplicate_conflict`。比较解析后的规范化JSON，不因空白/属性顺序误报冲突。重复包不改变任何最新值或新鲜时间；过了接入时限的既存同包仍只返回duplicate。历史清理后再收到老包按时效拒绝。
4. 新包检查时钟窗口、绑定隔离期、采集质量组合；`boot_id < last_boot_id`直接拒绝；同boot要求`seq > last_seq`且`uptime_ms > last_uptime_ms`；更大boot允许seq/uptime重新开始；所有boot都要求`captured_at > last_captured_at`。回退/旧包409 `out_of_order`，不写历史、不续在线。只上传最新模式，不需要接收旧历史再维护第二条排序路径。
5. 插入Observation、设置Device.latest与最后新鲜接收时间、同boot水位；同一事务提交后返回200 `accepted`。数据库不可写返回503，不能先回成功再丢样本。

启动计数提供跨boot顺序，不能仅靠随机UUID与有偏差的UTC辨别旧开机迟到包。NVS原子写入失败时停上报，跳号允许；已有device_id却缺失/损坏计数或计数耗尽时不得默认从0重建，须归档旧设备身份并重新登记新device_id和凭证。每次启动仅写一次计数，不按每条上报写Flash。跨boot仍保守要求采集时间递增，时钟反跳修正后才继续有效写入。单机串行请求与最大5秒在途限制缩小乱序窗口；正确性仍由服务端排序规则保证。

成功响应仅含`status: accepted|duplicate`、原`boot_id/seq`、`server_time`。它不包含新绑定、远程命令或自动启用指示。`server_time`用于排错，不能把未经本地时间策略确认的响应当作禁用TLS验证的理由。

## 3. 绑定与人员更换

绑定是一次安装/住户使用周期，UUID不可复用。当前绑定的UUID和token通过受控现场配置工具写入设备。服务端不按上报时间猜测住户，也不允许修改已有Observation的绑定。

换床、换人或设备替换必须调用事务化管理动作：现场停止测量（不是调用平台停用动作）→事务内结束旧绑定→新建绑定→轮换token→清空latest及最后新鲜接收时间；启动计数、序号和采集时间防回退水位保留；随后现场更新配置并重启，清空待发槽和现场确认。完成现场供电与安装检查后再启用。设备不自己领取或猜测新绑定。绑定两侧都为null时，只写无归属的工程诊断数据。

新绑定仅在`received_at ≥ started_at+5s`且`captured_at ≥ started_at+5s`后接收；早包返回409 `binding_not_ready`，丢掉并等下一个新快照。此保守隔离配合绑定ID、凭证轮换及现场清缓存使用，不能单独依赖5秒时间偏移保证身份正确。换绑过程保持Device.enabled=true，凭证轮换立即阻止旧配置上传；新绑定显示待首次上报，旧住户latest不会闪入新住户卡片。显式停用属于另一动作，会结束绑定并置enabled=false。

## 4. 测量有效性

结构校验与下列跨字段校验都要实现；Schema不能代替服务端的时钟、权限、数据库水位检查。

- `available=false`必须`valid=false`；此时现有固件的`age_ms=0`不是新鲜证据。所有available=true字段的age_ms不得大于uptime_ms；`valid=true`必须`reason=ok`、`available=true`、`age_ms≤5000`且年龄不大于`uptime_ms`；无效字段的reason不得为ok。
- 有效presence/bed要求雷达启用、ready、安装已确认和传输正常；raw取0/1。冲突`presence=0, bed=1`不得有两个valid=true；返回422 `quality_conflict`，不把它当离床。
- 有效RR为10..25，有效HR为60..100，单位次/分钟；还要求上述基础条件、presence与bed均有效且raw=1、low_motion有效且raw=1。范围属于当前固件工程门控，不是健康阈值。0、255、无数据均不能转成呼吸停止。
- `low_motion.valid=true`要求available=true；主机压缩后的raw=0/1不是厂商原始运动枚举。平台不重做或放宽设备质量判定。
- 结构合格但全部测量无效的包可以accepted：它证明设备网络仍在工作，提供“待现场启用/测量不可用”的信息。无效值显示“—”，原因保留。

## 5. 错误响应与设备动作

所有业务错误返回`{"error":{"code":"...","message":"..."}}`，不回显token、原始请求或患者资料。代理产生的413/429/502可能不是JSON，设备须按HTTP状态容错。

| HTTP | code | 设备动作 |
|---|---|---|
| 400 | `malformed_json` | 丢包、记录本地格式错误 |
| 401 | `invalid_credential` | 停止密集重试，等待现场重配；不上传旧缓存 |
| 403 | `device_disabled` / `device_identity_mismatch` | 停止上传并提示维护 |
| 409 | `binding_mismatch` | 等待现场重配 |
| 409 | `binding_not_ready` | 等待下一10秒新快照 |
| 409 | `out_of_order` / `duplicate_conflict` | 丢旧包，记录计数；检查时钟/序号，不能改时间冒充新包 |
| 413 | — | 丢包并修复载荷大小 |
| 422 | `schema_invalid` / `quality_conflict` / `clock_out_of_window` | 丢包；字段错误修代码，时钟错误恢复可信时间后采新样本 |
| 429 / 5xx | 可能无JSON | 退避、只保留最新待发；遵守有界Retry-After，不阻塞采集 |

不提供HTTP降级入口。网络配置、凭证和绑定更换后的实际固件回归要求见[固件改造](firmware_integration.md)。
