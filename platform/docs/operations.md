# 平台运行与恢复

本页对应 `platform/deploy/` 的实际配置。运行形态为 Nginx、Django/Gunicorn、PostgreSQL 三个容器，只有 Nginx 的 443 端口映射到宿主机。应用以 UID 10001 运行；数据库初始化时创建独立的非超级用户供应用迁移和查询使用。

这些文件提供可执行的部署与恢复步骤；本地执行器未启动 Docker，合成部署/恢复冒烟交由第 6 节的 CI 脚本验证，以对应工作流结果为准。真实域名与设备未部署；100 台模拟设备容量、三台真机 24 小时和恢复 RTO/RPO 仍须按 [开发验收](development.md) 实测并记录。

## 1. 准备

宿主机需要 Linux、Docker Engine 与 Compose v2、`age`、OpenSSL、`mountpoint`、`sha256sum`。准备机构域名的 TLS 证书、允许人员访问的出口/VPN CIDR，以及另一台机构受控主机提供的专用备份挂载点。

在仓库中执行：

```sh
cd platform/deploy
umask 077
cp .env.example .env
cp staff-networks.conf.example staff-networks.conf
mkdir -p tls
```

编辑 `.env`，设置真实域名以及三个互不相同的随机秘密：`DJANGO_SECRET_KEY`、`POSTGRES_ADMIN_PASSWORD`、`PGPASSWORD`。示例没有预置密码，未填写会使 Compose 直接报错。每个秘密可用 `openssl rand -hex 32` 生成。保留 `.env` 为 0600；将 `fullchain.pem` 和 `privkey.pem` 放入 `tls/`，私钥只对运维账号可读。秘密、TLS 目录和人员网络配置均已排除出 Git 与镜像构建上下文。

在 `staff-networks.conf` 的 `deny all;` 前填写实际 `allow <CIDR>;`，可有多行。初始示例默认拒绝所有人员访问。配置按直接连接 Nginx 的客户端地址判断；如机构另有入口代理，应先明确可信代理地址与真实客户端 IP 的传递规则，再调整配置，不能直接信任浏览器自带的转发头。

设备入口只有 `POST /api/device/v1/telemetry` 对人员网络之外开放；该路径仍由应用校验单设备 token。人员页面、Admin 和静态文件受 CIDR 限制。`/healthz` 在外部入口返回 404，仅应用容器内部健康检查可用。无 HTTP 明文设备入口。

## 2. 首次启动

以下命令均在 `platform/deploy/` 执行：

```sh
docker compose config --quiet
docker compose build app
docker compose up -d db
docker compose run --rm app python manage.py migrate
docker compose run --rm app python manage.py init_roles
docker compose run --rm app python manage.py createsuperuser
docker compose run --rm app python manage.py collectstatic --noinput
docker compose run --rm app python manage.py check --deploy
docker compose up -d
docker compose exec nginx nginx -t
docker compose ps
```

`check --deploy` 的结果需由运维按实际域名和证书配置处理。首次创建的超级管理员用于建立人员账号和分组；查看员只分配查看权限，不设为后台工作人员。模拟设备必须登记为模拟，使用单独演示部署。TLS 根证书与 NTP 来源仍需在真实设备上配置，平台注册或绑定不会远程启用雷达或恢复现场确认。

Nginx 将自身确定的 HTTPS 协议覆盖到 `X-Forwarded-Proto`；应用容器没有宿主端口。限流初值为设备每 IP 20 次/秒、突发 200，登录每 IP 5 次/分钟、突发 10，超限返回 429。它们是待压测配置，需覆盖 100 台设备共用 NAT 与多人登录；访问日志仅记录请求 ID、方法、路径、状态及耗时，不记录查询串、Authorization 或请求体。

PostgreSQL 初始化脚本只在空数据卷运行。后续修改 `.env` 中的数据库密码不会替现有数据库执行改密；应在维护窗口同步修改数据库角色与应用配置。`docker compose down` 保留卷；不要用 `down --volumes` 执行日常升级。

## 3. 每日清理与加密备份

在备份/恢复受控工作站生成 age 密钥，私钥保存在机构密钥保管位置；应用宿主机只需要含 `age1...` 公钥的 recipients 文件，例如 `/etc/mianguang/backup-recipients.txt`。将另一台受控主机的专用目录挂载到 `/mnt/mianguang-backups`，确认该路径自身是挂载点、运维账号可写，并且具备容量监测。脚本不在挂载失败时退回本地目录。

```sh
./daily.sh /mnt/mianguang-backups /etc/mianguang/backup-recipients.txt
```

`daily.sh` 先调用 `purge_expired` 清理过期观测、身份文本、审计、Admin 日志与 Session，再调用 `backup.sh`。清理命令用 PostgreSQL advisory lock 避免重叠执行。备份使用 `pg_dump -Fc --no-owner --no-acl`，经管道直接由 age 加密，不写明文临时转储。管道任一环节失败即非零退出；成功时检查非空文件、生成 SHA-256 并验证摘要。

每天使用一个 UTC 日期文件名，同日成功重跑替换当日版本，最多保留最近七个日备份及其摘要。加密公钥可在应用宿主机，解密私钥与备份分开保存。数据库角色、Django 密钥、证书和部署配置按机构既有密钥流程另行保管；该转储不包含 PostgreSQL 全局角色。

在已设置为 `Asia/Shanghai` 的宿主机安装每日 02:10 cron（将仓库绝对路径替换为实际值）：

```cron
10 2 * * * /usr/bin/flock -n /run/lock/mianguang-daily.lock /srv/mianguang/platform/deploy/daily.sh /mnt/mianguang-backups /etc/mianguang/backup-recipients.txt >> /var/log/mianguang-daily.log 2>&1
```

由有 Docker 权限的运维账号执行并管理日志轮转；监测非零退出和当天备份是否生成。发布前也可单独运行 `backup.sh`。在线数据保留七天，备份再保留七份，因此在线清除后的数据仍可能在备份残留约七天；恢复后须按机构的删除记录重新清除。

## 4. 在隔离空库恢复

在有足够空间的受控演练主机取回 `.dump.age`、同名 `.sha256` 和 age 私钥：

```sh
./restore.sh /mnt/mianguang-backups/mianguang-YYYY-MM-DD.dump.age /secure/mianguang-age-identity.txt
```

脚本先校验摘要，再创建全新的 PostgreSQL 容器和数据卷，使用 `--network none`、不发布端口、不读取生产 `.env`；只有 `docker exec` 可以进入演练库。age 解密流交给 `pg_restore --exit-on-error --single-transaction`，随后检查账号/绑定/观测数量及绑定归属、latest 与排序水位的一致性。失败时删除此次新建的演练容器和卷；成功时保留供运维核对，并输出查看与清除命令。

核对备份日期、账号、已知绑定和设备水位；记录备份字节数、摘要、实际恢复耗时、检查结果以及负责人。演练库不连接真实设备，核对完成后按脚本输出删除敏感副本。每日备份目标 RPO 为 24 小时、目标 RTO 为 2 小时，必须由实际演练确认。该脚本只做隔离恢复，不自动替换生产数据库。

## 5. 发布与镜像锁定

升级前完成备份，在维护窗口停用 `nginx` 和 `app` 的接入，更新已审核代码，重新构建 app、执行迁移和 `check --deploy`、收集静态文件，然后启动应用和 Nginx。涉及数据库变更时，旧应用镜像不等于数据库回滚；先判断迁移兼容性，再使用经演练的恢复流程。

Python 依赖由 `platform/requirements.txt` 锁定版本和哈希；Docker 构建强制 `--require-hashes` 且只接受 wheel。以下官方多架构 index digest 已于 2026-11-04 从 Docker Hub API 读取，并向官方 Registry 按 digest 执行 HEAD，均返回 200 且摘要一致，已写入配置：

| 镜像 | 固定摘要 | 官方来源 |
|---|---|---|
| Python 3.12.16-slim-bookworm | `sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337` | [Docker Hub](https://hub.docker.com/v2/repositories/library/python/tags/3.12.16-slim-bookworm) |
| PostgreSQL 17.11-bookworm | `sha256:839fbb5a4942a7758dd93e18b42ea5649807491a0545b5eeeb8f0b8bb11857a5` | [Docker Hub](https://hub.docker.com/v2/repositories/library/postgres/tags/17.11-bookworm) |
| Nginx 1.30.6 | `sha256:66b50d24288dba67f3d000b31223daefc4868c58d29aaacb6a4ff9771597b5eb` | [Docker Hub](https://hub.docker.com/v2/repositories/library/nginx/tags/1.30.6) |

更新补丁时重新核验官方标签与 digest，并同步更新 Dockerfile、Compose 和恢复脚本中的固定镜像。Digest 可解析不代表本部署已构建或通过容量验收。

## 6. CI 合成冒烟

`deploy/smoke.sh` 面向有 Docker 和 `age` 的 Linux CI runner。它使用独立 Compose 项目、随机 localhost 端口、临时秘密及自签证书；curl 和模拟器显式信任该临时证书，保持证书/主机名校验。不会读取正式 `.env` 或替换正式证书/CIDR 配置。

脚本完成镜像构建、迁移、角色初始化、静态文件收集、部署检查、Nginx 配置检查和 HTTPS 访问边界；复用现有模拟器让三台设备各运行20秒，随后运行实际日清理、age 加密备份和隔离恢复脚本，核对账号、三个绑定、三个设备各自的观测及水位关联。结束后清理临时容器、卷和密钥。CI 的临时本地挂载只作为备份目录检查的夹具，不表示已完成异机备份或生产恢复演练；真实容量、证书续期、机构网络和恢复耗时仍按前文验收。
