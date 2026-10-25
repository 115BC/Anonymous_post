PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL DEFAULT 'member'
                CHECK (role IN ('member', 'admin', 'counselor', 'superadmin')),
  status        TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'banned')),
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS site_config (
  id          INTEGER PRIMARY KEY CHECK (id = 1),
  site_name   TEXT NOT NULL,
  invite_code TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notices (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  category   TEXT NOT NULL
             CHECK (category IN ('safety', 'activity', 'important', 'exam')),
  title      TEXT NOT NULL,
  body       TEXT NOT NULL,
  pinned     INTEGER NOT NULL DEFAULT 0,
  deadline   TEXT,
  status     TEXT NOT NULL DEFAULT 'published'
             CHECK (status IN ('draft', 'published')),
  author_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notices_list
  ON notices(status, pinned DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS notice_reads (
  notice_id INTEGER NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
  user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  read_at   TEXT NOT NULL,
  PRIMARY KEY (notice_id, user_id)
);

-- 匿名反馈：刻意不存 user_id / IP / User-Agent。
-- 作者身份只由回访码证明，服务端保存回访码的 HMAC 摘要。
CREATE TABLE IF NOT EXISTS feedback_threads (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  code_hash  TEXT NOT NULL UNIQUE,
  topic      TEXT NOT NULL
             CHECK (topic IN ('study', 'class', 'activity', 'other')),
  status     TEXT NOT NULL DEFAULT 'new'
             CHECK (status IN ('new', 'replied')),
  created_at TEXT NOT NULL,
  last_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback_messages (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id  INTEGER NOT NULL REFERENCES feedback_threads(id) ON DELETE CASCADE,
  sender     TEXT NOT NULL CHECK (sender IN ('author', 'committee')),
  body       TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feedback_messages
  ON feedback_messages(thread_id, id);

-- 树洞：同样不存任何身份字段，只有雪绒花角色可进入收件箱。
CREATE TABLE IF NOT EXISTS tree_threads (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  code_hash  TEXT NOT NULL UNIQUE,
  mood       TEXT NOT NULL
             CHECK (mood IN ('talk', 'tired', 'happy', 'help')),
  status     TEXT NOT NULL DEFAULT 'new'
             CHECK (status IN ('new', 'replied')),
  created_at TEXT NOT NULL,
  last_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tree_messages (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id  INTEGER NOT NULL REFERENCES tree_threads(id) ON DELETE CASCADE,
  sender     TEXT NOT NULL CHECK (sender IN ('author', 'counselor')),
  body       TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tree_messages
  ON tree_messages(thread_id, id);

-- 登录失败限速。键是用户名的 HMAC 摘要，不保存明文用户名与 IP。
CREATE TABLE IF NOT EXISTS login_throttle (
  key          TEXT PRIMARY KEY,
  fails        INTEGER NOT NULL DEFAULT 0,
  locked_until INTEGER NOT NULL DEFAULT 0
);

-- 问题交流：实名模块，与匿名反馈/树洞完全分离。
CREATE TABLE IF NOT EXISTS qa_threads (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  author_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  topic      TEXT NOT NULL
             CHECK (topic IN ('study', 'class', 'activity', 'other')),
  title      TEXT NOT NULL,
  body       TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'open'
             CHECK (status IN ('open', 'resolved')),
  created_at TEXT NOT NULL,
  last_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_qa_threads_list
  ON qa_threads(status, last_at DESC);

CREATE TABLE IF NOT EXISTS qa_replies (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id  INTEGER NOT NULL REFERENCES qa_threads(id) ON DELETE CASCADE,
  author_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  body       TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_qa_replies
  ON qa_replies(thread_id, id);

-- 资源库：文件放在 instance/uploads（不在 static 下），下载需登录。
-- 这里刻意保留上传者身份，资源不是匿名内容；审核通过后才对全班可见。
CREATE TABLE IF NOT EXISTS resources (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  uploader_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
  title          TEXT NOT NULL,
  description    TEXT NOT NULL DEFAULT '',
  subject        TEXT NOT NULL,
  filename       TEXT NOT NULL,
  stored_name    TEXT NOT NULL UNIQUE,
  size           INTEGER NOT NULL,
  status         TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'approved', 'rejected')),
  download_count INTEGER NOT NULL DEFAULT 0,
  created_at     TEXT NOT NULL,
  reviewed_at    TEXT,
  reviewed_by    INTEGER REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_resources_list
  ON resources(status, created_at DESC);
