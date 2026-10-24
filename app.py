import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta

from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'app.db')
UPLOAD_AV = os.path.join(BASE, 'static', 'avatars')
UPLOAD_POST = os.path.join(BASE, 'static', 'uploads')
os.makedirs(UPLOAD_AV, exist_ok=True)
os.makedirs(UPLOAD_POST, exist_ok=True)

app = Flask(__name__)
# Demo 占位密钥；生产环境请通过环境变量 SECRET_KEY 注入随机值
app.secret_key = os.environ.get('SECRET_KEY', 'demo-secret-change-me')

RESET_TTL_MINUTES = 30
FMT = '%Y-%m-%d %H:%M'


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def now():
    return datetime.now().strftime(FMT)


def _cols(conn, table):
    return [r[1] for r in conn.execute('PRAGMA table_info(%s)' % table)]


def init_db():
    conn = db(); c = conn.cursor()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY,
      username TEXT UNIQUE,
      email TEXT,
      password_hash TEXT,
      role TEXT DEFAULT 'user',
      avatar TEXT,
      status TEXT DEFAULT 'active',
      reset_token TEXT,
      reset_expires TEXT,
      created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS categories (
      id INTEGER PRIMARY KEY,
      name TEXT UNIQUE,
      created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS posts (
      id INTEGER PRIMARY KEY,
      user_id INTEGER,
      category_id INTEGER,
      title TEXT,
      body TEXT,
      image_path TEXT,
      is_history INTEGER DEFAULT 0,
      created_at TEXT,
      updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS comments (
      id INTEGER PRIMARY KEY,
      post_id INTEGER,
      user_id INTEGER,
      parent_id INTEGER,
      body TEXT,
      created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS site_config (
      id INTEGER PRIMARY KEY CHECK (id=1),
      site_name TEXT,
      invite_code TEXT
    );
    ''')
    # ---- 兼容旧库的迁移（补列） ----
    ucols = _cols(conn, 'users')
    for col, ddl in (('status', "TEXT DEFAULT 'active'"),
                     ('reset_token', 'TEXT'),
                     ('reset_expires', 'TEXT')):
        if col not in ucols:
            conn.execute('ALTER TABLE users ADD COLUMN %s %s' % (col, ddl))
    pcols = _cols(conn, 'posts')
    if 'is_history' not in pcols:
        conn.execute("ALTER TABLE posts ADD COLUMN is_history INTEGER DEFAULT 0")
    # 邮箱唯一（尽力而为：若历史数据已有重复邮箱则跳过索引，仅靠应用层校验）
    try:
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)')
    except sqlite3.IntegrityError:
        pass
    # ---- 默认数据 ----
    if c.execute('SELECT COUNT(*) FROM users WHERE role="superadmin"').fetchone()[0] == 0:
        c.execute('INSERT INTO users (username,email,password_hash,role,status,created_at) VALUES (?,?,?,?,?,?)',
                  ('admin', 'admin@example.com', generate_password_hash('admin123'), 'superadmin', 'active', now()))
    if c.execute('SELECT COUNT(*) FROM site_config').fetchone()[0] == 0:
        c.execute('INSERT INTO site_config (id,site_name,invite_code) VALUES (1,?,?)', ('匿名登记台', 'DEMO2026'))
    if c.execute('SELECT COUNT(*) FROM categories').fetchone()[0] == 0:
        for n in ['综合', '求助', '反馈']:
            c.execute('INSERT INTO categories (name,created_at) VALUES (?,?)', (n, now()))
    conn.commit(); conn.close()


init_db()


# ---------- helpers ----------
def require_login():
    return 'user_id' in session


def is_staff():
    return session.get('role') in ('admin', 'superadmin')


def is_superadmin():
    return session.get('role') == 'superadmin'


def password_ok(pw):
    return (len(pw) >= 8
            and re.search(r'[a-z]', pw)
            and re.search(r'[A-Z]', pw)
            and re.search(r'[0-9]', pw))


def post_query(extra_where=''):
    return ('''SELECT p.*, c.name as category, u.username as author
              FROM posts p
              LEFT JOIN categories c ON p.category_id=c.id
              LEFT JOIN users u ON p.user_id=u.id
              ''' + extra_where + '''
              ORDER BY p.created_at DESC''')


def can_view_post(row):
    """本人或 staff 可查看/评论某帖。"""
    return is_staff() or row['user_id'] == session.get('user_id')


def comment_counts(conn, post_ids=None):
    if post_ids:
        marks = ','.join('?' * len(post_ids))
        rows = conn.execute(
            'SELECT post_id, COUNT(*) AS c FROM comments WHERE post_id IN (%s) GROUP BY post_id' % marks,
            post_ids).fetchall()
    else:
        rows = conn.execute('SELECT post_id, COUNT(*) AS c FROM comments GROUP BY post_id').fetchall()
    return {r['post_id']: r['c'] for r in rows}


# ---------- auth ----------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        name = request.form['username'].strip()
        pw = request.form['password']
        conn = db()
        u = conn.execute('SELECT * FROM users WHERE username=? OR email=?', (name, name)).fetchone()
        conn.close()
        if u and check_password_hash(u['password_hash'], pw):
            if u['status'] == 'banned':
                flash('账号已被封禁，请联系管理员'); return redirect('/login')
            session['user_id'] = u['id']
            session['username'] = u['username']
            session['role'] = u['role']
            return redirect('/')
        flash('用户名或密码错误')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u = request.form['username'].strip()
        e = request.form['email'].strip()
        ic = request.form['invite_code'].strip()
        pw = request.form['password']
        pw2 = request.form['password2']
        conn = db()
        cfg = conn.execute('SELECT invite_code FROM site_config WHERE id=1').fetchone()
        if not (u and e and ic and pw):
            conn.close(); flash('用户名、邮箱、邀请码、密码均需填写'); return redirect('/register')
        if ic != cfg['invite_code']:
            conn.close(); flash('邀请码错误'); return redirect('/register')
        if not password_ok(pw):
            conn.close(); flash('密码需 8 位以上，且同时包含大小写字母与数字'); return redirect('/register')
        if pw != pw2:
            conn.close(); flash('两次输入的密码不一致'); return redirect('/register')
        if conn.execute('SELECT id FROM users WHERE email=?', (e,)).fetchone():
            conn.close(); flash('邮箱已被注册'); return redirect('/register')
        if conn.execute('SELECT id FROM users WHERE username=?', (u,)).fetchone():
            conn.close(); flash('用户名已存在'); return redirect('/register')
        conn.execute('INSERT INTO users (username,email,password_hash,role,status,created_at) VALUES (?,?,?,?,?,?)',
                     (u, e, generate_password_hash(pw), 'user', 'active', now()))
        conn.commit(); conn.close()
        flash('注册成功，请登录'); return redirect('/login')
    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear(); return redirect('/login')


# ---------- pages ----------
@app.route('/')
def index():
    if not require_login():
        return redirect('/login')
    conn = db()
    if is_staff():
        rows = conn.execute(post_query('WHERE p.is_history=0')).fetchall()
    else:
        rows = conn.execute(post_query('WHERE p.is_history=0 AND p.user_id=?'), (session['user_id'],)).fetchall()
    counts = comment_counts(conn, [p['id'] for p in rows])
    cats = conn.execute('SELECT * FROM categories ORDER BY id').fetchall()
    conn.close()
    return render_template('index.html', posts=rows, counts=counts, categories=cats)


@app.route('/history')
def history():
    if not require_login():
        return redirect('/login')
    conn = db()
    rows = conn.execute(post_query('WHERE p.is_history=1 AND p.user_id=?'), (session['user_id'],)).fetchall()
    counts = comment_counts(conn, [p['id'] for p in rows])
    conn.close()
    return render_template('history.html', posts=rows, counts=counts)


# ---------- posts ----------
@app.route('/post/new', methods=['POST'])
def new_post():
    if not require_login():
        return redirect('/login')
    title = request.form['title'].strip()
    body = request.form['body'].strip()
    cid = request.form.get('category_id')
    if not title or not body or not cid:
        flash('标题、内容和分区均必填'); return redirect('/')
    conn = db()
    img = save_upload(request.files.get('image'), UPLOAD_POST, prefix='p%d_' % session['user_id'])
    conn.execute('INSERT INTO posts (user_id,category_id,title,body,image_path,is_history,created_at,updated_at) VALUES (?,?,?,?,?,0,?,?)',
                 (session['user_id'], cid, title, body, img, now(), now()))
    conn.commit(); conn.close()
    return redirect('/')


@app.route('/post/<int:pid>/edit', methods=['POST'])
def edit_post(pid):
    if not require_login():
        return redirect('/login')
    conn = db()
    p = conn.execute('SELECT * FROM posts WHERE id=?', (pid,)).fetchone()
    if not p:
        conn.close(); return '帖子不存在', 404
    if not can_view_post(p):
        conn.close(); return '无权操作', 403
    title = request.form['title'].strip()
    body = request.form['body'].strip()
    cid = request.form.get('category_id')
    if not title or not body or not cid:
        flash('标题、内容和分区均必填'); conn.close(); return redirect('/post/%d' % pid)
    conn.execute('UPDATE posts SET title=?,body=?,category_id=?,updated_at=? WHERE id=?',
                 (title, body, cid, now(), pid))
    conn.commit(); conn.close()
    return redirect('/post/%d' % pid)


@app.route('/post/<int:pid>')
def post_detail(pid):
    if not require_login():
        return redirect('/login')
    conn = db()
    p = conn.execute(post_query('WHERE p.id=?'), (pid,)).fetchone()
    if not p:
        conn.close(); return '帖子不存在', 404
    if not can_view_post(p):
        conn.close(); return '无权查看', 403
    comments = conn.execute('''SELECT cm.*, u.username AS author, u.role AS author_role
                               FROM comments cm JOIN users u ON cm.user_id=u.id
                               WHERE cm.post_id=? ORDER BY cm.created_at''', (pid,)).fetchall()
    cats = conn.execute('SELECT * FROM categories ORDER BY id').fetchall()
    conn.close()
    top = [c for c in comments if c['parent_id'] is None]
    children = {}
    for c in comments:
        if c['parent_id'] is not None:
            children.setdefault(c['parent_id'], []).append(c)
    return render_template('post.html', post=p, top=top, children=children,
                           comment_total=len(comments),
                           can_comment=can_view_post(p), categories=cats)


@app.route('/post/<int:pid>/delete', methods=['POST'])
def delete_post(pid):
    if not require_login():
        return redirect('/login')
    conn = db()
    p = conn.execute('SELECT * FROM posts WHERE id=?', (pid,)).fetchone()
    if not p:
        conn.close(); return '帖子不存在', 404
    if not can_view_post(p):
        conn.close(); return '无权操作', 403
    conn.execute('DELETE FROM comments WHERE post_id=?', (pid,))
    conn.execute('DELETE FROM posts WHERE id=?', (pid,))
    conn.commit(); conn.close()
    return redirect(request.referrer or '/')


@app.route('/post/<int:pid>/category', methods=['POST'])
def change_category(pid):
    if not require_login():
        return redirect('/login')
    if not is_staff():
        return '无权操作', 403
    cid = request.form.get('category_id')
    conn = db()
    conn.execute('UPDATE posts SET category_id=?,updated_at=? WHERE id=?', (cid, now(), pid))
    conn.commit(); conn.close()
    return redirect('/admin')


@app.route('/post/<int:pid>/history', methods=['POST'])
def toggle_history(pid):
    if not require_login():
        return redirect('/login')
    conn = db()
    p = conn.execute('SELECT * FROM posts WHERE id=?', (pid,)).fetchone()
    if not p:
        conn.close(); return '帖子不存在', 404
    if not can_view_post(p):
        conn.close(); return '无权操作', 403
    newv = 0 if p['is_history'] else 1
    conn.execute('UPDATE posts SET is_history=?,updated_at=? WHERE id=?', (newv, now(), pid))
    conn.commit(); conn.close()
    flash('已移入历史帖子' if newv else '已从历史恢复')
    return redirect(request.referrer or ('/history' if newv else '/'))


# ---------- comments ----------
@app.route('/post/<int:pid>/comment', methods=['POST'])
def add_comment(pid):
    if not require_login():
        return redirect('/login')
    conn = db()
    p = conn.execute('SELECT * FROM posts WHERE id=?', (pid,)).fetchone()
    if not p:
        conn.close(); return '帖子不存在', 404
    if not can_view_post(p):
        conn.close(); return '无权操作', 403
    body = request.form['body'].strip()
    parent_id = request.form.get('parent_id') or None
    if parent_id:
        parent_id = int(parent_id)
    if body:
        conn.execute('INSERT INTO comments (post_id,user_id,parent_id,body,created_at) VALUES (?,?,?,?,?)',
                     (pid, session['user_id'], parent_id, body, now()))
        conn.commit()
    conn.close()
    return redirect('/post/%d' % pid)


@app.route('/comment/<int:cid>/delete', methods=['POST'])
def delete_comment(cid):
    if not require_login():
        return redirect('/login')
    conn = db()
    cm = conn.execute('SELECT * FROM comments WHERE id=?', (cid,)).fetchone()
    if not cm:
        conn.close(); return '评论不存在', 404
    post = conn.execute('SELECT * FROM posts WHERE id=?', (cm['post_id'],)).fetchone()
    # staff 可删任意；普通用户仅能删自己帖下的自己评论
    if not is_staff() and not (cm['user_id'] == session.get('user_id') and post['user_id'] == session.get('user_id')):
        conn.close(); return '无权操作', 403
    conn.execute('DELETE FROM comments WHERE id=? OR parent_id=?', (cid, cid))
    conn.commit(); conn.close()
    return redirect(request.referrer or ('/post/%d' % cm['post_id']))


# ---------- profile ----------
@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if not require_login():
        return redirect('/login')
    conn = db()
    u = conn.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        if not username:
            conn.close(); flash('用户名不能为空'); return redirect('/profile')
        if not email:
            conn.close(); flash('邮箱不能为空'); return redirect('/profile')
        if conn.execute('SELECT id FROM users WHERE username=? AND id!=?', (username, session['user_id'])).fetchone():
            conn.close(); flash('用户名已被占用'); return redirect('/profile')
        if conn.execute('SELECT id FROM users WHERE email=? AND id!=?', (email, session['user_id'])).fetchone():
            conn.close(); flash('邮箱已被占用'); return redirect('/profile')
        av = save_upload(request.files.get('avatar'), UPLOAD_AV, prefix='u%d_' % session['user_id'])
        if av:
            conn.execute('UPDATE users SET avatar=? WHERE id=?', (av, session['user_id']))
        conn.execute('UPDATE users SET username=?,email=? WHERE id=?', (username, email, session['user_id']))
        conn.commit()
        session['username'] = username
        conn.close(); flash('已保存'); return redirect('/profile')
    conn.close()
    return render_template('profile.html', user=u)


@app.route('/profile/avatar', methods=['GET', 'POST'])
def avatar_edit():
    if not require_login():
        return redirect('/login')
    conn = db()
    u = conn.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    if request.method == 'POST':
        av = save_upload(request.files.get('avatar'), UPLOAD_AV, prefix='u%d_' % session['user_id'])
        if av:
            conn.execute('UPDATE users SET avatar=? WHERE id=?', (av, session['user_id']))
            conn.commit(); conn.close()
            return jsonify(ok=True, url=url_for('static', filename='avatars/' + av))
        conn.close()
        return jsonify(ok=False, msg='请选择有效的图片（png/jpg/jpeg/gif/webp）'), 400
    conn.close()
    return render_template('avatar.html', user=u)


# ---------- admin (staff) ----------
@app.route('/admin')
def admin():
    if not require_login():
        return redirect('/login')
    if not is_staff():
        return '无权访问', 403
    conn = db()
    posts = conn.execute(post_query()).fetchall()
    cats = conn.execute('SELECT * FROM categories ORDER BY id').fetchall()
    conn.close()
    return render_template('manage.html', posts=posts, categories=cats)


# ---------- superadmin: users ----------
@app.route('/admin/users')
def admin_users():
    if not require_login():
        return redirect('/login')
    if not is_superadmin():
        return '无权访问', 403
    conn = db()
    users = conn.execute('SELECT * FROM users ORDER BY id').fetchall()
    conn.close()
    return render_template('users.html', users=users)


@app.route('/admin/user/<int:uid>/ban', methods=['POST'])
def admin_ban(uid):
    if not require_login() or not is_superadmin():
        return '无权访问', 403
    conn = db()
    u = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if u and u['role'] != 'superadmin':
        newstatus = 'active' if u['status'] == 'banned' else 'banned'
        conn.execute('UPDATE users SET status=? WHERE id=?', (newstatus, uid))
        conn.commit()
        flash(('已解封 ' if newstatus == 'active' else '已封禁 ') + u['username'])
    conn.close()
    return redirect('/admin/users')


@app.route('/admin/user/<int:uid>/rename', methods=['POST'])
def admin_rename(uid):
    if not require_login() or not is_superadmin():
        return '无权访问', 403
    new = request.form['username'].strip()
    conn = db()
    if new:
        try:
            conn.execute('UPDATE users SET username=? WHERE id=?', (new, uid))
            conn.commit(); flash('已改名')
        except sqlite3.IntegrityError:
            flash('用户名已存在')
    conn.close()
    return redirect('/admin/users')


@app.route('/admin/user/<int:uid>/role', methods=['POST'])
def admin_role(uid):
    if not require_login() or not is_superadmin():
        return '无权访问', 403
    role = request.form.get('role')
    conn = db()
    if role in ('user', 'admin', 'superadmin'):
        conn.execute('UPDATE users SET role=? WHERE id=?', (role, uid))
        conn.commit(); flash('权限已更新')
    conn.close()
    return redirect('/admin/users')


@app.route('/admin/user/<int:uid>/avatar', methods=['POST'])
def admin_reset_avatar(uid):
    if not require_login() or not is_superadmin():
        return '无权访问', 403
    conn = db()
    conn.execute('UPDATE users SET avatar=NULL WHERE id=?', (uid,))
    conn.commit(); conn.close()
    flash('头像已重置')
    return redirect('/admin/users')


@app.route('/admin/user/<int:uid>/reset', methods=['POST'])
def admin_send_reset(uid):
    if not require_login() or not is_superadmin():
        return '无权访问', 403
    token = secrets.token_urlsafe(24)
    expires = (datetime.now() + timedelta(minutes=RESET_TTL_MINUTES)).strftime(FMT)
    conn = db()
    conn.execute('UPDATE users SET reset_token=?, reset_expires=? WHERE id=?', (token, expires, uid))
    conn.commit(); conn.close()
    link = url_for('reset_password', token=token, _external=True)
    flash('已生成重置链接（演示环境未真正发送邮件，%d 分钟内有效）：%s' % (RESET_TTL_MINUTES, link))
    return redirect('/admin/users')


@app.route('/reset/<token>', methods=['GET', 'POST'])
def reset_password(token):
    conn = db()
    u = conn.execute('SELECT * FROM users WHERE reset_token=?', (token,)).fetchone()
    valid = False
    if u and u['reset_expires']:
        try:
            valid = datetime.strptime(u['reset_expires'], FMT) > datetime.now()
        except ValueError:
            valid = False
    if request.method == 'POST' and valid:
        pw = request.form['password']
        pw2 = request.form['password2']
        if not password_ok(pw):
            conn.close(); flash('密码需 8 位以上，且同时包含大小写字母与数字'); return redirect(request.path)
        if pw != pw2:
            conn.close(); flash('两次输入的密码不一致'); return redirect(request.path)
        conn.execute('UPDATE users SET password_hash=?, reset_token=NULL, reset_expires=NULL WHERE id=?',
                     (generate_password_hash(pw), u['id']))
        conn.commit(); conn.close()
        flash('密码已重置，请登录'); return redirect('/login')
    conn.close()
    return render_template('reset.html', valid=valid)


# ---------- superadmin: settings ----------
@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if not require_login():
        return redirect('/login')
    if not is_superadmin():
        return '无权访问', 403
    conn = db()
    if request.method == 'POST':
        sn = request.form['site_name'].strip()
        ic = request.form['invite_code'].strip()
        conn.execute('UPDATE site_config SET site_name=?,invite_code=? WHERE id=1', (sn, ic))
        conn.commit(); flash('设置已保存')
    cfg = conn.execute('SELECT * FROM site_config WHERE id=1').fetchone()
    cats = conn.execute('SELECT * FROM categories ORDER BY id').fetchall()
    conn.close()
    return render_template('settings.html', config=cfg, categories=cats)


@app.route('/category/new', methods=['POST'])
def new_category():
    if not require_login() or not is_superadmin():
        return '无权访问', 403
    name = request.form['name'].strip()
    if name:
        conn = db()
        try:
            conn.execute('INSERT INTO categories (name,created_at) VALUES (?,?)', (name, now()))
            conn.commit()
        except sqlite3.IntegrityError:
            flash('分区名已存在')
        conn.close()
    return redirect('/settings')


@app.route('/category/<int:cid>/delete', methods=['POST'])
def del_category(cid):
    if not require_login() or not is_superadmin():
        return '无权访问', 403
    conn = db()
    conn.execute('UPDATE posts SET category_id=NULL WHERE category_id=?', (cid,))
    conn.execute('DELETE FROM categories WHERE id=?', (cid,))
    conn.commit(); conn.close()
    return redirect('/settings')


# ---------- util ----------
ALLOWED = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def save_upload(f, folder, prefix=''):
    if not f or not f.filename:
        return None
    ext = f.filename.rsplit('.', 1)[-1].lower()
    if ext not in ALLOWED:
        return None
    fn = prefix + secure_filename(f.filename)
    f.save(os.path.join(folder, fn))
    if folder == UPLOAD_AV:
        return fn
    return 'uploads/' + fn


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
