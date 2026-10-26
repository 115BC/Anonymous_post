"""SQLite 连接与初始化。

数据库刻意不采集：反馈/树洞的身份、IP、User-Agent。登录限速只保存
用户名的 HMAC 摘要，用于防止口令爆破。
"""

import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from werkzeug.security import generate_password_hash

BASE = Path(__file__).resolve().parent
INSTANCE = BASE / "instance"
SCHEMA = BASE / "schema.sql"
FMT = "%Y-%m-%d %H:%M"

_db_env = os.environ.get("CLASSSITE_DB", "").strip()
if _db_env:
    DB_PATH = Path(_db_env)
    if not DB_PATH.is_absolute():
        DB_PATH = BASE / DB_PATH
else:
    DB_PATH = INSTANCE / "classsite.db"

SITE_NAME = os.environ.get("SITE_NAME", "青禾 · 计师班班级空间").strip() or "青禾 · 计师班班级空间"
INVITE_CODE = (os.environ.get("INVITE_CODE") or "CLASS2026").strip().upper()
ADMIN_USERNAME = (os.environ.get("ADMIN_USERNAME") or "admin").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or ""


def now_str():
    return datetime.now().strftime(FMT)


def connect():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _seed(conn):
    cur = conn.cursor()

    if cur.execute("SELECT COUNT(*) FROM site_config").fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO site_config (id, site_name, invite_code) VALUES (1, ?, ?)",
            (SITE_NAME, INVITE_CODE),
        )
        print(f"[init] 站点名称：{SITE_NAME}")
        print(f"[init] 注册邀请码：{INVITE_CODE}（可在 管理 → 设置 或 flask set-invite 修改）", flush=True)

    if cur.execute("SELECT COUNT(*) FROM users WHERE role = 'superadmin'").fetchone()[0] == 0:
        password = ADMIN_PASSWORD
        generated = not password
        if generated:
            password = secrets.token_urlsafe(9)
        cur.execute(
            "INSERT INTO users (username, password_hash, role, status, created_at) "
            "VALUES (?, ?, 'superadmin', 'active', ?)",
            (ADMIN_USERNAME, generate_password_hash(password), now_str()),
        )
        print(f"[init] 已创建超级管理员：{ADMIN_USERNAME}", flush=True)
        if generated:
            INSTANCE.mkdir(parents=True, exist_ok=True)
            credential_file = INSTANCE / "first-login.txt"
            credential_file.write_text(
                "初始管理员账号（首次登录后请用 flask reset-password 修改密码并删除本文件）\n"
                f"用户名：{ADMIN_USERNAME}\n密码：{password}\n",
                encoding="utf-8",
            )
            try:
                os.chmod(credential_file, 0o600)
            except OSError:
                pass
            print(f"[init] 初始密码已写入 {credential_file}", flush=True)
            print(f"[init] 初始密码：{password}", flush=True)

    if cur.execute("SELECT COUNT(*) FROM notices").fetchone()[0] == 0:
        admin = cur.execute(
            "SELECT id FROM users WHERE role = 'superadmin' ORDER BY id LIMIT 1"
        ).fetchone()
        author_id = admin["id"] if admin else None
        created = datetime.now()
        exam_day = (created.date() + timedelta(days=9)).strftime("%Y-%m-%d")
        activity_day = (created.date() + timedelta(days=4)).strftime("%Y-%m-%d")

        rows = [
            (
                "safety",
                "宿舍用电与晚归安全提醒",
                "最近气温下降，宿舍取暖设备增多，请同学们注意：\n"
                "1. 不使用热得快、电热毯、小太阳等大功率电器；\n"
                "2. 离开宿舍前拔掉充电器，不在床上给设备充电；\n"
                "3. 晚归请提前在班级群报备，尽量结伴回寝；\n"
                "4. 遇到可疑人员或安全隐患，第一时间联系宿管和班长。\n\n"
                "安全无小事，请互相提醒。",
                1,
                None,
                "published",
                author_id,
                (created - timedelta(hours=2)).strftime(FMT),
                (created - timedelta(hours=2)).strftime(FMT),
            ),
            (
                "exam",
                "期中考试安排与考场提醒",
                "期中考试周从下周开始，请提前确认考场和考试时间：\n"
                "· 携带学生证、黑色签字笔、2B 铅笔；\n"
                "· 提前 20 分钟到达考场，迟到 15 分钟不得入场；\n"
                "· 手机等电子设备关机后放在指定位置；\n"
                "· 有冲突或特殊情况，请在考试前联系学委。\n\n"
                "各科具体时间以教务系统为准。",
                0,
                exam_day,
                "published",
                author_id,
                (created - timedelta(hours=5)).strftime(FMT),
                (created - timedelta(hours=5)).strftime(FMT),
            ),
            (
                "activity",
                "师范生教学技能大赛报名",
                "学院师范生教学技能大赛开始报名，含教学设计、模拟授课、板书三个环节。\n"
                "想参加的同学请在截止日期前找学委登记，班级会组织一次试讲互评。\n"
                "没有经验也可以报名，重点是练胆子、攒经验。",
                0,
                activity_day,
                "published",
                author_id,
                (created - timedelta(days=1)).strftime(FMT),
                (created - timedelta(days=1)).strftime(FMT),
            ),
            (
                "important",
                "班级通知渠道与隐私说明",
                "班级事务统一在本站「通知」发布，重要消息会同时转发到班级群。\n"
                "匿名反馈与树洞的内容不关联账号、不记录 IP；反馈请保存好回访码，"
                "树洞只有雪绒花可以查看。\n"
                "详细的数据说明见页面底部「隐私与数据说明」。",
                0,
                None,
                "published",
                author_id,
                (created - timedelta(days=2)).strftime(FMT),
                (created - timedelta(days=2)).strftime(FMT),
            ),
        ]
        cur.executemany(
            "INSERT INTO notices (category, title, body, pinned, deadline, status, "
            "author_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    conn.commit()


def init_db():
    INSTANCE.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        _seed(conn)
    finally:
        conn.close()
