# 青禾 · 计师班班级空间 2.0

面向班级内部的通知、匿名反馈、心理树洞、问题交流与资源库平台。2.0 在原有基础上补齐 **问题交流** 与 **资源库（文件上传 + 班委审核）**，并保留三条硬规则：

1. 反馈不可追溯，但可以回复；
2. 树洞仅雪绒花可见，双方对话仅双方可见；
3. 资源库做文件上传，不接网盘链接。

- 后端：Flask 2.3 + SQLite（Werkzeug 密码哈希）
- 前端：Jinja2 + 原生 CSS/JS，无前端构建步骤
- 移动优先，支持 320px 起；自动跟随系统明暗主题

> **来源说明**：本仓库以 [115BC/Anonymous_post](https://github.com/115BC/Anonymous_post) 为基底克隆后大改。原项目是登录发帖原型，没有匿名线程模型、CSRF、上传限制与审核；2.0 保留了它的仓库血脉，但认证、数据模型、模板、样式与安全边界基本重写。详见文末「与原型的关系」。

## 已实现

| 模块 | 能力 |
| --- | --- |
| 通知 | 安全提示 / 活动预告 / 重要消息 / 考试提醒；置顶、截止日期、未读计数 |
| 匿名反馈 | 不关联账号，班委可在线程内回复；凭一次性回访码回来查看 |
| 树洞 | 独立的雪绒花账号收信；班长/管理员/超管访问信箱一律 403 |
| 问题交流 | 实名提问与回复、标记已解决、作者/班委可删除；问答与匿名模块完全分离 |
| 资源库 | 登录上传（20 MB 内、类型白名单）、班委审核、登录后下载、下载计数、上传者/班委删除 |
| 账号 | 邀请码注册、登录限速、改密、封禁、改名、角色管理 |
| 隐私 | 独立的「隐私与数据说明」页，如实写明保存与不保存什么 |

## 目录

```
app.py                 路由、权限、CSRF、限速、CLI
db.py                  数据库连接、首次初始化与示例通知
schema.sql             表结构与约束
templates/             Jinja 模板
static/                style.css / app.js
tests/smoke_test.py    端到端冒烟测试（不依赖浏览器）
tests/seed_shots.py    生成截图用的演示数据（仅开发）
tests/shots_cdp.js     Chrome DevTools 截图脚本（仅开发）
deploy/nginx.conf      Nginx TLS 反向代理（上传上限、敏感路径不记日志）
deploy/gunicorn.conf.py
deploy/backup.py       数据库在线备份 + 可选资源文件打包 + 30 天轮转
instance/uploads/      资源文件私有目录（不在 static 下，默认被 .gitignore 忽略）
```

## 本地运行

需要 Python 3.10+（开发环境为 3.12）。

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

打开 <http://127.0.0.1:5000>。首次启动会自动建库、写入 4 条示例通知，并创建超级管理员：

- 终端会打印初始密码；
- 同时写入 `instance/first-login.txt`；
- **登录后立刻修改密码，并删除该文件。**

注册同学账号需要邀请码，默认 `CLASS2026`（可在管理命令或 `instance` 库中修改）。

配置通过环境变量注入，应用**不会自动读取 `.env`**。可参考 `.env.example`：

```bash
# Linux/macOS
set -a; . ./.env; set +a
# PowerShell
Get-Content .env | ForEach-Object { if ($_ -match '^([^#=]+)=(.*)$') { Set-Item "env:$($matches[1])" $matches[2] } }
```

| 变量 | 说明 |
| --- | --- |
| `SECRET_KEY` | 会话与回访码 HMAC 的密钥；留空则生成并保存到 `instance/secret.key` |
| `COOKIE_SECURE` | HTTPS 部署时设为 `1`；本地 HTTP 调试保持 `0` |
| `SITE_NAME` | 站点名称（仅首次建库时写入） |
| `INVITE_CODE` | 注册邀请码（仅首次建库时写入） |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 首次建库时的超管账号；密码留空则随机生成 |
| `CLASSSITE_DB` | SQLite 路径，默认 `instance/classsite.db` |
| `CLASSSITE_UPLOADS` | 资源文件目录，默认 `instance/uploads`；生产建议放到代码目录外 |

> 切换 `SECRET_KEY` 会让所有登录会话、回访码和线程链接失效。上线后不要随意更换。

## 角色与初始化

| 角色 | 怎么来 | 能做什么 |
| --- | --- | --- |
| `superadmin` | 首次启动自动创建 | 全部管理权限；可进用户管理 |
| `member` | 邀请码注册 | 看通知、发匿名反馈、写树洞、提问与回复、上传资源 |
| `admin` | 由超管在后台或 CLI 设置 | 发通知、回复匿名反馈、审核/删除资源、管理问答 |
| `counselor` | **只能**由 CLI 设置 | 唯一能进入树洞信箱的人 |

雪绒花请**单独注册一个账号**（例如 `xueronghua`），不要与班长账号共用：

```bash
flask --app app set-role xueronghua counselor
```

同一时间只允许一个 `counselor`。系统管理员和班委即使在后台也无法进入树洞信箱，接口直接返回 403。雪绒花换人时，先把旧账号改回 `member`，再设置新账号。

常用命令：

```bash
flask --app app set-invite CLASS2027          # 修改邀请码
flask --app app set-site "青禾 · 计师班"       # 修改站点名称
flask --app app reset-password admin          # 交互式重置密码
flask --app app set-role 张三 admin            # 设班委
flask --app app set-role 李四 counselor        # 设雪绒花（唯一）
```

## 匿名模型与边界

**反馈线程**（`feedback_threads` / `feedback_messages`）没有 `user_id`、IP、User-Agent 字段。提交后生成 8 位一次性回访码（如 `K7F2-9QX3`），数据库只保存它的 HMAC-SHA256 摘要；明文只在提交成功页出现一次。查看线程使用签名 URL，不把回访码放进地址栏。

**树洞线程**同样不落身份字段。信箱和线程页只对 `counselor` 开放，班长、团支书、超管均无法查看；首页也不展示树洞的汇总统计。

**问题交流与资源库不是匿名模块**：问答保存作者账号；资源保存上传者账号、审核人与下载记录。两者使用独立数据表，不与反馈/树洞线程关联，也不会把身份写进匿名表。提问页和上传页都有明确提示。

限速：每个会话每小时最多 5 条反馈、5 封信、10 个提问、10 次上传、30 条问答回复；回访码连续输错 5 次锁定 15 分钟；登录连续失败 5 次锁定 15 分钟。

必须如实告诉同学的局限：

- **服务器管理员仍能看到数据库和提交时间**，看不到账号身份。匿名是应用层与制度层的承诺，不是密码学意义上的绝对隔离。
- TCP 连接本身仍经过服务器与网络提供商；匿名入口的 Nginx/Gunicorn 访问日志已关闭，但云厂商负载均衡或 CDN 可能自行记录，建议不要在前面套 CDN。
- 回访码就是钥匙：丢失无法找回，截图转发等于把对话交给对方。
- 树洞不是危机干预通道，没有 24 小时值守。遇到危险请直接拨打 **12356**、**120 / 110** 或联系学校心理中心。
- 备份默认保留 30 天；删除线程会立即从主库移除，但备份中的副本要等轮转后消失。

`deploy/nginx.conf` 对 `/feedback`、`/tree`、`/qa`、`/resources`、`/account`、`/login`、`/register`、`/admin/feedback`、`/admin/resources` 设置了 `access_log off`；`deploy/gunicorn.conf.py` 关闭了 access log，只保留错误日志。部署后请实际验证日志文件没有新增匿名请求记录。

资源文件不在 `static/` 下，只能通过登录后的 `/resources/<id>/download` 获取，响应固定为附件下载并带 `nosniff`。班委退回资料时会删除服务器上的文件。

## 安全基线

- 所有 POST 校验 CSRF token；登录/注册/提交表单均带隐藏字段
- 会话 Cookie：HttpOnly + SameSite=Lax + HTTPS 下 Secure
- 登录与回访码限速，登录失败对不存在用户也做恒定时间哈希比较
- 页面输出默认转义；CSP、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer`
- 请求体上限 21 MB（20 MB 文件 + 表单开销）；Nginx 同步限制 22 MB
- 上传扩展名白名单、随机存储名、原始文件名仅作下载名；文件不落在静态目录，下载需登录与可见性校验
- 资源先审后发；退回即删文件；服务器不做病毒扫描，页面已如实提示
- `SECRET_KEY` 不硬编码，支持环境变量或 0600 权限的持久密钥文件
- 会话每次请求都会从数据库重新加载用户，封禁与角色变更立即生效
- 雪绒花角色只能通过服务器 CLI 设置，后台没有提权入口

## 部署（Ubuntu + Nginx + Gunicorn）

以 `/opt/classsite` 为例，需将域名、证书路径替换为实际值。

```bash
sudo adduser --system --group --home /opt/classsite classsite
sudo -u classsite git clone <repo> /opt/classsite   # 或 rsync 上传
cd /opt/classsite
sudo -u classsite python3 -m venv .venv
sudo -u classsite .venv/bin/pip install -r requirements.txt
```

准备数据目录与密钥：

```bash
sudo mkdir -p /var/lib/classsite/uploads
sudo chown -R classsite:classsite /var/lib/classsite
sudo chmod 700 /var/lib/classsite

sudo tee /etc/classsite.env >/dev/null <<'EOF'
SECRET_KEY=替换为 openssl rand -hex 32 的输出
COOKIE_SECURE=1
SITE_NAME=青禾 · 计师班班级空间
INVITE_CODE=替换为班级内部邀请码
CLASSSITE_DB=/var/lib/classsite/classsite.db
CLASSSITE_UPLOADS=/var/lib/classsite/uploads
CLASSSITE_BACKUP_DIR=/var/backups/classsite
BACKUP_KEEP_DAYS=30
EOF
sudo chmod 600 /etc/classsite.env
```

首次建库（会打印管理员初始密码）：

```bash
sudo -u classsite bash -c 'set -a; . /etc/classsite.env; set +a; cd /opt/classsite; .venv/bin/python -c "import app; print(\"init ok\")"'
sudo -u classsite chmod 600 /var/lib/classsite/classsite.db
```

systemd 服务 `/etc/systemd/system/classsite.service`：

```ini
[Unit]
Description=Class site
After=network.target

[Service]
User=classsite
Group=classsite
WorkingDirectory=/opt/classsite
EnvironmentFile=/etc/classsite.env
ExecStart=/opt/classsite/.venv/bin/gunicorn -c deploy/gunicorn.conf.py app:app
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=/var/lib/classsite /opt/classsite/instance

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now classsite
sudo systemctl status classsite
```

Nginx：

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/classsite
sudo ln -s /etc/nginx/sites-available/classsite /etc/nginx/sites-enabled/
# 修改 server_name 与证书路径后：
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d class.example.com   # 申请证书
```

应用已在响应头设置 CSP/HSTS 等安全头，Nginx 中也重复设置了关键项。匿名入口的访问日志按上文关闭。

## 备份与恢复

`deploy/backup.py` 使用 SQLite backup API 做在线备份，并清理超过 30 天的文件（权限 0600）。加上 `--with-files` 会把资源目录打包成同时间戳的 `classsite-files-*.zip`。

```bash
set -a; . /etc/classsite.env; set +a
python deploy/backup.py --with-files
```

每日 04:15 的 cron：

```cron
15 4 * * * cd /opt/classsite && set -a; . /etc/classsite.env; set +a; .venv/bin/python deploy/backup.py --with-files >> /var/log/classsite-backup.log 2>&1
```

如果没有加 `--with-files`，数据库会引用已经不在备份里的文件。恢复时需要同时还原数据库与资源目录，否则资源列表会出现下载 404。

恢复：

```bash
sudo systemctl stop classsite
sudo cp /var/backups/classsite/classsite-YYYYMMDD-HHMMSS.db /var/lib/classsite/classsite.db
sudo rm -f /var/lib/classsite/classsite.db-wal /var/lib/classsite/classsite.db-shm
# 若同时备份了资源文件：
sudo rm -rf /var/lib/classsite/uploads
sudo mkdir -p /var/lib/classsite/uploads
sudo unzip -q /var/backups/classsite/classsite-files-YYYYMMDD-HHMMSS.zip -d /var/lib/classsite/uploads
sudo chown -R classsite:classsite /var/lib/classsite
sudo chmod 600 /var/lib/classsite/classsite.db
sudo systemctl start classsite
```

## 测试

```bash
python tests/smoke_test.py
```

覆盖注册登录、通知已读、匿名反馈提交/回访/回复、树洞、问答发布/回复/标记解决、资源上传/审核/下载/类型拒绝、管理员与雪绒花权限边界、CSRF、错误码、改密后旧密码失效。测试使用独立的临时数据库与 `tests/tmp_uploads/`，不触碰 `instance/`。

视觉回归（可选）：先生成 `tests/shot.db`，再用同一套环境变量启动演示实例：

```bash
python tests/seed_shots.py
CLASSSITE_DB=tests/shot.db SECRET_KEY=shot-secret INVITE_CODE=SHOTCODE ADMIN_PASSWORD=Admin12345 python app.py
```

另开一个终端执行：

```bash
node tests/shots_cdp.js
```

截图输出到 `tests/screens/`，需要本机安装 Chrome。

## 上线前检查

1. 修改邀请码，确认旧邀请码失效
2. 修改管理员密码，删除 `instance/first-login.txt`
3. `SECRET_KEY` 为随机值，`COOKIE_SECURE=1`，全站 HTTPS
4. 用管理员账号访问 `/tree`，确认收到 403
5. 用雪绒花账号确认信箱只有本人可见
6. 检查 Nginx/Gunicorn 日志中无 `/feedback`、`/tree`、`/qa`、`/resources` 的访问记录
7. 上传一个小文件走完「待审核 → 通过 → 下载」流程，再测一次超过 20 MB 的文件
8. 配置每日备份（建议 `--with-files`），并实际恢复一次到测试目录
9. 把「隐私与数据说明」页发到班级群，说明回访码、实名问答、资源审核与危机求助方式

## Roadmap（v2.1）

- 资源库分科目归档、分页与存储配额（目前是单页列表）
- 问答的“最佳回答”标记与站内提醒
- 通知的定时发布与站内提醒
- 管理员操作审计（只记录管理动作，不触碰匿名内容）
- 雪绒花交接流程与新来信提醒（仍不暴露写信人）

## 与原型的关系

本项目以 [115BC/Anonymous_post](https://github.com/115BC/Anonymous_post) 为基底执行 `git clone`，原仓库的提交历史与 `origin` 仍保留在本地 `.git` 中。原型的账号、发帖、评论、头像与管理页已被大规模替换：

- 认证与会话：加入 CSRF、登录限速、安全 Cookie、角色隔离与 CLI 管理；
- 数据模型：新增完全无身份字段的反馈/树洞线程表，问答与资源独立建表；
- 上传：从无限制的 `static/uploads` 改为私有目录、类型白名单、20 MB 上限与先审后发；
- 前端：整体重写为移动优先的响应式界面，保留通知分类与班级场景。

原型中的密码重置、邮箱、头像等与班级场景无关或增加隐私面的功能没有保留。若要对外发布，请自行确认原仓库的授权情况（原仓库当前未声明 LICENSE）。
