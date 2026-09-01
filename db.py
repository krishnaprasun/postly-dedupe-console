"""Decision store. Postgres when DATABASE_URL is set (Render), SQLite locally.

Decisions are the only thing a reviewer's work produces, so they must outlive the
process. On Render's free plan the filesystem is wiped on every sleep/restart,
which is why this talks to Postgres there rather than to a local file.
"""
import os, sqlite3, time
from pathlib import Path

DB_URL = os.environ.get("DATABASE_URL", "")
PG = DB_URL.startswith(("postgres://", "postgresql://"))
SQLITE_PATH = Path(__file__).resolve().parent / "data" / "decisions.db"

if PG:
    import psycopg2, psycopg2.extras

def conn():
    if PG:
        return psycopg2.connect(DB_URL, sslmode=os.environ.get("PGSSLMODE", "require"),
                                cursor_factory=psycopg2.extras.RealDictCursor)
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(SQLITE_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c

_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS decision (
  cluster_id TEXT PRIMARY KEY, verdict TEXT NOT NULL, keeper_row INTEGER,
  note TEXT DEFAULT '', reviewer TEXT DEFAULT '', ts DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS history (
  id SERIAL PRIMARY KEY, cluster_id TEXT, verdict TEXT, keeper_row INTEGER,
  note TEXT, reviewer TEXT, ts DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS execution (
  id SERIAL PRIMARY KEY, ts DOUBLE PRECISION, mode TEXT, rows INTEGER, detail TEXT);
"""
_LITE_SCHEMA = _PG_SCHEMA.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT") \
                         .replace("DOUBLE PRECISION", "REAL")

def _q(s):
    """SQLite uses ?, psycopg2 uses %s."""
    return s.replace("?", "%s") if PG else s

def init():
    with conn() as c:
        cur = c.cursor()
        for stmt in (_PG_SCHEMA if PG else _LITE_SCHEMA).strip().split(";"):
            if stmt.strip(): cur.execute(stmt)
        c.commit()

def decide(cluster_id, verdict, keeper_row, note="", reviewer=""):
    now = time.time()
    with conn() as c:
        cur = c.cursor()
        if PG:
            cur.execute("""INSERT INTO decision(cluster_id,verdict,keeper_row,note,reviewer,ts)
                VALUES(%s,%s,%s,%s,%s,%s)
                ON CONFLICT(cluster_id) DO UPDATE SET verdict=EXCLUDED.verdict,
                keeper_row=EXCLUDED.keeper_row, note=EXCLUDED.note,
                reviewer=EXCLUDED.reviewer, ts=EXCLUDED.ts""",
                (cluster_id, verdict, keeper_row, note, reviewer, now))
        else:
            cur.execute("""INSERT INTO decision(cluster_id,verdict,keeper_row,note,reviewer,ts)
                VALUES(?,?,?,?,?,?) ON CONFLICT(cluster_id) DO UPDATE SET
                verdict=excluded.verdict, keeper_row=excluded.keeper_row,
                note=excluded.note, reviewer=excluded.reviewer, ts=excluded.ts""",
                (cluster_id, verdict, keeper_row, note, reviewer, now))
        cur.execute(_q("INSERT INTO history(cluster_id,verdict,keeper_row,note,reviewer,ts) "
                       "VALUES(?,?,?,?,?,?)"),
                    (cluster_id, verdict, keeper_row, note, reviewer, now))
        c.commit()

def all_decisions():
    with conn() as c:
        cur = c.cursor(); cur.execute("SELECT * FROM decision")
        return {r["cluster_id"]: dict(r) for r in cur.fetchall()}

def get(cluster_id):
    with conn() as c:
        cur = c.cursor()
        cur.execute(_q("SELECT * FROM decision WHERE cluster_id=?"), (cluster_id,))
        r = cur.fetchone()
        return dict(r) if r else None

def history():
    with conn() as c:
        cur = c.cursor(); cur.execute("SELECT * FROM history ORDER BY ts DESC")
        return [dict(r) for r in cur.fetchall()]

def log_execution(mode, rows, detail):
    with conn() as c:
        cur = c.cursor()
        cur.execute(_q("INSERT INTO execution(ts,mode,rows,detail) VALUES(?,?,?,?)"),
                    (time.time(), mode, rows, detail))
        c.commit()

def executions():
    with conn() as c:
        cur = c.cursor(); cur.execute("SELECT * FROM execution ORDER BY id DESC LIMIT 50")
        return [dict(r) for r in cur.fetchall()]
