# ============================================================
# infra/memory.py - SQLite memory layer (review + performance + filters)
# ============================================================
import logging, os, sqlite3, uuid
from datetime import datetime
from infra.sqlite_utils import checkpoint as wal_checkpoint

logger = logging.getLogger("infra.memory")


def _get_db_path():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_dir = os.path.join(base, "memory")
    os.makedirs(db_dir, exist_ok=True)
    return os.path.join(db_dir, "conversations.db")


def get_db_path():
    return _get_db_path()


def get_connection():
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, title TEXT, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT, role TEXT, content TEXT,
                content_type TEXT, score INTEGER, body TEXT, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT, score INTEGER, elapsed REAL, tokens INTEGER,
                content_type TEXT, status TEXT DEFAULT 'pending_review',
                published_style TEXT DEFAULT '',
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS schedules (
                id TEXT PRIMARY KEY, topic TEXT, keywords TEXT, model TEXT,
                trigger_type TEXT, trigger_value TEXT, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE, reads INTEGER DEFAULT 0,
                shares INTEGER DEFAULT 0, likes INTEGER DEFAULT 0,
                recorded_at TEXT
            );
            CREATE TABLE IF NOT EXISTS review_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                author TEXT DEFAULT 'reviewer',
                comment TEXT NOT NULL,
                stage TEXT DEFAULT 'review',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS review_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                action TEXT NOT NULL,
                from_status TEXT DEFAULT '',
                to_status TEXT NOT NULL,
                operator TEXT DEFAULT 'system',
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
        """)
        conn.commit()
        _run_migrations(conn)
        wal_checkpoint(_get_db_path())
    finally:
        conn.close()


def _run_migrations(conn):
    """Centralized schema migration - all ALTER + INDEX in one place"""
    try: conn.execute("ALTER TABLE stats ADD COLUMN reason TEXT DEFAULT ''")
    except sqlite3.OperationalError: pass
    for col, df in [("content_type", ""), ("status", ""), ("body", "")]:
        try: conn.execute(f"ALTER TABLE stats ADD COLUMN {col} TEXT DEFAULT '{df}'")
        except sqlite3.OperationalError: pass
    try: conn.execute("UPDATE stats SET status='approved' WHERE status IS NULL OR status=''")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE stats ADD COLUMN published_style TEXT DEFAULT ''")
    except sqlite3.OperationalError: pass
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_stats_status ON stats(status)",
        "CREATE INDEX IF NOT EXISTS idx_stats_type ON stats(content_type)",
        "CREATE INDEX IF NOT EXISTS idx_stats_date ON stats(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_stats_style ON stats(published_style)",
    ]:
        try: conn.execute(idx_sql)
        except sqlite3.OperationalError: pass
    conn.commit()


def _estimate_tokens(text):
    """Rough token count: CJK chars ~1.5 tokens, others ~0.3 tokens"""
    import re
    cjk = len(re.findall(r'[一-鿿㐀-䶿]', text))
    other = len(text) - cjk
    return int(cjk * 1.5 + other * 0.3)

def save_result(topic, content_type, result, output_dir):
    """Save generation result, default status=pending_review"""
    conn = get_connection()
    try:
        sid = uuid.uuid4().hex[:12]
        now = datetime.now().isoformat()
        score = result["evaluation"]["overall_score"]
        final_body = result["final_body"]
        final_title = result["final_title"]

        conn.execute("INSERT INTO sessions VALUES(?,?,?)", (sid, topic[:80], now))
        conn.execute(
            "INSERT INTO messages(session_id,role,content,content_type,score,body,created_at) VALUES(?,?,?,?,?,?,?)",
            (sid, "user", topic, "", 0, "", now)
        )
        conn.execute(
            "INSERT INTO messages(session_id,role,content,content_type,score,body,created_at) VALUES(?,?,?,?,?,?,?)",
            (sid, "agent", final_title, content_type, score, final_body, now)
        )
        conn.execute(
            "INSERT INTO stats(topic,score,elapsed,tokens,content_type,status,created_at) VALUES(?,?,?,?,?,?,?)",
            (topic[:80], score, result["elapsed_seconds"], _estimate_tokens(final_body), content_type, "pending_review", now)
        )
        conn.commit()
        wal_checkpoint(_get_db_path())
        logger.info("[MEM] saved session=%s score=%d status=pending_review", sid, score)
    except Exception as e:
        logger.warning("[MEM] save failed: %s", e)
    finally:
        conn.close()


# ============================================================
# Review
# ============================================================
def _audit_log(session_id, action, from_status, to_status, operator="system", note=""):
    """记录审核操作日志"""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO review_audit_log(session_id,action,from_status,to_status,operator,note,created_at) VALUES(?,?,?,?,?,?,?)",
            (session_id, action, from_status, to_status, operator, note, datetime.now().isoformat()))
        conn.commit()
    except Exception as e:
        logger.debug("[MEM] audit log failed: %s", e)
    finally:
        conn.close()


def _get_current_status(session_id):
    """Get current status for a session"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT st.status FROM stats st "
            "WHERE EXISTS (SELECT 1 FROM sessions s WHERE s.title=st.topic AND s.created_at=st.created_at AND s.id=?)",
            (session_id,)).fetchone()
        return row["status"] if row else ""
    except Exception:
        return ""
    finally:
        conn.close()


def approve_result(session_id, operator="reviewer"):
    old = _get_current_status(session_id)
    ok = _set_status(session_id, "approved")
    if ok:
        _audit_log(session_id, "approve", old, "approved", operator)
    return ok


def reject_result(session_id, reason="", operator="reviewer"):
    old = _get_current_status(session_id)
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE stats SET status='rejected', reason=? "
            "WHERE EXISTS (SELECT 1 FROM sessions s WHERE s.title=stats.topic AND s.created_at=stats.created_at AND s.id=?)",
            (reason, session_id))
        conn.commit()
        wal_checkpoint(_get_db_path())
        _audit_log(session_id, "reject", old, "rejected", operator, reason)
        logger.info("[MEM] session=%s rejected reason=%s", session_id, reason[:40] if reason else "-")
        return True
    except Exception as e:
        logger.warning("[MEM] reject failed: %s", e)
        return False
    finally:
        conn.close()


def _set_status(session_id, status):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE stats SET status=? "
            "WHERE EXISTS (SELECT 1 FROM sessions s WHERE s.title=stats.topic AND s.created_at=stats.created_at AND s.id=?)",
            (status, session_id))
        conn.commit()
        wal_checkpoint(_get_db_path())
        logger.info("[MEM] session=%s status=%s", session_id, status)
        return True
    except Exception as e:
        logger.warning("[MEM] set_status failed: %s", e)
        return False
    finally:
        conn.close()


# ---- Review comments ----
def add_review_comment(session_id, comment, author="reviewer", stage="review"):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO review_comments(session_id,author,comment,stage,created_at) VALUES(?,?,?,?,?)",
            (session_id, author, comment, stage, datetime.now().isoformat()))
        conn.commit()
        wal_checkpoint(_get_db_path())
        logger.info("[MEM] comment added to %s by %s", session_id, author)
        return True
    except Exception as e:
        logger.warning("[MEM] add_comment failed: %s", e)
        return False
    finally:
        conn.close()


def get_review_comments(session_id):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT author, comment, stage, created_at FROM review_comments WHERE session_id=? ORDER BY id",
            (session_id,)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("[MEM] get_comments failed: %s", e)
        return []
    finally:
        conn.close()


def get_audit_log(session_id):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT action, from_status, to_status, operator, note, created_at FROM review_audit_log WHERE session_id=? ORDER BY id",
            (session_id,)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("[MEM] audit_log failed: %s", e)
        return []
    finally:
        conn.close()


def get_rejected(limit=20):
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT s.id, s.title, s.created_at, st.score, st.content_type, st.reason
            FROM sessions s JOIN stats st ON s.title = st.topic AND s.created_at = st.created_at
            WHERE st.status = 'rejected'
            ORDER BY st.created_at DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("[MEM] get_rejected failed: %s", e)
        return []
    finally:
        conn.close()


def get_pending_reviews():
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT s.id, s.title, s.created_at, st.score, st.content_type, st.status
            FROM sessions s JOIN stats st ON s.title = st.topic AND s.created_at = st.created_at
            WHERE st.status = 'pending_review'
            ORDER BY st.created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("[MEM] get_pending failed: %s", e)
        return []
    finally:
        conn.close()


# ============================================================
# Performance tracking
# ============================================================
def record_performance(session_id, reads=0, shares=0, likes=0):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO performance(session_id,reads,shares,likes,recorded_at) VALUES(?,?,?,?,?)",
            (session_id, reads, shares, likes, datetime.now().isoformat())
        )
        conn.commit()
        wal_checkpoint(_get_db_path())
        return True
    except Exception as e:
        logger.warning("[MEM] record_perf failed: %s", e)
        return False
    finally:
        conn.close()


def get_performance(session_id):
    conn = get_connection()
    try:
        r = conn.execute("SELECT * FROM performance WHERE session_id=?", (session_id,)).fetchone()
        return dict(r) if r else {"reads": 0, "shares": 0, "likes": 0}
    except Exception as e:
        logger.warning("[MEM] get_perf failed: %s", e)
        return {"reads": 0, "shares": 0, "likes": 0}
    finally:
        conn.close()


def set_published_style(session_id, style):
    """记录实际发布时选用的版本风格（标准版/数据版/故事版）"""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE stats SET published_style=? "
            "WHERE EXISTS (SELECT 1 FROM sessions s WHERE s.title=stats.topic AND s.created_at=stats.created_at AND s.id=?)",
            (style, session_id))
        conn.commit()
        wal_checkpoint(_get_db_path())
        logger.info("[MEM] session=%s published_style=%s", session_id, style)
        return True
    except Exception as e:
        logger.warning("[MEM] set_published_style failed: %s", e)
        return False
    finally:
        conn.close()


def get_performance_stats():
    """按内容类型 + 版本风格分组的效果统计"""
    conn = get_connection()
    try:
        by_type = conn.execute("""
            SELECT st.content_type,
                   COUNT(p.session_id) as cnt,
                   AVG(p.reads) as avg_reads,
                   AVG(p.shares) as avg_shares,
                   AVG(p.likes) as avg_likes,
                   SUM(p.reads) as total_reads
            FROM performance p
            JOIN sessions s ON p.session_id = s.id
            JOIN stats st ON s.title = st.topic AND s.created_at = st.created_at
            GROUP BY st.content_type
        """).fetchall()
        by_style = conn.execute("""
            SELECT st.published_style,
                   COUNT(p.session_id) as cnt,
                   AVG(p.reads) as avg_reads,
                   SUM(p.reads) as total_reads
            FROM performance p
            JOIN sessions s ON p.session_id = s.id
            JOIN stats st ON s.title = st.topic AND s.created_at = st.created_at
            WHERE st.published_style != ''
            GROUP BY st.published_style
        """).fetchall()
        return {
            "by_type": [dict(r) for r in by_type],
            "by_style": [dict(r) for r in by_style],
        }
    except Exception as e:
        logger.warning("[MEM] get_perf_stats failed: %s", e)
        return {"by_type": [], "by_style": []}
    finally:
        conn.close()


# ============================================================
# Session queries (with filters)
# ============================================================
def get_token_stats():
    """Token cost statistics (monthly breakdown)"""
    conn = get_connection()
    try:
        total = conn.execute("SELECT SUM(tokens) as t FROM stats WHERE status='approved'").fetchone()
        monthly = conn.execute("""
            SELECT substr(created_at,1,7) as month, SUM(tokens) as t, COUNT(*) as cnt
            FROM stats WHERE status='approved' AND created_at > date('now','-12 months')
            GROUP BY month ORDER BY month
        """).fetchall()
        from infra.llm import estimate_cost
        total_t = total["t"] or 0
        return {
            "total_tokens": total_t,
            "estimated_cost_yuan": estimate_cost("default", total_t),
            "monthly": [{"month": r["month"], "tokens": r["t"], "count": r["cnt"]} for r in monthly],
        }
    except Exception as e:
        logger.warning("[MEM] get_token_stats failed: %s", e)
        return {"total_tokens": 0, "estimated_cost_yuan": 0, "monthly": []}
    finally:
        conn.close()


def get_sessions(limit=50, content_type=None, date_from=None, date_to=None, q=None):
    conn = get_connection()
    try:
        sql = "SELECT s.id, s.title, s.created_at, st.content_type, st.status FROM sessions s LEFT JOIN stats st ON s.title = st.topic AND s.created_at = st.created_at WHERE 1=1"
        params = []
        if content_type:
            sql += " AND st.content_type = ?"
            params.append(content_type)
        if date_from:
            sql += " AND s.created_at >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND s.created_at <= ?"
            params.append(date_to + "T23:59:59")
        if q:
            sql += " AND s.title LIKE ?"
            params.append(f"%{q}%")
        sql += " ORDER BY s.created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("[MEM] get_sessions failed: %s", e)
        return []
    finally:
        conn.close()


def get_messages(session_id):
    conn = get_connection()
    try:
        msgs = conn.execute(
            "SELECT role,content,content_type,score,body,created_at FROM messages WHERE session_id=? ORDER BY id",
            (session_id,)
        ).fetchall()
        return [dict(m) for m in msgs]
    except Exception as e:
        logger.warning("[MEM] get_messages failed: %s", e)
        return []
    finally:
        conn.close()


def delete_session(session_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM performance WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        conn.commit()
        wal_checkpoint(_get_db_path())
        return True
    except Exception as e:
        logger.warning("[MEM] delete_session failed: %s", e)
        return False
    finally:
        conn.close()


def get_stats():
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) as c, AVG(score) as a FROM stats WHERE status='approved'").fetchone()
        today = conn.execute(
            "SELECT COUNT(*) as c FROM stats WHERE date(created_at)=date('now','localtime')"
        ).fetchone()
        pending = conn.execute("SELECT COUNT(*) as c FROM stats WHERE status='pending_review'").fetchone()
        total_tokens = conn.execute("SELECT SUM(tokens) as t FROM stats WHERE status='approved'").fetchone()
        from infra.llm import estimate_cost
        total_t = total_tokens["t"] or 0
        return {
            "total": total["c"] or 0,
            "avg_score": round(total["a"] or 0, 1),
            "today": today["c"] or 0,
            "pending": pending["c"] or 0,
            "total_tokens": total_t,
            "estimated_cost": estimate_cost("default", total_t),
        }
    except Exception as e:
        logger.warning("[MEM] get_stats failed: %s", e)
        return {"total": 0, "avg_score": 0, "today": 0, "pending": 0}
    finally:
        conn.close()


def save_schedule(job_id, topic, keywords, model, trigger_type, trigger_value):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO schedules VALUES(?,?,?,?,?,?,?)",
            (job_id, topic, ",".join(keywords), model, trigger_type, trigger_value, datetime.now().isoformat())
        )
        conn.commit()
    finally:
        conn.close()


def delete_schedule(job_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM schedules WHERE id=?", (job_id,))
        conn.commit()
    finally:
        conn.close()


def get_schedules():
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM schedules").fetchall()]
    except Exception as e:
        logger.warning("[MEM] get_schedules failed: %s", e)
        return []
    finally:
        conn.close()
