import os
from datetime import datetime

from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'app.db')
UPLOAD_AV = os.path.join(BASE, 'static', 'avatars')
UPLOAD_POST = os.path.join(BASE, 'static', 'uploads')
os.makedirs(UPLOAD_AV, exist_ok=True)
os.makedirs(UPLOAD_POST, exist_ok=True)

app = Flask(__name__)
app.secret_key = 'demo-secret-change-me'

import sqlite3

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M')

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
      created_at TEXT,
      updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS replies (
      id INTEGER PRIMARY KEY,
      post_id INTEGER,
      admin_id INTEGER,
      admin_name TEXT,
      body TEXT,
      created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS site_config (
      id INTEGER PRIMARY KEY CHECK (id=1),
      site_name TEXT,
      invite_code TEXT
    );
    ''')
    if c.execute('SELECT COUNT(*) FROM users WHERE role="superadmin"').fetchone()[0] == 0:
        c.execute('INSERT INTO users (username,email,password_hash,role,created_at) VALUES (?,?,?,?,?)',
                  ('admin', 'admin@example.com', generate_password_hash('admin123'), 'superadmin', now()))
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

def post_query(extra_where='', params=()):
    return '''SELECT p.*, c.name as category, u.username as author
             FROM posts p
             LEFT JOIN categories c ON p.category_id=c.id
             LEFT JOIN users u ON p.user_id=u.id
             ''' + extra_where + '''
             ORDER BY p.created_at DESC'''

# ---------- auth ----------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u = request.form['username'].strip()
        e = request.form['email'].strip()
        ic = request.form['invite_code'].strip()
        pw = request.form['password']
        conn = db()
        cfg = conn.execute('SELECT invite_code FROM site_config WHERE id=1').fetchone()
        if ic != cfg['invite_code']:
            flash('邀请码错误'); conn.close(); return redirect('/register')
        if len(pw) < 6:
            flash('密码至少6位'); conn.close(); return redirect('/register')
        if conn.execute('SELECT id FROM users WHERE username=?', (u,)).fetchone():
            flash('用户名已存在'); conn.close(); return redirect('/register')
        conn.execute('INSERT INTO users (username,email,password_hash,role,created_at) VALUES (?,?,?,?,?)',
                     (u, e, generate_password_hash(pw), 'user', now()))
        conn.commit(); conn.close()
        flash('注册成功，请登录'); return redirect('/login')
    return render_template('auth.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        name = request.form['username'].strip()
        pw = request.form['password']
        conn = db()
        u = conn.execute('SELECT * FROM users WHERE username=? OR email=?', (name, name)).fetchone()
        conn.close()
        if u and check_password_hash(u['password_hash'], pw):
            session['user_id'] = u['id']; session['username'] = u['username']; session['role'] = u['role']
            return redirect('/')
        flash('用户名或密码错误')
    return render_template('auth.html')

@app.route('/logout')
def logout():
    session.clear(); return redirect('/')

# ---------- pages ----------
@app.route('/')
def index():
    if not require_login(): return redirect('/login')
    conn = db()
    if is_staff():
        rows = conn.execute(post_query()).fetchall()
    else:
        rows = conn.execute(post_query('WHERE p.user_id=?'), (session['user_id'],)).fetchall()
    conn.close()
    return render_template('index.html', posts=rows)

@app.route('/post/new', methods=['GET', 'POST'])
def new_post():
    if not require_login(): return redirect('/login')
    conn = db(); cats = conn.execute('SELECT * FROM categories ORDER BY id').fetchall()
    if request.method == 'POST':
        title = request.form['title'].strip()
        body = request.form['body'].strip()
        cid = request.form.get('category_id')
        if not title or not body or not cid:
            flash('标题、内容和分区均必填'); conn.close(); return render_template('post_form.html', categories=cats, post=None)
        img = save_upload(request.files.get('image'), UPLOAD_POST, prefix=f"p{session['user_id']}_")
        conn.execute('INSERT INTO posts (user_id,category_id,title,body,image_path,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
                     (session['user_id'], cid, title, body, img, now(), now()))
        conn.commit(); conn.close(); return redirect('/')
    conn.close(); return render_template('post_form.html', categories=cats, post=None)

@app.route('/post/<int:pid>/edit', methods=['GET', 'POST'])
def edit_post(pid):
    if not require_login(): return redirect('/login')
    conn = db(); p = conn.execute('SELECT * FROM posts WHERE id=?', (pid,)).fetchone()
    if not p: conn.close(); return '帖子不存在', 404
    if p['user_id'] != session['user_id'] and not is_staff():
        conn.close(); return '无权操作', 403
    cats = conn.execute('SELECT * FROM categories ORDER BY id').fetchall()
    if request.method == 'POST':
        title = request.form['title'].strip(); body = request.form['body'].strip(); cid = request.form.get('category_id')
        if not title or not body or not cid:
            flash('标题、内容和分区均必填'); conn.close(); return render_template('post_form.html', categories=cats, post=p)
        conn.execute('UPDATE posts SET title=?,body=?,category_id=?,updated_at=? WHERE id=?', (title, body, cid, now(), pid))
        conn.commit(); conn.close(); return redirect(f'/post/{pid}')
    conn.close(); return render_template('post_form.html', categories=cats, post=p)

@app.route('/post/<int:pid>')
def post_detail(pid):
    if not require_login(): return redirect('/login')
    conn = db()
    p = conn.execute(post_query('WHERE p.id=?'), (pid,)).fetchone()
    if not p: conn.close(); return '帖子不存在', 404
    if p['user_id'] != session['user_id'] and session['role'] == 'user':
        conn.close(); return '无权查看', 403
    replies = conn.execute('SELECT * FROM replies WHERE post_id=? ORDER BY created_at', (pid,)).fetchall()
    conn.close()
    return render_template('post.html', post=p, replies=replies)

@app.route('/post/<int:pid>/delete', methods=['POST'])
def delete_post(pid):
    if not require_login(): return redirect('/login')
    if not is_staff(): return '无权操作', 403
    conn = db(); conn.execute('DELETE FROM replies WHERE post_id=?', (pid,))
    conn.execute('DELETE FROM posts WHERE id=?', (pid,)); conn.commit(); conn.close()
    return redirect('/admin' if is_staff() else '/')

@app.route('/post/<int:pid>/category', methods=['POST'])
def change_category(pid):
    if not require_login(): return redirect('/login')
    if not is_staff(): return '无权操作', 403
    cid = request.form.get('category_id')
    conn = db(); conn.execute('UPDATE posts SET category_id=?,updated_at=? WHERE id=?', (cid, now(), pid))
    conn.commit(); conn.close()
    return redirect('/admin')

@app.route('/post/<int:pid>/reply', methods=['POST'])
def reply(pid):
    if not require_login(): return redirect('/login')
    if not is_staff(): return '无权操作', 403
    body = request.form['body'].strip()
    if not body: return redirect(f'/post/{pid}')
    conn = db()
    conn.execute('INSERT INTO replies (post_id,admin_id,admin_name,body,created_at) VALUES (?,?,?,?,?)',
                 (pid, session['user_id'], session['username'], body, now()))
    conn.commit(); conn.close()
    return redirect(f'/post/{pid}')

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if not require_login(): return redirect('/login')
    conn = db(); u = conn.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    if request.method == 'POST':
        username = request.form['username'].strip(); email = request.form['email'].strip()
        av = save_upload(request.files.get('avatar'), UPLOAD_AV, prefix=f"u{session['user_id']}_")
        if av:
            conn.execute('UPDATE users SET avatar=? WHERE id=?', (av, session['user_id']))
        conn.execute('UPDATE users SET username=?,email=? WHERE id=?', (username, email, session['user_id']))
        conn.commit(); conn.close(); session['username'] = username
        flash('已保存'); return redirect('/profile')
    conn.close(); return render_template('profile.html', user=u)

@app.route('/admin')
def admin():
    if not require_login(): return redirect('/login')
    if not is_staff(): return '无权访问', 403
    conn = db()
    posts = conn.execute(post_query()).fetchall()
    cats = conn.execute('SELECT * FROM categories ORDER BY id').fetchall()
    conn.close()
    return render_template('manage.html', posts=posts, categories=cats)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if not require_login(): return redirect('/login')
    if session['role'] != 'superadmin': return '无权访问', 403
    conn = db()
    if request.method == 'POST':
        sn = request.form['site_name'].strip(); ic = request.form['invite_code'].strip()
        conn.execute('UPDATE site_config SET site_name=?,invite_code=? WHERE id=1', (sn, ic))
        conn.commit(); flash('设置已保存')
    cfg = conn.execute('SELECT * FROM site_config WHERE id=1').fetchone()
    cats = conn.execute('SELECT * FROM categories ORDER BY id').fetchall()
    conn.close()
    return render_template('settings.html', config=cfg, categories=cats)

@app.route('/category/new', methods=['POST'])
def new_category():
    if not require_login(): return redirect('/login')
    if session['role'] != 'superadmin': return '无权访问', 403
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
    if not require_login(): return redirect('/login')
    if session['role'] != 'superadmin': return '无权访问', 403
    conn = db(); conn.execute('UPDATE posts SET category_id=NULL WHERE category_id=?', (cid,))
    conn.execute('DELETE FROM categories WHERE id=?', (cid,)); conn.commit(); conn.close()
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
