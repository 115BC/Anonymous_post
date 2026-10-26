"""青禾 · 计师班班级空间 2.0

在匿名反馈与树洞之外，补齐问题交流与班级资源库。
安全基线：CSRF、登录限速、无硬编码密钥、匿名模块不落身份与日志；
资源文件存放在 instance/uploads，只能通过登录后的下载路由获取。
"""

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path

import click
from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_from_directory, session, url_for)
from itsdangerous import BadSignature, URLSafeSerializer
from werkzeug.security import check_password_hash, generate_password_hash

import db
from db import FMT, now_str

BASE = Path(__file__).resolve().parent
INSTANCE = BASE / "instance"
INSTANCE.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = Path(os.environ.get("CLASSSITE_UPLOADS") or (INSTANCE / "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_MAX_BYTES = 20 * 1024 * 1024


def _load_secret_key():
    env = os.environ.get("SECRET_KEY", "").strip()
    if env:
        return env
    path = INSTANCE / "secret.key"
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = secrets.token_hex(32)
    path.write_text(value, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return value


app = Flask(__name__, instance_path=str(INSTANCE))
app.config.update(
    SECRET_KEY=_load_secret_key(),
    SESSION_COOKIE_NAME="classsite_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=14),
    MAX_CONTENT_LENGTH=UPLOAD_MAX_BYTES + 1024 * 1024,
)

db.init_db()

CATEGORIES = {
    "safety": "安全提示",
    "activity": "活动预告",
    "important": "重要消息",
    "exam": "考试提醒",
}
TOPICS = {
    "study": "学习与课程",
    "class": "班级事务",
    "activity": "活动想法",
    "other": "其他",
}
MOODS = {
    "talk": "想说说",
    "tired": "有点累",
    "happy": "有点开心",
    "help": "需要帮助",
}
ROLE_LABELS = {
    "member": "同学",
    "admin": "班委",
    "counselor": "雪绒花",
    "superadmin": "系统管理员",
}
UPLOAD_TYPES = {
    "pdf": "PDF", "doc": "Word", "docx": "Word",
    "ppt": "演示文稿", "pptx": "演示文稿",
    "xls": "表格", "xlsx": "表格",
    "zip": "压缩包", "md": "Markdown", "txt": "文本",
    "png": "图片", "jpg": "图片", "jpeg": "图片",
}
RESOURCE_STATUS = {
    "pending": "待审核",
    "approved": "已共享",
    "rejected": "未通过",
}

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
USERNAME_RE = re.compile(r"^[\w\u4e00-\u9fa5-]{2,20}$", re.UNICODE)
INVITE_RE = re.compile(r"^[A-Z0-9_-]{4,32}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(16))
thread_serializer = URLSafeSerializer(app.secret_key, salt="classsite-thread")

app.jinja_env.globals.update(
    CATEGORIES=CATEGORIES,
    TOPICS=TOPICS,
    MOODS=MOODS,
    ROLE_LABELS=ROLE_LABELS,
    UPLOAD_TYPES=UPLOAD_TYPES,
    RESOURCE_STATUS=RESOURCE_STATUS,
)


# ---------------------------------------------------------------- database

def get_db():
    if "db" not in g:
        g.db = db.connect()
    return g.db


@app.teardown_appcontext
def close_db(exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


# ---------------------------------------------------------------- helpers

def csrf_token():
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


app.jinja_env.globals["csrf_token"] = csrf_token


def safe_next(target):
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("home")


def password_ok(pw):
    return (8 <= len(pw) <= 128
            and re.search(r"[a-z]", pw)
            and re.search(r"[A-Z]", pw)
            and re.search(r"[0-9]", pw))


def normalize_code(raw):
    value = re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()
    if len(value) != 8 or any(ch not in CODE_ALPHABET for ch in value):
        return ""
    return value


def format_code(raw):
    return f"{raw[:4]}-{raw[4:]}"


def code_digest(raw):
    return hmac.new(app.secret_key.encode(), raw.encode(), hashlib.sha256).hexdigest()


def make_code():
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return raw, format_code(raw), code_digest(raw)


def clean_upload_name(raw):
    name = (raw or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".")
    return name[:120] or "未命名文件"


def upload_ext(name):
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def thread_token(kind, thread_id):
    return thread_serializer.dumps({"k": kind, "id": thread_id})


def read_thread_token(token, kind):
    try:
        data = thread_serializer.loads(token)
    except (BadSignature, ValueError):
        abort(404)
    if (not isinstance(data, dict) or data.get("k") != kind
            or not isinstance(data.get("id"), int)):
        abort(404)
    return data["id"]


def allow_session_action(key, limit, window_seconds):
    stamp = time.time()
    recent = [t for t in session.get(key, []) if stamp - t < window_seconds]
    if len(recent) >= limit:
        session[key] = recent
        return False
    recent.append(stamp)
    session[key] = recent
    return True


def lookup_blocked(prefix):
    return session.get(prefix + "_lock", 0) > time.time()


def lookup_failed(prefix):
    fails = session.get(prefix + "_fails", 0) + 1
    if fails >= 5:
        session[prefix + "_lock"] = time.time() + 900
        session[prefix + "_fails"] = 0
    else:
        session[prefix + "_fails"] = fails


def lookup_succeeded(prefix):
    session.pop(prefix + "_fails", None)
    session.pop(prefix + "_lock", None)


def get_config():
    if "site_config" not in g:
        g.site_config = get_db().execute(
            "SELECT * FROM site_config WHERE id = 1"
        ).fetchone()
    return g.site_config


def unread_count():
    if "unread_count" not in g:
        row = get_db().execute(
            "SELECT COUNT(*) FROM notices n WHERE n.status = 'published' "
            "AND NOT EXISTS (SELECT 1 FROM notice_reads r "
            "WHERE r.notice_id = n.id AND r.user_id = ?)",
            (g.user["id"],),
        ).fetchone()
        g.unread_count = row[0]
    return g.unread_count


def today_label():
    today = date.today()
    week = "一二三四五六日"[today.weekday()]
    return f"{today.month}月{today.day}日 周{week}"


def greeting():
    hour = datetime.now().hour
    if hour < 11:
        return "早上好"
    if hour < 18:
        return "下午好"
    return "晚上好"


def _login_redirect():
    if g.get("user"):
        return None
    return redirect(url_for("login", next=request.path))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        resp = _login_redirect()
        if resp:
            return resp
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            resp = _login_redirect()
            if resp:
                return resp
            if g.user["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


staff_required = role_required("admin", "superadmin")
counselor_required = role_required("counselor")
superadmin_required = role_required("superadmin")


@app.before_request
def load_user():
    if request.endpoint == "static":
        return
    g.user = None
    if "user_id" not in session:
        return
    row = get_db().execute(
        "SELECT id, username, role, status, created_at FROM users WHERE id = ?",
        (session["user_id"],),
    ).fetchone()
    if row is None or row["status"] != "active":
        session.clear()
        if request.endpoint not in (None, "login", "register", "privacy"):
            flash("登录状态已失效，请重新登录", "error")
            return redirect(url_for("login", next=request.path))
        return
    g.user = row
    session["username"] = row["username"]
    session["role"] = row["role"]


@app.before_request
def verify_csrf():
    if request.method != "POST":
        return
    token = request.form.get("_csrf") or request.headers.get("X-CSRF-Token", "")
    expected = session.get("_csrf", "")
    if not token or not expected or not hmac.compare_digest(str(token), str(expected)):
        abort(400, description="表单已过期，请刷新页面后重试。")


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self'; base-uri 'none'; form-action 'self'; "
        "frame-ancestors 'none'; object-src 'none'",
    )
    if request.path.startswith(("/feedback", "/tree", "/account", "/login",
                                "/register", "/qa", "/resources", "/admin/resources")):
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
    if app.config["SESSION_COOKIE_SECURE"]:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return resp


@app.context_processor
def inject_globals():
    counts = {"unread": 0, "feedback_new": 0, "tree_new": 0}
    user = g.get("user")
    if user:
        counts["unread"] = unread_count()
        if user["role"] in ("admin", "superadmin"):
            counts["feedback_new"] = get_db().execute(
                "SELECT COUNT(*) FROM feedback_threads WHERE status = 'new'"
            ).fetchone()[0]
            counts["resources_pending"] = get_db().execute(
                "SELECT COUNT(*) FROM resources WHERE status = 'pending'"
            ).fetchone()[0]
        elif user["role"] == "counselor":
            counts["tree_new"] = get_db().execute(
                "SELECT COUNT(*) FROM tree_threads WHERE status = 'new'"
            ).fetchone()[0]
    return {
        "site_name": get_config()["site_name"],
        "nav_counts": counts,
        "today_label": today_label(),
        "role_label": ROLE_LABELS.get(user["role"], "") if user else "",
    }


@app.template_filter("short_time")
def short_time(value):
    try:
        dt = datetime.strptime(value, FMT)
    except (TypeError, ValueError):
        return value or ""
    today = date.today()
    if dt.date() == today:
        return "今天 " + dt.strftime("%H:%M")
    if dt.date() == today - timedelta(days=1):
        return "昨天 " + dt.strftime("%H:%M")
    return dt.strftime("%m-%d %H:%M")


@app.template_filter("filesize")
def filesize(value):
    try:
        size = float(value)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
        size /= 1024
    return ""


@app.template_filter("days_until")
def days_until(value):
    if not value:
        return None
    try:
        target = date.fromisoformat(value)
    except ValueError:
        return None
    return (target - date.today()).days


# ---------------------------------------------------------------- auth

@app.route("/login", methods=["GET", "POST"])
def login():
    if g.get("user"):
        return redirect(url_for("home"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if not username or not password:
            return render_template("login.html", username=username,
                                   error="请输入用户名和密码"), 400

        key = hmac.new(app.secret_key.encode(), username.lower().encode(),
                       hashlib.sha256).hexdigest()
        throttle = get_db().execute(
            "SELECT fails, locked_until FROM login_throttle WHERE key = ?", (key,)
        ).fetchone()
        if throttle and throttle["locked_until"] > time.time():
            return render_template("login.html", username=username,
                                   error="尝试次数过多，请 15 分钟后再试"), 429

        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        ok = check_password_hash(user["password_hash"], password) if user \
            else check_password_hash(DUMMY_HASH, password)

        if not ok:
            fails = (throttle["fails"] if throttle else 0) + 1
            locked_until = 0
            if fails >= 5:
                locked_until = int(time.time()) + 900
                fails = 0
            get_db().execute(
                "INSERT INTO login_throttle (key, fails, locked_until) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET fails = excluded.fails, "
                "locked_until = excluded.locked_until",
                (key, fails, locked_until),
            )
            get_db().commit()
            return render_template("login.html", username=username,
                                   error="用户名或密码错误"), 401

        if user["status"] != "active":
            return render_template("login.html", username=username,
                                   error="账号已被封禁，请联系班委"), 403

        get_db().execute("DELETE FROM login_throttle WHERE key = ?", (key,))
        get_db().commit()
        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]
        session.permanent = True
        return redirect(safe_next(request.args.get("next")))
    return render_template("login.html", username="")


@app.route("/register", methods=["GET", "POST"])
def register():
    if g.get("user"):
        return redirect(url_for("home"))
    if request.method == "POST":
        if not allow_session_action("register_attempts", 10, 3600):
            return render_template("register.html", error="尝试次数过多，请稍后再试",
                                   values=request.form), 429

        username = (request.form.get("username") or "").strip()
        invite = (request.form.get("invite_code") or "").strip().upper()
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""
        cfg = get_config()

        error = None
        if not username or not invite or not password:
            error = "请填写完整信息"
        elif invite != cfg["invite_code"].upper():
            error = "邀请码不正确"
        elif not USERNAME_RE.match(username):
            error = "用户名需为 2–20 位，可用中英文、数字、下划线或短横线"
        elif not password_ok(password):
            error = "密码至少 8 位，且同时包含大写字母、小写字母和数字"
        elif password != password2:
            error = "两次输入的密码不一致"

        if error is None:
            try:
                get_db().execute(
                    "INSERT INTO users (username, password_hash, role, status, created_at) "
                    "VALUES (?, ?, 'member', 'active', ?)",
                    (username, generate_password_hash(password), now_str()),
                )
                get_db().commit()
            except sqlite3.IntegrityError:
                error = "用户名已被占用"
            else:
                flash("注册成功，请登录", "ok")
                return redirect(url_for("login"))

        return render_template("register.html", error=error, values=request.form), 400
    return render_template("register.html", values={})


@app.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/account", methods=["GET", "POST"])
@login_required
def account():
    error = None
    if request.method == "POST":
        current = request.form.get("current_password") or ""
        new = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""
        row = get_db().execute(
            "SELECT password_hash FROM users WHERE id = ?", (g.user["id"],)
        ).fetchone()
        if not check_password_hash(row["password_hash"], current):
            error = "当前密码不正确"
        elif not password_ok(new):
            error = "新密码至少 8 位，且同时包含大写字母、小写字母和数字"
        elif new != confirm:
            error = "两次输入的新密码不一致"
        else:
            get_db().execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash(new), g.user["id"]),
            )
            get_db().commit()
            session.clear()
            session["user_id"] = g.user["id"]
            session["username"] = g.user["username"]
            session["role"] = g.user["role"]
            session.permanent = True
            flash("密码已更新", "ok")
            return redirect(url_for("account"))
    return render_template("account.html", error=error)


# ---------------------------------------------------------------- notices

def notice_query(user_id, category="", limit=None):
    sql = ("SELECT n.*, (r.user_id IS NULL) AS unread "
           "FROM notices n LEFT JOIN notice_reads r "
           "ON r.notice_id = n.id AND r.user_id = ? "
           "WHERE n.status = 'published'")
    params = [user_id]
    if category:
        sql += " AND n.category = ?"
        params.append(category)
    sql += " ORDER BY n.pinned DESC, n.created_at DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return get_db().execute(sql, params).fetchall()


@app.get("/")
@login_required
def home():
    conn = get_db()
    notices = notice_query(g.user["id"], limit=3)
    hero = conn.execute(
        "SELECT * FROM notices WHERE status = 'published' AND deadline IS NOT NULL "
        "AND deadline >= ? ORDER BY pinned DESC, deadline ASC LIMIT 1",
        (date.today().isoformat(),),
    ).fetchone()
    if hero is None:
        hero = conn.execute(
            "SELECT * FROM notices WHERE status = 'published' AND pinned = 1 "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    since = (datetime.now() - timedelta(days=7)).strftime(FMT)
    stats = conn.execute(
        "SELECT COUNT(*) AS total, "
        "COALESCE(SUM(CASE WHEN status = 'replied' THEN 1 ELSE 0 END), 0) AS replied "
        "FROM feedback_threads WHERE created_at >= ?",
        (since,),
    ).fetchone()
    qa_open = conn.execute(
        "SELECT COUNT(*) FROM qa_threads WHERE status = 'open'"
    ).fetchone()[0]
    resource_count = conn.execute(
        "SELECT COUNT(*) FROM resources WHERE status = 'approved'"
    ).fetchone()[0]
    return render_template("home.html", notices=notices, hero=hero,
                           stats=stats, qa_open=qa_open,
                           resource_count=resource_count, greeting=greeting())


@app.get("/notices")
@login_required
def notices():
    category = request.args.get("category", "")
    if category not in CATEGORIES:
        category = ""
    rows = notice_query(g.user["id"], category)
    return render_template("notices.html", notices=rows, active_category=category)


@app.get("/notice/<int:nid>")
@login_required
def notice_view(nid):
    row = get_db().execute(
        "SELECT n.*, CASE u.role WHEN 'counselor' THEN '雪绒花' ELSE '班委' END AS author "
        "FROM notices n LEFT JOIN users u ON u.id = n.author_id WHERE n.id = ?",
        (nid,),
    ).fetchone()
    if row is None:
        abort(404)
    if row["status"] != "published" and g.user["role"] not in ("admin", "superadmin"):
        abort(404)
    if row["status"] == "published":
        get_db().execute(
            "INSERT OR IGNORE INTO notice_reads (notice_id, user_id, read_at) "
            "VALUES (?, ?, ?)",
            (nid, g.user["id"], now_str()),
        )
        get_db().commit()
    return render_template("notice_view.html", notice=row)


# ---------------------------------------------------------------- feedback

def render_feedback(**kwargs):
    payload = {
        "topics": TOPICS,
        "body": "",
        "topic": "",
        "error": None,
        "new_code": None,
        "locked": lookup_blocked("fb"),
    }
    payload.update(kwargs)
    return render_template("feedback.html", **payload)


@app.route("/feedback", methods=["GET", "POST"])
@login_required
def feedback():
    if request.method == "GET":
        return render_feedback()

    topic = request.form.get("topic", "")
    body = (request.form.get("body") or "").strip()
    error = None
    if topic not in TOPICS:
        error = "请选择反馈类型"
    elif not body:
        error = "请写点内容再提交"
    elif len(body) > 2000:
        error = "内容请控制在 2000 字以内"
    if error:
        return render_feedback(error=error, body=body, topic=topic), 400
    if not allow_session_action("feedback_submits", 5, 3600):
        return render_feedback(error="提交太频繁了，请过一会儿再试", body=body, topic=topic), 429

    raw, display, digest = make_code()
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO feedback_threads (code_hash, topic, status, created_at, last_at) "
        "VALUES (?, ?, 'new', ?, ?)",
        (digest, topic, now_str(), now_str()),
    )
    conn.execute(
        "INSERT INTO feedback_messages (thread_id, sender, body, created_at) "
        "VALUES (?, 'author', ?, ?)",
        (cursor.lastrowid, body, now_str()),
    )
    conn.commit()
    return render_feedback(new_code=display)


@app.post("/feedback/open")
@login_required
def feedback_open():
    if lookup_blocked("fb"):
        flash("回访码尝试次数过多，请 15 分钟后再试", "error")
        return redirect(url_for("feedback"))
    raw = normalize_code(request.form.get("code"))
    row = get_db().execute(
        "SELECT id FROM feedback_threads WHERE code_hash = ?", (code_digest(raw),)
    ).fetchone() if raw else None
    if row is None:
        lookup_failed("fb")
        flash("回访码无效，请检查后重试", "error")
        return redirect(url_for("feedback"))
    lookup_succeeded("fb")
    return redirect(url_for("feedback_thread", token=thread_token("feedback", row["id"])))


def load_feedback_thread(tid):
    thread = get_db().execute(
        "SELECT * FROM feedback_threads WHERE id = ?", (tid,)
    ).fetchone()
    if thread is None:
        abort(404)
    messages = get_db().execute(
        "SELECT * FROM feedback_messages WHERE thread_id = ? ORDER BY id", (tid,)
    ).fetchall()
    return thread, messages


@app.get("/feedback/t/<token>")
@login_required
def feedback_thread(token):
    tid = read_thread_token(token, "feedback")
    thread, messages = load_feedback_thread(tid)
    return render_template("feedback_thread.html", thread=thread,
                           messages=messages, token=token, view="author")


@app.post("/feedback/t/<token>/reply")
@login_required
def feedback_reply(token):
    tid = read_thread_token(token, "feedback")
    thread, _ = load_feedback_thread(tid)
    body = (request.form.get("body") or "").strip()
    if not body:
        flash("回复内容不能为空", "error")
        return redirect(url_for("feedback_thread", token=token))
    if len(body) > 2000:
        flash("回复请控制在 2000 字以内", "error")
        return redirect(url_for("feedback_thread", token=token))
    conn = get_db()
    conn.execute(
        "INSERT INTO feedback_messages (thread_id, sender, body, created_at) "
        "VALUES (?, 'author', ?, ?)",
        (tid, body, now_str()),
    )
    conn.execute(
        "UPDATE feedback_threads SET status = 'new', last_at = ? WHERE id = ?",
        (now_str(), tid),
    )
    conn.commit()
    return redirect(url_for("feedback_thread", token=token))


@app.post("/feedback/t/<token>/delete")
@login_required
def feedback_delete(token):
    tid = read_thread_token(token, "feedback")
    load_feedback_thread(tid)
    conn = get_db()
    conn.execute("DELETE FROM feedback_threads WHERE id = ?", (tid,))
    conn.commit()
    flash("这条反馈及其回复已删除", "ok")
    return redirect(url_for("feedback"))


# ---------------------------------------------------------------- tree hole

def render_tree(**kwargs):
    payload = {
        "moods": MOODS,
        "body": "",
        "mood": "",
        "error": None,
        "new_code": None,
        "locked": lookup_blocked("tree"),
    }
    payload.update(kwargs)
    return render_template("tree.html", **payload)


@app.route("/tree", methods=["GET", "POST"])
@login_required
def tree():
    if request.method == "GET":
        return render_tree()

    mood = request.form.get("mood", "")
    body = (request.form.get("body") or "").strip()
    error = None
    if mood not in MOODS:
        error = "请选择此刻的心情"
    elif not body:
        error = "信里还没有内容"
    elif len(body) > 3000:
        error = "内容请控制在 3000 字以内"
    if error:
        return render_tree(error=error, body=body, mood=mood), 400
    if not allow_session_action("tree_submits", 5, 3600):
        return render_tree(error="提交太频繁了，请过一会儿再试", body=body, mood=mood), 429

    raw, display, digest = make_code()
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO tree_threads (code_hash, mood, status, created_at, last_at) "
        "VALUES (?, ?, 'new', ?, ?)",
        (digest, mood, now_str(), now_str()),
    )
    conn.execute(
        "INSERT INTO tree_messages (thread_id, sender, body, created_at) "
        "VALUES (?, 'author', ?, ?)",
        (cursor.lastrowid, body, now_str()),
    )
    conn.commit()
    return render_tree(new_code=display)


@app.post("/tree/open")
@login_required
def tree_open():
    if lookup_blocked("tree"):
        flash("回访码尝试次数过多，请 15 分钟后再试", "error")
        return redirect(url_for("tree"))
    raw = normalize_code(request.form.get("code"))
    row = get_db().execute(
        "SELECT id FROM tree_threads WHERE code_hash = ?", (code_digest(raw),)
    ).fetchone() if raw else None
    if row is None:
        lookup_failed("tree")
        flash("回访码无效，请检查后重试", "error")
        return redirect(url_for("tree"))
    lookup_succeeded("tree")
    return redirect(url_for("tree_thread", token=thread_token("tree", row["id"])))


def load_tree_thread(tid):
    thread = get_db().execute(
        "SELECT * FROM tree_threads WHERE id = ?", (tid,)
    ).fetchone()
    if thread is None:
        abort(404)
    messages = get_db().execute(
        "SELECT * FROM tree_messages WHERE thread_id = ? ORDER BY id", (tid,)
    ).fetchall()
    return thread, messages


@app.get("/tree/t/<token>")
@login_required
def tree_thread(token):
    tid = read_thread_token(token, "tree")
    thread, messages = load_tree_thread(tid)
    return render_template("tree_thread.html", thread=thread,
                           messages=messages, token=token, view="author")


@app.post("/tree/t/<token>/reply")
@login_required
def tree_reply(token):
    tid = read_thread_token(token, "tree")
    load_tree_thread(tid)
    body = (request.form.get("body") or "").strip()
    if not body:
        flash("回复内容不能为空", "error")
        return redirect(url_for("tree_thread", token=token))
    if len(body) > 3000:
        flash("回复请控制在 3000 字以内", "error")
        return redirect(url_for("tree_thread", token=token))
    conn = get_db()
    conn.execute(
        "INSERT INTO tree_messages (thread_id, sender, body, created_at) "
        "VALUES (?, 'author', ?, ?)",
        (tid, body, now_str()),
    )
    conn.execute(
        "UPDATE tree_threads SET status = 'new', last_at = ? WHERE id = ?",
        (now_str(), tid),
    )
    conn.commit()
    return redirect(url_for("tree_thread", token=token))


@app.post("/tree/t/<token>/delete")
@login_required
def tree_delete(token):
    tid = read_thread_token(token, "tree")
    load_tree_thread(tid)
    conn = get_db()
    conn.execute("DELETE FROM tree_threads WHERE id = ?", (tid,))
    conn.commit()
    flash("这封信及对话已删除", "ok")
    return redirect(url_for("tree"))


@app.get("/tree/inbox")
@counselor_required
def tree_inbox():
    status = request.args.get("status", "new")
    if status not in ("new", "all"):
        status = "new"
    sql = ("SELECT t.*, (SELECT COUNT(*) FROM tree_messages m "
           "WHERE m.thread_id = t.id) AS msg_count, "
           "(SELECT body FROM tree_messages m WHERE m.thread_id = t.id "
           "ORDER BY m.id LIMIT 1) AS first_body "
           "FROM tree_threads t")
    params = []
    if status == "new":
        sql += " WHERE t.status = 'new'"
    sql += " ORDER BY t.last_at DESC"
    rows = get_db().execute(sql, params).fetchall()
    new_count = get_db().execute(
        "SELECT COUNT(*) FROM tree_threads WHERE status = 'new'"
    ).fetchone()[0]
    total = get_db().execute("SELECT COUNT(*) FROM tree_threads").fetchone()[0]
    return render_template("tree_inbox.html", threads=rows, active_status=status,
                           new_count=new_count, total=total)


@app.get("/tree/inbox/<int:tid>")
@counselor_required
def tree_inbox_thread(tid):
    thread, messages = load_tree_thread(tid)
    return render_template("tree_thread.html", thread=thread, messages=messages,
                           token=None, view="counselor")


@app.post("/tree/inbox/<int:tid>/reply")
@counselor_required
def tree_inbox_reply(tid):
    load_tree_thread(tid)
    body = (request.form.get("body") or "").strip()
    if not body:
        flash("回复内容不能为空", "error")
        return redirect(url_for("tree_inbox_thread", tid=tid))
    if len(body) > 3000:
        flash("回复请控制在 3000 字以内", "error")
        return redirect(url_for("tree_inbox_thread", tid=tid))
    conn = get_db()
    conn.execute(
        "INSERT INTO tree_messages (thread_id, sender, body, created_at) "
        "VALUES (?, 'counselor', ?, ?)",
        (tid, body, now_str()),
    )
    conn.execute(
        "UPDATE tree_threads SET status = 'replied', last_at = ? WHERE id = ?",
        (now_str(), tid),
    )
    conn.commit()
    flash("已回复", "ok")
    return redirect(url_for("tree_inbox_thread", tid=tid))


# ---------------------------------------------------------------- q&a

@app.get("/qa")
@login_required
def qa():
    status = request.args.get("status", "")
    if status not in ("", "open", "resolved"):
        status = ""
    sql = ("SELECT t.*, u.username AS author, u.role AS author_role, "
           "(SELECT COUNT(*) FROM qa_replies r WHERE r.thread_id = t.id) AS reply_count "
           "FROM qa_threads t LEFT JOIN users u ON u.id = t.author_id")
    params = []
    if status:
        sql += " WHERE t.status = ?"
        params.append(status)
    sql += (" ORDER BY CASE t.status WHEN 'open' THEN 0 ELSE 1 END, "
            "t.last_at DESC")
    rows = get_db().execute(sql, params).fetchall()
    counts = get_db().execute(
        "SELECT COALESCE(SUM(status = 'open'), 0) AS open_count, "
        "COALESCE(SUM(status = 'resolved'), 0) AS resolved_count FROM qa_threads"
    ).fetchone()
    return render_template("qa.html", threads=rows, active_status=status,
                           qa_counts=counts)


@app.route("/qa/new", methods=["GET", "POST"])
@login_required
def qa_new():
    values = {"topic": "study", "title": "", "body": ""}
    error = None
    code = 200
    if request.method == "POST":
        values = {
            "topic": request.form.get("topic", ""),
            "title": (request.form.get("title") or "").strip(),
            "body": (request.form.get("body") or "").strip(),
        }
        if values["topic"] not in TOPICS:
            error = "请选择问题类型"
        elif not (4 <= len(values["title"]) <= 120):
            error = "标题请控制在 4–120 字"
        elif not (10 <= len(values["body"]) <= 10000):
            error = "问题描述请控制在 10–10000 字"
        elif not allow_session_action("qa_posts", 10, 3600):
            error = "提问太频繁了，请过一会儿再试"
            code = 429
        else:
            conn = get_db()
            cursor = conn.execute(
                "INSERT INTO qa_threads (author_id, topic, title, body, status, "
                "created_at, last_at) VALUES (?, ?, ?, ?, 'open', ?, ?)",
                (g.user["id"], values["topic"], values["title"], values["body"],
                 now_str(), now_str()),
            )
            conn.commit()
            flash("问题已发布", "ok")
            return redirect(url_for("qa_thread", tid=cursor.lastrowid))
    if error and code == 200:
        code = 400
    return render_template("qa_new.html", values=values, error=error), code


def load_qa_thread(tid):
    thread = get_db().execute(
        "SELECT t.*, u.username AS author, u.role AS author_role "
        "FROM qa_threads t LEFT JOIN users u ON u.id = t.author_id WHERE t.id = ?",
        (tid,),
    ).fetchone()
    if thread is None:
        abort(404)
    return thread


@app.get("/qa/<int:tid>")
@login_required
def qa_thread(tid):
    thread = load_qa_thread(tid)
    replies = get_db().execute(
        "SELECT r.*, u.username AS author, u.role AS author_role "
        "FROM qa_replies r LEFT JOIN users u ON u.id = r.author_id "
        "WHERE r.thread_id = ? ORDER BY r.id",
        (tid,),
    ).fetchall()
    can_manage = (thread["author_id"] == g.user["id"]
                  or g.user["role"] in ("admin", "superadmin"))
    return render_template("qa_thread.html", thread=thread, replies=replies,
                           can_manage=can_manage)


@app.post("/qa/<int:tid>/reply")
@login_required
def qa_reply(tid):
    load_qa_thread(tid)
    body = (request.form.get("body") or "").strip()
    if not body:
        flash("回复内容不能为空", "error")
        return redirect(url_for("qa_thread", tid=tid))
    if len(body) > 5000:
        flash("回复请控制在 5000 字以内", "error")
        return redirect(url_for("qa_thread", tid=tid))
    if not allow_session_action("qa_replies", 30, 3600):
        flash("回复太频繁了，请过一会儿再试", "error")
        return redirect(url_for("qa_thread", tid=tid))
    conn = get_db()
    conn.execute(
        "INSERT INTO qa_replies (thread_id, author_id, body, created_at) "
        "VALUES (?, ?, ?, ?)",
        (tid, g.user["id"], body, now_str()),
    )
    conn.execute("UPDATE qa_threads SET last_at = ? WHERE id = ?", (now_str(), tid))
    conn.commit()
    flash("回复已发送", "ok")
    return redirect(url_for("qa_thread", tid=tid))


@app.post("/qa/<int:tid>/resolve")
@login_required
def qa_resolve(tid):
    thread = load_qa_thread(tid)
    if thread["author_id"] != g.user["id"] and g.user["role"] not in ("admin", "superadmin"):
        abort(403)
    new_status = "open" if thread["status"] == "resolved" else "resolved"
    conn = get_db()
    conn.execute("UPDATE qa_threads SET status = ?, last_at = ? WHERE id = ?",
                 (new_status, now_str(), tid))
    conn.commit()
    flash("已标记为解决" if new_status == "resolved" else "已重新打开", "ok")
    return redirect(url_for("qa_thread", tid=tid))


@app.post("/qa/<int:tid>/delete")
@login_required
def qa_delete(tid):
    thread = load_qa_thread(tid)
    if thread["author_id"] != g.user["id"] and g.user["role"] not in ("admin", "superadmin"):
        abort(403)
    conn = get_db()
    conn.execute("DELETE FROM qa_threads WHERE id = ?", (tid,))
    conn.commit()
    flash("问题及其回复已删除", "ok")
    return redirect(url_for("qa"))


# ---------------------------------------------------------------- resources

@app.get("/resources")
@login_required
def resources():
    keyword = (request.args.get("q") or "").strip()[:40]
    sql = ("SELECT r.*, u.username AS uploader FROM resources r "
           "LEFT JOIN users u ON u.id = r.uploader_id "
           "WHERE r.status = 'approved'")
    params = []
    if keyword:
        like = f"%{keyword}%"
        sql += (" AND (r.title LIKE ? OR r.subject LIKE ? OR r.description LIKE ?)")
        params += [like, like, like]
    sql += " ORDER BY r.created_at DESC"
    rows = get_db().execute(sql, params).fetchall()
    mine = get_db().execute(
        "SELECT * FROM resources WHERE uploader_id = ? ORDER BY created_at DESC",
        (g.user["id"],),
    ).fetchall()
    total = get_db().execute(
        "SELECT COUNT(*) FROM resources WHERE status = 'approved'"
    ).fetchone()[0]
    return render_template("resources.html", resources=rows, mine=mine,
                           keyword=keyword, total=total)


@app.route("/resources/upload", methods=["GET", "POST"])
@login_required
def resource_upload():
    values = {"title": "", "subject": "", "description": ""}
    error = None
    code = 200
    if request.method == "POST":
        values = {
            "title": (request.form.get("title") or "").strip(),
            "subject": (request.form.get("subject") or "").strip(),
            "description": (request.form.get("description") or "").strip(),
        }
        upload = request.files.get("file")
        filename = clean_upload_name(upload.filename) if upload and upload.filename else ""
        ext = upload_ext(filename)
        if not (2 <= len(values["title"]) <= 80):
            error = "资料名称请控制在 2–80 字"
        elif not (1 <= len(values["subject"]) <= 30):
            error = "请填写科目或用途，最多 30 字"
        elif len(values["description"]) > 500:
            error = "补充说明请控制在 500 字以内"
        elif not filename:
            error = "请选择要上传的文件"
        elif ext not in UPLOAD_TYPES:
            error = "不支持这种文件类型，请上传 PDF、Office 文档、压缩包、图片或文本"
        elif not allow_session_action("resource_uploads", 10, 3600):
            error = "上传太频繁了，请过一会儿再试"
            code = 429
        else:
            stored = secrets.token_hex(16) + "." + ext
            target = UPLOAD_DIR / stored
            upload.save(target)
            size = target.stat().st_size if target.exists() else 0
            if size == 0 or size > UPLOAD_MAX_BYTES:
                target.unlink(missing_ok=True)
                error = "文件为空或超过 20 MB"
            else:
                conn = get_db()
                conn.execute(
                    "INSERT INTO resources (uploader_id, title, description, subject, "
                    "filename, stored_name, size, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                    (g.user["id"], values["title"], values["description"],
                     values["subject"], filename, stored, size, now_str()),
                )
                conn.commit()
                flash("已上传，班委审核通过后会出现在资源列表里", "ok")
                return redirect(url_for("resources"))
    if error and code == 200:
        code = 400
    return render_template("resource_upload.html", values=values,
                           error=error, max_mb=UPLOAD_MAX_BYTES // (1024 * 1024)), code


@app.get("/resources/<int:rid>/download")
@login_required
def resource_download(rid):
    row = get_db().execute(
        "SELECT * FROM resources WHERE id = ?", (rid,)
    ).fetchone()
    if row is None:
        abort(404)
    allowed = (row["status"] == "approved"
               or row["uploader_id"] == g.user["id"]
               or g.user["role"] in ("admin", "superadmin"))
    path = UPLOAD_DIR / row["stored_name"]
    if not allowed or not path.is_file():
        abort(404)
    conn = get_db()
    conn.execute("UPDATE resources SET download_count = download_count + 1 WHERE id = ?",
                 (rid,))
    conn.commit()
    return send_from_directory(str(UPLOAD_DIR), row["stored_name"],
                               as_attachment=True, download_name=row["filename"])


@app.post("/resources/<int:rid>/delete")
@login_required
def resource_delete(rid):
    row = get_db().execute(
        "SELECT * FROM resources WHERE id = ?", (rid,)
    ).fetchone()
    if row is None:
        abort(404)
    if row["uploader_id"] != g.user["id"] and g.user["role"] not in ("admin", "superadmin"):
        abort(403)
    (UPLOAD_DIR / row["stored_name"]).unlink(missing_ok=True)
    conn = get_db()
    conn.execute("DELETE FROM resources WHERE id = ?", (rid,))
    conn.commit()
    flash("资料已删除", "ok")
    return redirect(url_for("resources"))


# ---------------------------------------------------------------- admin: resources

@app.get("/admin/resources")
@staff_required
def admin_resources():
    status = request.args.get("status", "pending")
    if status not in ("pending", "all"):
        status = "pending"
    sql = ("SELECT r.*, u.username AS uploader FROM resources r "
           "LEFT JOIN users u ON u.id = r.uploader_id")
    if status == "pending":
        sql += " WHERE r.status = 'pending'"
    sql += " ORDER BY CASE r.status WHEN 'pending' THEN 0 ELSE 1 END, r.created_at DESC"
    rows = get_db().execute(sql).fetchall()
    counts = get_db().execute(
        "SELECT COALESCE(SUM(status = 'pending'), 0) AS pending_count, "
        "COUNT(*) AS total FROM resources"
    ).fetchone()
    return render_template("admin_resources.html", resources=rows,
                           active_status=status, res_counts=counts)


@app.post("/admin/resources/<int:rid>/review")
@staff_required
def admin_resource_review(rid):
    row = get_db().execute(
        "SELECT * FROM resources WHERE id = ?", (rid,)
    ).fetchone()
    if row is None:
        abort(404)
    if row["status"] != "pending":
        flash("这条资料已经处理过了", "error")
        return redirect(url_for("admin_resources"))
    action = request.form.get("action", "")
    if action not in ("approve", "reject"):
        abort(400)
    conn = get_db()
    if action == "approve":
        conn.execute(
            "UPDATE resources SET status = 'approved', reviewed_at = ?, "
            "reviewed_by = ? WHERE id = ?",
            (now_str(), g.user["id"], rid),
        )
        flash("已通过，资料现在对全班可见", "ok")
    else:
        (UPLOAD_DIR / row["stored_name"]).unlink(missing_ok=True)
        conn.execute(
            "UPDATE resources SET status = 'rejected', reviewed_at = ?, "
            "reviewed_by = ? WHERE id = ?",
            (now_str(), g.user["id"], rid),
        )
        flash("已退回，文件已从服务器删除", "ok")
    conn.commit()
    return redirect(url_for("admin_resources"))


@app.post("/admin/resources/<int:rid>/delete")
@staff_required
def admin_resource_delete(rid):
    row = get_db().execute(
        "SELECT * FROM resources WHERE id = ?", (rid,)
    ).fetchone()
    if row is None:
        abort(404)
    (UPLOAD_DIR / row["stored_name"]).unlink(missing_ok=True)
    conn = get_db()
    conn.execute("DELETE FROM resources WHERE id = ?", (rid,))
    conn.commit()
    flash("资料已删除", "ok")
    return redirect(url_for("admin_resources"))


# ---------------------------------------------------------------- admin: notices

@app.get("/admin")
@staff_required
def admin_index():
    return redirect(url_for("admin_notices"))


@app.get("/admin/notices")
@staff_required
def admin_notices():
    rows = get_db().execute(
        "SELECT n.*, CASE u.role WHEN 'counselor' THEN '雪绒花' ELSE '班委' END AS author "
        "FROM notices n LEFT JOIN users u ON u.id = n.author_id "
        "ORDER BY n.pinned DESC, n.created_at DESC"
    ).fetchall()
    return render_template("admin_notices.html", notices=rows)


def notice_form_values(source=None):
    if source is None:
        return {"category": "important", "title": "", "body": "", "pinned": False,
                "deadline": "", "status": "published"}
    if isinstance(source, dict):
        return source
    return {
        "category": source["category"],
        "title": source["title"],
        "body": source["body"],
        "pinned": bool(source["pinned"]),
        "deadline": source["deadline"] or "",
        "status": source["status"],
    }


def validate_notice(values):
    errors = []
    if values["category"] not in CATEGORIES:
        errors.append("请选择通知分类")
    title = (values["title"] or "").strip()
    body = (values["body"] or "").strip()
    if not (2 <= len(title) <= 120):
        errors.append("标题需为 2–120 字")
    if not (2 <= len(body) <= 20000):
        errors.append("正文需为 2–20000 字")
    if values["status"] not in ("draft", "published"):
        errors.append("状态不正确")
    deadline = (values["deadline"] or "").strip()
    if deadline:
        if not DATE_RE.match(deadline):
            errors.append("截止日期格式应为 YYYY-MM-DD")
        else:
            try:
                date.fromisoformat(deadline)
            except ValueError:
                errors.append("截止日期无效")
    return errors


@app.route("/admin/notices/new", methods=["GET", "POST"])
@staff_required
def admin_notice_new():
    values = notice_form_values()
    if request.method == "POST":
        values = {
            "category": request.form.get("category", ""),
            "title": request.form.get("title", ""),
            "body": request.form.get("body", ""),
            "pinned": bool(request.form.get("pinned")),
            "deadline": request.form.get("deadline", ""),
            "status": request.form.get("status", "published"),
        }
        errors = validate_notice(values)
        if errors:
            return render_template("admin_notice_form.html", values=values,
                                   errors=errors, mode="new"), 400
        conn = get_db()
        conn.execute(
            "INSERT INTO notices (category, title, body, pinned, deadline, status, "
            "author_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (values["category"], values["title"].strip(), values["body"].strip(),
             1 if values["pinned"] else 0, values["deadline"].strip() or None,
             values["status"], g.user["id"], now_str(), now_str()),
        )
        conn.commit()
        flash("通知已发布" if values["status"] == "published" else "草稿已保存", "ok")
        return redirect(url_for("admin_notices"))
    return render_template("admin_notice_form.html", values=values, errors=[], mode="new")


@app.route("/admin/notices/<int:nid>/edit", methods=["GET", "POST"])
@staff_required
def admin_notice_edit(nid):
    conn = get_db()
    row = conn.execute("SELECT * FROM notices WHERE id = ?", (nid,)).fetchone()
    if row is None:
        abort(404)
    values = notice_form_values(row)
    if request.method == "POST":
        values = {
            "category": request.form.get("category", ""),
            "title": request.form.get("title", ""),
            "body": request.form.get("body", ""),
            "pinned": bool(request.form.get("pinned")),
            "deadline": request.form.get("deadline", ""),
            "status": request.form.get("status", "published"),
        }
        errors = validate_notice(values)
        if errors:
            return render_template("admin_notice_form.html", values=values,
                                   errors=errors, mode="edit", notice_id=nid), 400
        conn.execute(
            "UPDATE notices SET category = ?, title = ?, body = ?, pinned = ?, "
            "deadline = ?, status = ?, updated_at = ? WHERE id = ?",
            (values["category"], values["title"].strip(), values["body"].strip(),
             1 if values["pinned"] else 0, values["deadline"].strip() or None,
             values["status"], now_str(), nid),
        )
        conn.commit()
        flash("通知已更新", "ok")
        return redirect(url_for("admin_notices"))
    return render_template("admin_notice_form.html", values=values, errors=[],
                           mode="edit", notice_id=nid)


@app.post("/admin/notices/<int:nid>/delete")
@staff_required
def admin_notice_delete(nid):
    conn = get_db()
    if conn.execute("SELECT id FROM notices WHERE id = ?", (nid,)).fetchone() is None:
        abort(404)
    conn.execute("DELETE FROM notices WHERE id = ?", (nid,))
    conn.commit()
    flash("通知已删除", "ok")
    return redirect(url_for("admin_notices"))


# ---------------------------------------------------------------- admin: feedback

@app.get("/admin/feedback")
@staff_required
def admin_feedback():
    status = request.args.get("status", "new")
    if status not in ("new", "all"):
        status = "new"
    sql = ("SELECT t.*, "
           "(SELECT COUNT(*) FROM feedback_messages m WHERE m.thread_id = t.id) AS msg_count, "
           "(SELECT body FROM feedback_messages m WHERE m.thread_id = t.id "
           "ORDER BY m.id DESC LIMIT 1) AS last_body "
           "FROM feedback_threads t")
    if status == "new":
        sql += " WHERE t.status = 'new'"
    sql += " ORDER BY t.last_at DESC"
    rows = get_db().execute(sql).fetchall()
    new_count = get_db().execute(
        "SELECT COUNT(*) FROM feedback_threads WHERE status = 'new'"
    ).fetchone()[0]
    total = get_db().execute("SELECT COUNT(*) FROM feedback_threads").fetchone()[0]
    return render_template("admin_feedback.html", threads=rows,
                           active_status=status, new_count=new_count, total=total)


@app.get("/admin/feedback/<int:tid>")
@staff_required
def admin_feedback_thread(tid):
    thread, messages = load_feedback_thread(tid)
    return render_template("feedback_thread.html", thread=thread, messages=messages,
                           token=None, view="staff")


@app.post("/admin/feedback/<int:tid>/reply")
@staff_required
def admin_feedback_reply(tid):
    load_feedback_thread(tid)
    body = (request.form.get("body") or "").strip()
    if not body:
        flash("回复内容不能为空", "error")
        return redirect(url_for("admin_feedback_thread", tid=tid))
    if len(body) > 2000:
        flash("回复请控制在 2000 字以内", "error")
        return redirect(url_for("admin_feedback_thread", tid=tid))
    conn = get_db()
    conn.execute(
        "INSERT INTO feedback_messages (thread_id, sender, body, created_at) "
        "VALUES (?, 'committee', ?, ?)",
        (tid, body, now_str()),
    )
    conn.execute(
        "UPDATE feedback_threads SET status = 'replied', last_at = ? WHERE id = ?",
        (now_str(), tid),
    )
    conn.commit()
    flash("已回复该反馈", "ok")
    return redirect(url_for("admin_feedback_thread", tid=tid))


# ---------------------------------------------------------------- admin: users

@app.get("/admin/users")
@superadmin_required
def admin_users():
    rows = get_db().execute(
        "SELECT id, username, role, status, created_at FROM users ORDER BY id"
    ).fetchall()
    return render_template("admin_users.html", users=rows)


@app.post("/admin/users/<int:uid>/ban")
@superadmin_required
def admin_user_ban(uid):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if user is None:
        abort(404)
    if uid == g.user["id"]:
        flash("不能封禁自己", "error")
    elif user["role"] in ("counselor", "superadmin"):
        flash("该账号由服务器命令管理，不能在此封禁", "error")
    else:
        new_status = "active" if user["status"] == "banned" else "banned"
        conn.execute("UPDATE users SET status = ? WHERE id = ?", (new_status, uid))
        conn.commit()
        flash(("已解封 " if new_status == "active" else "已封禁 ") + user["username"], "ok")
    return redirect(url_for("admin_users"))


@app.post("/admin/users/<int:uid>/rename")
@superadmin_required
def admin_user_rename(uid):
    name = (request.form.get("username") or "").strip()
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if user is None:
        abort(404)
    if user["role"] in ("counselor", "superadmin"):
        flash("该账号由服务器命令管理，不能在此改名", "error")
    elif not USERNAME_RE.match(name):
        flash("用户名需为 2–20 位，可用中英文、数字、下划线或短横线", "error")
    else:
        try:
            conn.execute("UPDATE users SET username = ? WHERE id = ?", (name, uid))
            conn.commit()
            flash("用户名已更新", "ok")
        except sqlite3.IntegrityError:
            flash("用户名已存在", "error")
    return redirect(url_for("admin_users"))


@app.post("/admin/users/<int:uid>/role")
@superadmin_required
def admin_user_role(uid):
    role = request.form.get("role", "")
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if user is None:
        abort(404)
    if uid == g.user["id"]:
        flash("不能修改自己的角色", "error")
    elif user["role"] in ("counselor", "superadmin"):
        flash("该账号角色由服务器命令管理", "error")
    elif role not in ("member", "admin"):
        flash("只能设置为同学或班委", "error")
    else:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, uid))
        conn.commit()
        flash("角色已更新", "ok")
    return redirect(url_for("admin_users"))


# ---------------------------------------------------------------- admin: settings

@app.route("/admin/settings", methods=["GET", "POST"])
@superadmin_required
def admin_settings():
    cfg = get_config()
    error = None
    if request.method == "POST":
        code = (request.form.get("invite_code") or "").strip().upper()
        if not INVITE_RE.match(code):
            error = "邀请码需为 4–32 位，只能使用字母、数字、下划线或短横线"
        elif code == cfg["invite_code"]:
            flash("邀请码没有变化", "info")
            return redirect(url_for("admin_settings"))
        else:
            conn = get_db()
            conn.execute("UPDATE site_config SET invite_code = ? WHERE id = 1", (code,))
            conn.commit()
            flash("邀请码已更新，旧邀请码立即失效", "ok")
            return redirect(url_for("admin_settings"))
    return render_template("admin_settings.html", invite_code=cfg["invite_code"], error=error)


# ---------------------------------------------------------------- misc pages

@app.get("/privacy")
def privacy():
    return render_template("privacy.html")


@app.errorhandler(400)
def error_400(err):
    return render_template("error.html", code=400, title="请求已过期",
                           message=getattr(err, "description", "请刷新页面后重试。")), 400


@app.errorhandler(403)
def error_403(err):
    return render_template("error.html", code=403, title="没有访问权限",
                           message="这个页面不对你的账号开放。"), 403


@app.errorhandler(404)
def error_404(err):
    return render_template("error.html", code=404, title="页面不存在",
                           message="链接可能已经失效，或者内容已被删除。"), 404


@app.errorhandler(413)
def error_413(err):
    return render_template("error.html", code=413, title="提交内容过大",
                           message="单个文件不能超过 20 MB，请压缩后再试。"), 413


@app.errorhandler(500)
def error_500(err):
    return render_template("error.html", code=500, title="服务器出错了",
                           message="请稍后再试；如果持续出现，请联系班委。"), 500


# ---------------------------------------------------------------- CLI

@app.cli.command("set-invite")
@click.argument("code")
def cli_set_invite(code):
    """修改注册邀请码，例如：flask --app app set-invite CLASS2027"""
    code = code.strip().upper()
    if not INVITE_RE.match(code):
        raise click.ClickException("邀请码需为 4–32 位，只能使用字母、数字、下划线或短横线")
    conn = db.connect()
    conn.execute("UPDATE site_config SET invite_code = ? WHERE id = 1", (code,))
    conn.commit()
    conn.close()
    click.echo(f"邀请码已更新为：{code}")


@app.cli.command("set-site")
@click.argument("name")
def cli_set_site(name):
    """修改站点名称。"""
    name = name.strip()
    if not name:
        raise click.ClickException("站点名称不能为空")
    conn = db.connect()
    conn.execute("UPDATE site_config SET site_name = ? WHERE id = 1", (name,))
    conn.commit()
    conn.close()
    click.echo(f"站点名称已更新为：{name}")


@app.cli.command("reset-password")
@click.argument("username")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
def cli_reset_password(username, password):
    """重置任意账号的密码。"""
    if not password_ok(password):
        raise click.ClickException("密码至少 8 位，且同时包含大写字母、小写字母和数字")
    conn = db.connect()
    user = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if user is None:
        conn.close()
        raise click.ClickException("用户不存在")
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                 (generate_password_hash(password), user["id"]))
    conn.commit()
    conn.close()
    click.echo(f"{username} 的密码已重置")


@app.cli.command("set-role")
@click.argument("username")
@click.argument("role", type=click.Choice(["member", "admin", "counselor", "superadmin"]))
def cli_set_role(username, role):
    """设置角色。counselor 只能有一个，用于雪绒花的独立账号。"""
    conn = db.connect()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if user is None:
        conn.close()
        raise click.ClickException("用户不存在")
    if role == "counselor":
        other = conn.execute(
            "SELECT username FROM users WHERE role = 'counselor' AND id != ?", (user["id"],)
        ).fetchone()
        if other:
            conn.close()
            raise click.ClickException(
                f"已存在雪绒花账号 {other['username']}；请先把原账号改为 member"
            )
    if user["role"] == "superadmin" and role != "superadmin":
        remaining = conn.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'superadmin' AND id != ?", (user["id"],)
        ).fetchone()[0]
        if remaining == 0:
            conn.close()
            raise click.ClickException("不能移除最后一个超级管理员")
    conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user["id"]))
    conn.commit()
    conn.close()
    click.echo(f"{username} 的角色已设置为 {role}")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
