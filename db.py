"""SQLite access layer."""
import os, sqlite3
from contextlib import closing

def path():
    return os.getenv("VAGO_DB", os.path.join(os.path.dirname(__file__), "data", "vago.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS brands(id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '', voice TEXT DEFAULT '',
  tone TEXT DEFAULT '', dos TEXT DEFAULT '', donts TEXT DEFAULT '', keywords TEXT DEFAULT '', audience TEXT DEFAULT '', created TEXT);
CREATE TABLE IF NOT EXISTS campaigns(id INTEGER PRIMARY KEY, brand_id INTEGER REFERENCES brands(id), name TEXT NOT NULL,
  goal TEXT DEFAULT '', brief TEXT DEFAULT '', analysis TEXT DEFAULT '', created TEXT);
CREATE TABLE IF NOT EXISTS contents(id INTEGER PRIMARY KEY, campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  channel TEXT, title TEXT, body TEXT, language TEXT DEFAULT 'English', status TEXT DEFAULT 'draft', version INTEGER DEFAULT 1,
  source TEXT DEFAULT 'demo', parent_id INTEGER, quality INTEGER DEFAULT 0, created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS versions(id INTEGER PRIMARY KEY, content_id INTEGER REFERENCES contents(id) ON DELETE CASCADE,
  version INTEGER, title TEXT, body TEXT, note TEXT, source TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY, content_id INTEGER REFERENCES contents(id) ON DELETE CASCADE,
  rating INTEGER, tags TEXT DEFAULT '', comment TEXT DEFAULT '', created TEXT);
CREATE TABLE IF NOT EXISTS calendar(id INTEGER PRIMARY KEY, campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
  content_id INTEGER, date TEXT, channel TEXT, title TEXT, notes TEXT DEFAULT '', status TEXT DEFAULT 'planned', created TEXT);
CREATE TABLE IF NOT EXISTS personas(id INTEGER PRIMARY KEY, campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
  data TEXT, source TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS visuals(id INTEGER PRIMARY KEY, campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
  content_id INTEGER, title TEXT, prompt TEXT, style TEXT, aspect TEXT, image TEXT DEFAULT '', source TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS approvals(id INTEGER PRIMARY KEY, content_id INTEGER REFERENCES contents(id) ON DELETE CASCADE,
  action TEXT, from_status TEXT, to_status TEXT, reviewer TEXT, note TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY, kind TEXT, text TEXT, created TEXT);
"""

def conn():
    os.makedirs(os.path.dirname(path()), exist_ok=True)
    c = sqlite3.connect(path())
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

def init():
    with closing(conn()) as c:
        c.executescript(SCHEMA); c.commit()

def q(sql, args=(), one=False):
    with closing(conn()) as c:
        rows = [dict(r) for r in c.execute(sql, args).fetchall()]
    return (rows[0] if rows else None) if one else rows

def x(sql, args=()):
    with closing(conn()) as c:
        cur = c.execute(sql, args); c.commit()
        return cur.lastrowid
