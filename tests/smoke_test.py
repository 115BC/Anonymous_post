"""端到端冒烟测试（不依赖 pytest）。

运行：D:/anaconda/python.exe tests/smoke_test.py
"""

import io
import os
import re
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TEST_DB = Path(__file__).resolve().parent / "tmp_smoke.db"
TEST_UPLOADS = Path(__file__).resolve().parent / "tmp_uploads"
for suffix in ("", "-wal", "-shm"):
    try:
        Path(str(TEST_DB) + suffix).unlink()
    except FileNotFoundError:
        pass
shutil.rmtree(TEST_UPLOADS, ignore_errors=True)

os.environ["CLASSSITE_DB"] = str(TEST_DB)
os.environ["CLASSSITE_UPLOADS"] = str(TEST_UPLOADS)
os.environ["SECRET_KEY"] = "smoke-test-secret"
os.environ["INVITE_CODE"] = "TESTCODE"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "Admin12345"
os.environ["COOKIE_SECURE"] = "0"

sys.path.insert(0, str(BASE))
import app as application  # noqa: E402
import db  # noqa: E402

application.app.config.update(TESTING=True)
client = application.app.test_client()

CSRF_RE = re.compile(r'name="_csrf" value="([^"]+)"')
CODE_RE = re.compile(r'data-code="([A-Z0-9]{4}-[A-Z0-9]{4})"')


def text(resp):
    return resp.get_data(as_text=True)


def token_from(html):
    match = CSRF_RE.search(html)
    assert match, "页面里没有 CSRF token"
    return match.group(1)


def login(username, password):
    page = text(client.get("/login"))
    token = token_from(page)
    resp = client.post("/login", data={
        "_csrf": token, "username": username, "password": password,
    }, follow_redirects=True)
    assert resp.status_code == 200, resp.status_code
    return token_from(text(resp))


def logout(token):
    resp = client.post("/logout", data={"_csrf": token}, follow_redirects=True)
    assert resp.status_code == 200
    return text(resp)


def db_row(sql, params=()):
    conn = db.connect()
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def db_all(sql, params=()):
    conn = db.connect()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


print("1. 注册与登录")
page = client.get("/register")
assert page.status_code == 200 and "注册" in text(page)
token = token_from(text(page))
assert client.post("/register", data={"username": "x"}).status_code == 400, "无 CSRF 应被拒绝"

resp = client.post("/register", data={
    "_csrf": token, "invite_code": "TESTCODE", "username": "student1",
    "password": "Passw0rdX", "password2": "Passw0rdX",
}, follow_redirects=True)
assert resp.status_code == 200 and "注册成功" in text(resp)

member_token = login("student1", "Passw0rdX")
home = text(client.get("/"))
assert "最新通知" in home and "匿名反馈" in home

print("2. 通知已读")
notice = db_row("SELECT * FROM notices WHERE status='published' ORDER BY id LIMIT 1")
assert notice is not None
assert client.get("/notice/%d" % notice["id"]).status_code == 200
read = db_row("SELECT * FROM notice_reads WHERE notice_id=? AND user_id=("
              "SELECT id FROM users WHERE username='student1')", (notice["id"],))
assert read is not None, "打开通知后应写入已读记录"

print("3. 匿名反馈闭环")
feedback_page = text(client.get("/feedback"))
member_token = token_from(feedback_page)
resp = client.post("/feedback", data={
    "_csrf": member_token, "topic": "study", "body": "希望晚自习多留一间教室。",
})
assert resp.status_code == 200
fed_code = CODE_RE.search(text(resp))
assert fed_code, "提交成功后应显示回访码"
fed_code = fed_code.group(1)
thread = db_row("SELECT * FROM feedback_threads ORDER BY id DESC LIMIT 1")
assert thread is not None
assert "user_id" not in [r["name"] for r in db_all("PRAGMA table_info(feedback_threads)")]
assert "ip" not in [r["name"] for r in db_all("PRAGMA table_info(feedback_threads)")]
assert thread["code_hash"] != fed_code.replace("-", ""), "回访码不能明文入库"

resp = client.post("/feedback/open", data={"_csrf": member_token, "code": fed_code},
                   follow_redirects=True)
assert resp.status_code == 200 and "希望晚自习多留一间教室" in text(resp)
thread_token = token_from(text(resp))
resp = client.post(resp.request.path + "/reply", data={
    "_csrf": thread_token, "body": "补充：周末也可以。",
}, follow_redirects=True)
assert resp.status_code == 200 and "补充：周末也可以" in text(resp)

resp = client.post("/feedback/open", data={"_csrf": member_token, "code": "AAAA-AAAA"},
                   follow_redirects=True)
assert resp.status_code == 200 and "回访码无效" in text(resp)

print("4. 树洞提交")
tree_page = text(client.get("/tree"))
member_token = token_from(tree_page)
resp = client.post("/tree", data={
    "_csrf": member_token, "mood": "tired", "body": "最近有点睡不着，想找人说说话。",
})
assert resp.status_code == 200
tree_code = CODE_RE.search(text(resp))
assert tree_code
tree_code = tree_code.group(1)
tree_thread_row = db_row("SELECT * FROM tree_threads ORDER BY id DESC LIMIT 1")
assert tree_thread_row is not None

print("4b. 问题交流与资源上传")
qa_page = text(client.get("/qa"))
assert "问题交流" in qa_page
member_token = token_from(qa_page)
resp = client.post("/qa/new", data={
    "_csrf": member_token, "topic": "study",
    "title": "数据结构作业第 3 题怎么理解？",
    "body": "题目要求用栈实现队列，但我不太理解为什么需要两个栈。",
}, follow_redirects=True)
assert resp.status_code == 200 and "数据结构作业第 3 题" in text(resp), "问题应发布成功"
qa_row = db_row("SELECT id, author_id FROM qa_threads ORDER BY id DESC LIMIT 1")
assert qa_row is not None and qa_row["author_id"] is not None, "问答应保存作者"

upload_page = text(client.get("/resources/upload"))
member_token = token_from(upload_page)
resp = client.post("/resources/upload", data={
    "_csrf": member_token,
    "title": "数据结构期中复习提纲",
    "subject": "数据结构",
    "description": "第 1–4 章的知识点整理。",
    "file": (io.BytesIO("栈与队列复习要点\n".encode("utf-8")), "review.txt"),
}, content_type="multipart/form-data", follow_redirects=True)
assert resp.status_code == 200 and "班委审核" in text(resp), "上传后应提示待审核"
res_row = db_row("SELECT * FROM resources ORDER BY id DESC LIMIT 1")
assert res_row is not None and res_row["status"] == "pending"
assert res_row["filename"] == "review.txt"
assert (application.UPLOAD_DIR / res_row["stored_name"]).is_file(), "文件应存入私有目录"

resp = client.post("/resources/upload", data={
    "_csrf": member_token, "title": "坏文件", "subject": "测试",
    "file": (io.BytesIO(b"x"), "evil.exe"),
}, content_type="multipart/form-data")
assert resp.status_code == 400 and "不支持" in text(resp), "可执行文件应被拒绝"

print("5. 管理员权限")
logout(member_token)
admin_token = login("admin", "Admin12345")
admin_notices_page = client.get("/admin/notices")
assert admin_notices_page.status_code == 200
admin_token = token_from(text(admin_notices_page))

resp = client.post("/admin/notices/new", data={
    "_csrf": admin_token, "category": "important", "title": "测试通知标题",
    "body": "这是一条用于冒烟测试的通知。", "status": "published",
}, follow_redirects=True)
assert resp.status_code == 200 and "测试通知标题" in text(resp)

assert client.get("/admin/feedback").status_code == 200
fed_id = db_row("SELECT id FROM feedback_threads ORDER BY id DESC LIMIT 1")["id"]
fed_view = client.get("/admin/feedback/%d" % fed_id)
assert fed_view.status_code == 200 and "匿名同学" in text(fed_view)
admin_token = token_from(text(fed_view))
resp = client.post("/admin/feedback/%d/reply" % fed_id, data={
    "_csrf": admin_token, "body": "收到，下周开始加开一间。",
}, follow_redirects=True)
assert resp.status_code == 200 and "收到，下周开始加开一间" in text(resp)
assert db_row("SELECT status FROM feedback_threads WHERE id=?", (fed_id,))["status"] == "replied"

resp = client.get("/tree/inbox")
assert resp.status_code == 403, "超级管理员不能进入树洞信箱"
assert client.get("/admin/users").status_code == 200

print("5b. 资源审核与问答回复")
assert "数据结构期中复习提纲" not in text(client.get("/resources")), "待审核资料不应公开"
admin_res_page = text(client.get("/admin/resources"))
assert "数据结构期中复习提纲" in admin_res_page
admin_token = token_from(admin_res_page)
resp = client.post("/admin/resources/%d/review" % res_row["id"], data={
    "_csrf": admin_token, "action": "approve",
}, follow_redirects=True)
assert resp.status_code == 200 and "已通过" in text(resp)
assert db_row("SELECT status FROM resources WHERE id=?", (res_row["id"],))["status"] == "approved"

qa_view = text(client.get("/qa/%d" % qa_row["id"]))
assert "数据结构作业第 3 题" in qa_view
admin_token = token_from(qa_view)
resp = client.post("/qa/%d/reply" % qa_row["id"], data={
    "_csrf": admin_token, "body": "用两个栈可以反转顺序，出队时把入队栈倒到出队栈。",
}, follow_redirects=True)
assert resp.status_code == 200 and "两个栈" in text(resp)

print("5c. 邀请码设置")
settings_page = text(client.get("/admin/settings"))
assert "当前邀请码" in settings_page and "TESTCODE" in settings_page
admin_token = token_from(settings_page)
resp = client.post("/admin/settings", data={
    "_csrf": admin_token, "invite_code": "newcode2027",
}, follow_redirects=True)
assert resp.status_code == 200 and "邀请码已更新" in text(resp)
assert "NEWCODE2027" in text(resp), "邀请码应自动转为大写并立即生效"
assert db_row("SELECT invite_code FROM site_config WHERE id=1")["invite_code"] == "NEWCODE2027"
admin_token = token_from(text(client.get("/admin/settings")))
resp = client.post("/admin/settings", data={"_csrf": admin_token, "invite_code": "ab"})
assert resp.status_code == 200 and "4–32" in text(resp), "过短的邀请码应被拒绝"

print("6. 雪绒花权限")
logout(admin_token)
conn = db.connect()
from werkzeug.security import generate_password_hash  # noqa: E402
conn.execute(
    "INSERT INTO users (username, password_hash, role, status, created_at) "
    "VALUES (?, ?, 'counselor', 'active', ?)",
    ("xueronghua", generate_password_hash("Counsel0rX"), db.now_str()),
)
conn.commit()
conn.close()

counselor_token = login("xueronghua", "Counsel0rX")
inbox = client.get("/tree/inbox")
assert inbox.status_code == 200 and "想找人说说话" in text(inbox)
counselor_token = token_from(text(inbox))
tree_id = tree_thread_row["id"]
tree_view = client.get("/tree/inbox/%d" % tree_id)
assert tree_view.status_code == 200
counselor_token = token_from(text(tree_view))
resp = client.post("/tree/inbox/%d/reply" % tree_id, data={
    "_csrf": counselor_token, "body": "我在，慢慢说。",
}, follow_redirects=True)
assert resp.status_code == 200 and "我在，慢慢说" in text(resp)
assert client.get("/admin/notices").status_code == 403
assert client.get("/admin/feedback").status_code == 403
assert client.get("/admin/resources").status_code == 403
assert client.get("/admin/settings").status_code == 403

print("7. 作者凭回访码看到双方回复")
logout(counselor_token)
member_token = login("student1", "Passw0rdX")
resp = client.post("/feedback/open", data={"_csrf": member_token, "code": fed_code},
                   follow_redirects=True)
assert "收到，下周开始加开一间" in text(resp)
resp = client.post("/tree/open", data={"_csrf": member_token, "code": tree_code},
                   follow_redirects=True)
assert "我在，慢慢说" in text(resp)

qa_view = text(client.get("/qa/%d" % qa_row["id"]))
assert "两个栈" in qa_view, "提问者应看到班委回复"
member_token = token_from(qa_view)
resp = client.post("/qa/%d/resolve" % qa_row["id"], data={"_csrf": member_token},
                   follow_redirects=True)
assert resp.status_code == 200 and "已标记为解决" in text(resp)
assert db_row("SELECT status FROM qa_threads WHERE id=?", (qa_row["id"],))["status"] == "resolved"

assert "数据结构期中复习提纲" in text(client.get("/resources"))
download = client.get("/resources/%d/download" % res_row["id"])
assert download.status_code == 200
assert download.data == "栈与队列复习要点\n".encode("utf-8")
assert "attachment" in download.headers.get("Content-Disposition", "")
assert db_row("SELECT download_count FROM resources WHERE id=?",
              (res_row["id"],))["download_count"] == 1

print("8. 安全边界")
resp = client.post("/feedback", data={"topic": "study", "body": "无 token"})
assert resp.status_code == 400, "缺少 CSRF 的表单必须被拒绝"
resp = client.get("/feedback/t/not-a-real-token")
assert resp.status_code == 404
resp = client.get("/admin/users")
assert resp.status_code == 403, "普通同学不能进用户管理"
assert client.get("/admin/resources").status_code == 403
resp = client.post("/resources/upload", data={"title": "无 token", "subject": "测试"})
assert resp.status_code == 400, "上传也必须校验 CSRF"

print("9. 管理员改密后旧密码失效")
new_token = token_from(text(client.get("/account")))
resp = client.post("/account", data={
    "_csrf": new_token, "current_password": "Passw0rdX",
    "new_password": "NewPassw0rd1", "confirm_password": "NewPassw0rd1",
}, follow_redirects=True)
assert "密码已更新" in text(resp)
logout(token_from(text(resp)))
resp = client.post("/login", data={"_csrf": token_from(text(client.get("/login"))),
                                   "username": "student1", "password": "Passw0rdX"})
assert resp.status_code in (401, 200) and "用户名或密码错误" in text(resp)
login("student1", "NewPassw0rd1")

shutil.rmtree(TEST_UPLOADS, ignore_errors=True)
print("\n全部冒烟测试通过。")
