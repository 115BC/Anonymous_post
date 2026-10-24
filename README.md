# 匿名登记台 (Anonymous Post)

一个轻量级的**匿名登记 / 帖子发布网站** Demo。用户凭邀请码注册，发布带分区的帖子；
管理员可查看全部帖子、分类、删帖；超级管理员可管理分区、修改网站设置与邀请码。

> 本项目为演示性质 Demo，使用 SQLite 存储、会话登录，未接入邮箱验证（代码已预留，暂未启用）。

---

## 功能特性

### 角色与权限

| 角色 | 说明 | 权限 |
| --- | --- | --- |
| **普通用户 (user)** | 注册用户 | 查看**自己**的帖子；发帖（必须挂在分区下）；编辑/删除自己的帖子；修改头像与个人资料 |
| **管理员 (admin)** | 由超级管理员手动提升 | 查看**全部**帖子；删帖；修改帖子所属分区；**仅管理员可回复帖子** |
| **超级管理员 (superadmin)** | 系统初始化内置 | 管理员全部权限 + 进入「设置」：修改网站名称、修改邀请码、增删帖子分区 |

### 核心流程

1. **注册**：填写用户名、邮箱、固定邀请码、密码（≥6 位）。邮箱验证已预留接口但暂未启用。
2. **发帖**：标题 + 内容 + 选择分区（必填）+ 可选图片；图片仅管理员/本人可见上传。
3. **查看**：普通用户首页只看到自己的帖子；管理员/超级管理员首页看到全部帖子（含作者）。
4. **回复**：帖子详情页「回复」入口仅对管理员/超级管理员可见，普通用户不可回复。
5. **管理**：管理员后台可批量改分类、删帖；超级管理员可在设置中维护分区与邀请码。
6. **个人资料**：可上传头像、修改用户名与邮箱。

---

## 技术栈

- **后端**：Python 3 + [Flask](https://flask.palletsprojects.com/)（SQLite 存储）
- **前端**：Jinja2 模板 + 原生 HTML/CSS（无前端框架依赖）
- **生产部署**：gunicorn + Nginx（反向代理）
- **测试**：Flask `test_client` 端到端自测（注册/权限/发帖/回复/分类/设置）

---

## 目录结构

```
.
├── app.py                 # Flask 应用主文件（路由、权限、数据模型、初始化）
├── requirements.txt       # Python 依赖
├── README.md
├── static/
│   ├── style.css          # 页面样式
│   ├── avatars/           # 用户头像（运行时生成，含 .gitkeep）
│   └── uploads/           # 帖子图片（运行时生成，含 .gitkeep）
└── templates/
    ├── layout.html        # 基础布局（导航、闪现消息）
    ├── auth.html          # 登录 / 注册
    ├── index.html         # 帖子列表（首页）
    ├── post.html          # 帖子详情 + 回复
    ├── post_form.html     # 发帖 / 编辑帖
    ├── profile.html       # 个人资料
    ├── manage.html        # 管理员后台
    └── settings.html      # 超级管理员设置（网站信息、分区管理）
```

---

## 本地运行

```bash
# 1. 创建虚拟环境并安装依赖
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. 启动（首次运行自动创建 app.db 与默认数据）
python app.py
# 访问 http://127.0.0.1:5000
```

开发服务器监听 `127.0.0.1:5000`，`debug=True`。生产环境请使用 gunicorn（见下）。

---

## 默认账号

系统首次启动会自动创建：

| 用户名 | 密码 | 角色 |
| --- | --- | --- |
| `admin` | `admin123` | 超级管理员 (superadmin) |

默认邀请码：`DEMO2026`（可在「设置」中修改）。
默认分区：`综合`、`求助`、`反馈`（可在「设置」中增删）。

> 提示：将某用户的 `role` 在数据库中改为 `admin` 即可授予管理员权限。

---

## 部署到服务器（腾讯云轻量应用服务器）

生产环境使用 `gunicorn` + `Nginx`，示例步骤：

```bash
# 1. 安装依赖
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip nginx
python3 -m venv /opt/website/venv
/opt/website/venv/bin/pip install -i https://mirrors.aliyun.com/pypi/simple flask gunicorn

# 2. 将本仓库代码放入 /opt/website（app.py、templates/、static/）

# 3. 配置 gunicorn systemd 服务（/etc/systemd/system/website.service）
#    ExecStart=/opt/website/venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 app:app
#    WorkingDirectory=/opt/website

# 4. 配置 Nginx 反向代理到 127.0.0.1:5000，并放通防火墙 80/443

# 5. 启动
sudo systemctl daemon-reload
sudo systemctl enable --now website
sudo systemctl enable --now nginx
```

首次运行会在 `/opt/website/app.db` 自动初始化数据与默认账号。

> 若服务器位于中国大陆，pip 安装请使用阿里云等镜像；从 GitHub 拉取代码可使用
> `https://ghfast.top/https://github.com/115BC/Anonymous_post` 镜像。

---

## 后续可改进（Demo 边界）

- 启用邮箱验证（注册流程已预留 `email` 字段与接口）。
- 使用更强的安全密钥（`app.secret_key` 当前为占位值，生产需替换为随机值）。
- 密码强度策略、登录失败限流、CSRF 防护。
- 帖子支持富文本 / Markdown、分页、搜索。
- 数据库可迁移至 PostgreSQL/MySQL 以支持更高并发。

---

## 许可证

本 Demo 仅供学习与演示使用。
