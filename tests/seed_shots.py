"""为截图准备演示数据（独立数据库，不影响 instance/）。"""

import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("CLASSSITE_DB", str(Path(__file__).resolve().parent / "shot.db"))
os.environ.setdefault("CLASSSITE_UPLOADS", str(Path(__file__).resolve().parent / "shot_uploads"))
os.environ.setdefault("SECRET_KEY", "shot-secret")
os.environ.setdefault("ADMIN_PASSWORD", "Admin12345")
os.environ.setdefault("INVITE_CODE", "SHOTCODE")

import app as mod  # noqa: E402
import db as dbmod  # noqa: E402
from flask.sessions import SecureCookieSessionInterface  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

conn = dbmod.connect()
now = dbmod.now_str()

conn.execute(
    "INSERT OR IGNORE INTO users (username, password_hash, role, status, created_at) "
    "VALUES (?, ?, 'member', 'active', ?)",
    ("student", generate_password_hash("Student123"), now),
)
conn.execute(
    "INSERT OR IGNORE INTO users (username, password_hash, role, status, created_at) "
    "VALUES (?, ?, 'counselor', 'active', ?)",
    ("xueronghua", generate_password_hash("Counsel0rX"), now),
)

if conn.execute("SELECT COUNT(*) FROM feedback_threads").fetchone()[0] == 0:
    cur = conn.execute(
        "INSERT INTO feedback_threads (code_hash, topic, status, created_at, last_at) "
        "VALUES (?, 'class', 'replied', ?, ?)",
        (mod.code_digest("K7F29QX3"), now, now),
    )
    fid = cur.lastrowid
    conn.execute(
        "INSERT INTO feedback_messages (thread_id, sender, body, created_at) VALUES (?, 'author', ?, ?)",
        (fid, "晚自习教室能不能多留一间？现在图书馆闭馆后，想小组讨论就没有地方了。", now),
    )
    conn.execute(
        "INSERT INTO feedback_messages (thread_id, sender, body, created_at) VALUES (?, 'committee', ?, ?)",
        (fid, "收到，已经和学委确认过。下周三开始，周三和周五晚上会多开一间教室，具体教室号会发在通知里。", now),
    )

if conn.execute("SELECT COUNT(*) FROM tree_threads").fetchone()[0] == 0:
    cur = conn.execute(
        "INSERT INTO tree_threads (code_hash, mood, status, created_at, last_at) "
        "VALUES (?, 'tired', 'replied', ?, ?)",
        (mod.code_digest("M4XK8QTR"), now, now),
    )
    tid = cur.lastrowid
    conn.execute(
        "INSERT INTO tree_messages (thread_id, sender, body, created_at) VALUES (?, 'author', ?, ?)",
        (tid, "最近作业和比赛堆在一起，晚上总是睡不着，白天又提不起精神。", now),
    )
    conn.execute(
        "INSERT INTO tree_messages (thread_id, sender, body, created_at) VALUES (?, 'counselor', ?, ?)",
        (tid, "听起来这段时间真的很紧。先别急着把所有事都做好，今晚可以试试把明天的任务只写三件。我在，你可以继续说。", now),
    )

student_id = conn.execute("SELECT id FROM users WHERE username='student'").fetchone()["id"]
admin_id = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()["id"]

if conn.execute("SELECT COUNT(*) FROM qa_threads").fetchone()[0] == 0:
    cur = conn.execute(
        "INSERT INTO qa_threads (author_id, topic, title, body, status, created_at, last_at) "
        "VALUES (?, 'study', ?, ?, 'resolved', ?, ?)",
        (student_id, "高数期中怎么复习效率高？",
         "老师画了重点，但一章内容还是很多。想问问大家是怎么安排复习顺序的。", now, now),
    )
    qa_id = cur.lastrowid
    conn.execute(
        "INSERT INTO qa_replies (thread_id, author_id, body, created_at) VALUES (?, ?, ?, ?)",
        (qa_id, admin_id,
         "建议先按老师画的重点过一遍，再用两套真题倒推薄弱章节。别从第一页开始平均用力。", now),
    )
    conn.execute(
        "INSERT INTO qa_replies (thread_id, author_id, body, created_at) VALUES (?, ?, ?, ?)",
        (qa_id, student_id, "明白了，今晚先把重点章节列出来。谢谢！", now),
    )
    conn.execute(
        "INSERT INTO qa_threads (author_id, topic, title, body, status, created_at, last_at) "
        "VALUES (?, 'class', ?, ?, 'open', ?, ?)",
        (student_id, "下周班会想加一个 10 分钟的经验分享",
         "想请参加过去年教学技能大赛的同学讲讲备赛过程，大家觉得合适吗？", now, now),
    )

if conn.execute("SELECT COUNT(*) FROM resources").fetchone()[0] == 0:
    mod.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    samples = [
        ("shot-approved.txt", "高数复习提纲\n第一章 极限\n第二章 导数\n第三章 积分\n"),
        ("shot-pending.txt", "教资面试：结构化答题框架\n1. 表态\n2. 分析\n3. 解决\n"),
    ]
    for stored, content in samples:
        (mod.UPLOAD_DIR / stored).write_text(content, encoding="utf-8")
    conn.execute(
        "INSERT INTO resources (uploader_id, title, description, subject, filename, stored_name, "
        "size, status, download_count, created_at, reviewed_at, reviewed_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'approved', 3, ?, ?, ?)",
        (student_id, "高等数学期中复习提纲", "按老师画的重点整理了前三章，附常见题型。",
         "高等数学", "高数复习提纲.txt", "shot-approved.txt",
         len(samples[0][1].encode("utf-8")), now, now, admin_id),
    )
    conn.execute(
        "INSERT INTO resources (uploader_id, title, description, subject, filename, stored_name, "
        "size, status, download_count, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?)",
        (student_id, "教资面试结构化答题模板", "自己整理的答题框架，想请大家帮忙看看。",
         "教资面试", "答题模板.txt", "shot-pending.txt",
         len(samples[1][1].encode("utf-8")), now),
    )

conn.commit()
counselor_id = conn.execute("SELECT id FROM users WHERE username='xueronghua'").fetchone()["id"]
conn.close()

serializer = SecureCookieSessionInterface().get_signing_serializer(mod.app)


def cookie_for(uid, name, role):
    return serializer.dumps({"_csrf": "shotcsrf", "user_id": uid, "username": name, "role": role})


out = {
    "cookies": {
        "admin": cookie_for(admin_id, "admin", "superadmin"),
        "student": cookie_for(student_id, "student", "member"),
        "counselor": cookie_for(counselor_id, "xueronghua", "counselor"),
    },
    "feedback_token": mod.thread_token("feedback", 1),
    "tree_token": mod.thread_token("tree", 1),
}
Path(__file__).with_name("shot-seed.json").write_text(
    json.dumps(out, ensure_ascii=False), encoding="utf-8"
)
print("seed ok")
