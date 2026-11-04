# 来源与设计决策

核对日期：2026-11-04。只采用项目实际源码及厂商/框架官方资料；技术选型是本项目的简化决定，不表示官方建议本项目架构或已经验证容量。

| 依据 | 用途与决定 |
|---|---|
| [现有固件说明](../../firmware/README.md)、[main.cpp](../../firmware/src/main.cpp)、[质量门控](../../firmware/lib/sleep_core/src/monitor_logic.cpp)、[日志统计](../../firmware/docs/logs.md) | 确认本机能力、串口依赖、有效性与2秒积分上限；平台不冒充已有联网/临床能力 |
| [PCB V0.2装配](../../pcb/release_v02/README_交付与装配.md) | 现场供电、三跳帽与手动雷达启用边界；联网不替代电源安全改造 |
| [Django版本支持](https://www.djangoproject.com/download/) | 选择5.2 LTS系列，开发时锁定受支持补丁；复用Admin/认证/模板，减少组件 |
| [Django部署检查](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/)、[CSRF](https://docs.djangoproject.com/en/5.2/ref/csrf/)、[模型约束](https://docs.djangoproject.com/en/5.2/ref/models/constraints/) | 部署配置、页面写操作保护、活动绑定唯一性 |
| [PostgreSQL维护政策](https://www.postgresql.org/support/versioning/)、[pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html) | 选择受支持的17系列并跟进补丁；事务库及逻辑备份，不引入时序库 |
| [ESP32-C3 HTTP/TLS](https://docs.espressif.com/projects/esp-idf/en/latest/esp32c3/api-reference/protocols/esp_http_client.html) | HTTPS、证书与主机校验的可行能力依据；并不证明当前Arduino固件已实现或测过TLS内存 |
| [Nginx请求限流](https://nginx.org/en/docs/http/ngx_http_limit_req_module.html) | 同一代理区分设备和登录入口；阈值需按共用NAT场景试验 |

关键取舍：HTTPS单向最近快照、一个机构一个部署、一个业务应用、一个事务数据库、两个业务页面；数据归属用不可变binding_id，启动排序用每设备持久boot计数。只为当前正确性增加字段，不为未来假想产品搭消息平台、规则引擎或多租户服务。
