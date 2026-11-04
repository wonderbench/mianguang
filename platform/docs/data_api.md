# 数据模型与接口

以下是Django模型/迁移与视图的设计依据；对应实现位于`platform/app/`，实际交付与验收状态见[平台入口](../README.md)。业务时间一律UTC `timestamptz`，显示时区在部署中配置，首版默认`Asia/Shanghai`。

## 1. 最少数据表

复用Django User、Group、Permission、Session；不自建认证/租户表。业务只有下列6张表，字段可按迁移规范增加主键和创建时间，但不要提前增加居民完整档案、健康诊断、消息、工单或订阅表。

| 表 | 必要字段与关系 |
|---|---|
| Site | `id,name,enabled`；机构内地点，名称唯一 |
| Bed | `id,site_id,room_label,bed_label,enabled`；唯一`(site,room_label,bed_label)`；社区单人住户也用一个床位表示 |
| Device | `id(UUID),display_code(unique),enabled,is_simulator,token_hash(unique),credential_changed_at,latest_observation_id(nullable),last_fresh_received_at(nullable),last_boot_id,last_seq,last_uptime_ms,last_captured_at`；水位初值为null，不把0当已收到 |
| Binding | `id(UUID),device_id,bed_id,resident_alias,location_label_snapshot,started_at,ended_at(nullable),created_by`；代号≤64字符、位置快照≤160字符；当前绑定由ended_at为空的行确定，不再存第二份active_binding外键 |
| Observation | `id(bigint),device_id,binding_id(nullable),boot_id,seq,captured_at,received_at,uptime_ms,firmware_version,payload(JSONB),payload_hash`；payload为完整验证后的规范化请求对象，hash为其SHA-256 |
| AuditEntry | `id,at,actor_id(nullable),action,target_type,target_id,details(JSONB)`；小型白名单详情，如旧/新绑定ID、配置变更字段名、导出时间范围与行数，不复制完整健康值或密钥 |

`Device.active_binding`在文档中表示当前Binding查询结果，不是额外存储字段。`latest_observation_id`是最多100台设备总览的必要读优化，不复制整份payload到Device；更新必须在写Observation的同一事务中完成。保留水位以拒绝历史清理后的回退包。

绑定的住户代号只用于机构内部对应，不存姓名、证件、电话、病历或地址明细。代号、原地点快照、设备和起点创建后不可直接编辑；更换住户必须结束并新建绑定。Site/Bed以后改名不改写历史位置快照。

Site/Bed仍有活动绑定时禁止直接停用，须先结束相应绑定。已有Observation或Binding关联的基础资料不提供普通Admin硬删除，避免越过历史保留逻辑。

## 2. 数据库必须兜住的约束

- 当前绑定条件唯一：`device_id WHERE ended_at IS NULL`，以及`bed_id WHERE ended_at IS NULL`。每台设备只对应一个床位，每床位最多一台。
- `ended_at IS NULL OR ended_at >= started_at`；禁止回填/重叠历史绑定，开始/结束时刻由服务端生成，不接受浏览器填写历史生效时间。
- Observation唯一`(device_id,boot_id,seq)`；字段正值/范围与契约一致；`binding_id`的device必须与Observation.device一致，由锁内服务函数校验。
- 查询索引`Observation(binding_id,captured_at,id)`；未绑定诊断按`(device_id,captured_at,id)`；过期清理索引`received_at`。Audit按`at`索引即可，不提前对JSONB建GIN索引或分区。
- 删除Observation时Device.latest设null；Device的接收时间/排序水位不因此归零。业务外键默认PROTECT，普通Admin不提供级联硬删除。

Django条件唯一约束在模型和数据库两层落实，依据[官方约束文档](https://docs.djangoproject.com/en/5.2/ref/models/constraints/)。只在表单中检查“床位空闲”不足以防并发冲突。

## 3. 关键事务

**接收**：事务外只做限大小、解析和快速凭证查找；事务内`select_for_update(Device)`后重新校验凭证、enabled、当前Binding，再按[接入顺序](device_protocol.md)验证。写Observation和latest后提交。唯一键竞争返回既定幂等结果，不产生第二条历史，不先200后落库。

**绑定/换人/换床**：一个`replace_binding()`函数被Admin自定义动作调用。按固定顺序锁涉及的Device、Bed及活动Binding；锁争用后重新查询占用，数据库条件唯一冲突给用户“床位已被分配”，不做静默覆盖。若目标床位已有另一台设备，管理员须先显式结束那次绑定；不自动拆除他人的安装。

在同一事务中结束旧Binding、新建Binding、轮换token、清空latest和`last_fresh_received_at`、写审计；保留`last_boot_id/last_seq/last_uptime_ms/last_captured_at`防回退水位。换绑并不调用disable_device，Device.enabled保持true；设备在现场重配期间显示“待首次上报/待现场安装”，不是沿用旧住户状态。准备工作需先现场停止使用；配置工具重启后才允许新绑定测量。若事务回滚，不给用户显示或导出尚未生效的新凭证。

**解绑/停用**：结束当前Binding、撤销或轮换token、清空latest/新鲜接收时间，保留水位；停用另置enabled=false。若仍要做无绑定诊断，管理员显式重新发放null绑定配置。不要让原住户配置继续写入无归属区。

**凭证轮换**：同样锁Device、只显示新token一次、禁止日志记录；要求现场更新并重启。旧token立刻失效；普通轮换不清启动排序水位、不自动生成新住户绑定。

审计只由领域函数写入，Admin对象修改日志也须过滤凭证；不能把包含token的完整配置作为`change_message`。事务失败不记录成功操作。

Binding/Device在Admin日志中的`object_repr`只用内部ID，不包含住户代号或token；Django内置LogEntry也按90天清理，避免另一个日志表绕过资料清除策略。

## 4. 首版接口面

不为Admin已承担的CRUD再做一套REST API。浏览器使用Django Session；状态改变只用POST与CSRF，GET没有写操作。设备token入口单独鉴权且仅该视图不使用浏览器CSRF，不全站豁免。

| 方法/路径 | 身份 | 结果 |
|---|---|---|
| GET/POST `/login/`；POST `/logout/` | 人员 | Django认证；失败不泄露账号是否存在 |
| GET `/` | 管理员/查看员 | 总览页面 |
| GET `/fragments/overview/?site=<id>` | 管理员/查看员 | 同源HTML片段，包含server_time；15秒轮询，`Cache-Control: no-store` |
| GET `/bindings/<uuid>/` | 管理员/查看员 | 当前或历史绑定详情，明确有效期间与代号 |
| GET `/api/ui/v1/bindings/<uuid>/series?from=<UTC>&to=<UTC>` | 管理员/查看员 | 下述1分钟显示桶与10秒时隙统计 |
| GET `/bindings/<uuid>/export.csv?from=<UTC>&to=<UTC>` | 仅管理员 | 同一绑定原始快照CSV；记导出审计 |
| `/admin/` 内表单/自定义POST动作 | 仅管理员 | 登记、绑定变更、停用、令牌轮换、账号；所有对象级写权限在服务端检查 |
| POST `/api/device/v1/telemetry` | 单设备token | 只写本设备；见接入契约 |
| GET `/healthz` | 仅容器/运维网 | 检查应用与数据库可用性，不含设备/住户内容 |

页面API不接受设备token；设备写入口不接受Session代替token。查看员不能靠猜UUID导出CSV、调用Admin POST或创建绑定。未登录页面重定向登录，JSON接口返回401，不向前端返回登录页HTML冒充数据。

`from/to`必须UTC、对齐整分钟且`from<to`、跨度≤24小时；to不得超过服务端当前分钟起点，from不得早于该起点减7天，超界返回400 `invalid_range`；绑定不存在返回404，未获功能权限返回403。查询将窗口裁剪到Binding实际期间，但响应同时返回请求范围与有效范围。禁止无限制“导出全部”。

### 趋势响应约定

响应为`{binding_id,server_time,requested_range,effective_range,summary,buckets}`；时间均UTC。

`summary`含`expected_slots,received_slots,rr_valid_slots,hr_valid_slots,report_completeness,rr_valid_ratio,hr_valid_ratio`，比率为0..1或null；严格使用[统计口径](architecture.md#5-统计口径)。`buckets`按时间递增，每项为`{minute,received_slots,rr_valid_slots,hr_valid_slots,rr_bpm,hr_bpm}`。仅完整6点且相应字段全有效时给值，否则null；没有点的分钟也返回null桶，SVG须断线。每个接口窗口最多1440分钟桶；不返回居民姓名或device token。

CSV每行一个原始Observation，含绑定ID、历史位置快照、住户代号、device_id、boot_id、seq、采集/接收时间、占用及RR/HR原值/有效标志/原因/年龄、灯状态。无效原值在导出中与valid/reason一起保留，不只导出数值。别名、位置等文本先按CSV引用规则编码，且对`= + - @`、tab/回车开头等公式风险前缀做文本转义；设备token和原始Authorization永不输出。

## 5. 删除与历史保留

Observation默认保留7天，按`received_at`分批删除；过去绑定没有Observation且已结束超过7天后清除resident_alias与位置快照，保留最小绑定ID/设备/床位/时间关联。Audit保留90天，不含住户代号与测量值；过期Session随日清理。数据保留是本项目试点默认，启用前由机构确认并记录。

不实现软删除框架、事件溯源或长期住户档案。数据库备份中的旧数据按[运维保留规则](deployment.md)过期；“在线库已清除”不能描述为所有备份已立刻消失。
