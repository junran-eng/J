# ============================================================
# infra/rag.py — RAG 向量检索（numpy 优先，纯 Python 回退）
# ============================================================
import json, logging, math, os, sqlite3
from datetime import datetime

from infra.llm import call_embedding
from infra.sqlite_utils import checkpoint as wal_checkpoint

logger = logging.getLogger("infra.rag")

MAX_VECTORS = 500
SIMILARITY_THRESHOLD = 0.3

# numpy 可选
try:
    import numpy as np
    _has_numpy = True
except ImportError:
    _has_numpy = False


def _cosine_similarity(a, b):
    """余弦相似度，兼容 numpy 和纯 Python"""
    if _has_numpy:
        a = np.array(a, dtype=np.float64)
        b = np.array(b, dtype=np.float64)
        dot = float(np.dot(a, b))
        na = float(np.linalg.norm(a))
        nb = float(np.linalg.norm(b))
    else:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb + 1e-8)


def _get_db_path():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_dir = os.path.join(base, "memory")
    os.makedirs(db_dir, exist_ok=True)
    return os.path.join(db_dir, "vectors.db")

def get_db_path():
    return _get_db_path()


def _init_db():
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS vectors (
            id TEXT PRIMARY KEY,
            vec_json TEXT NOT NULL,
            body_preview TEXT NOT NULL DEFAULT '',
            indexed_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_vectors_time ON vectors(indexed_at);
    """)
    conn.commit()
    return conn


def index(body, doc_id, api_key, api_base):
    vec = call_embedding(body[:2000], api_key, api_base)
    if vec is None:
        logger.warning("[RAG] embedding failed, skip indexing")
        return

    conn = _init_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO vectors(id, vec_json, body_preview, indexed_at) VALUES(?,?,?,?)",
            (doc_id, json.dumps(vec), body[:300], datetime.now().isoformat())
        )
        conn.commit()

        row = conn.execute("SELECT COUNT(*) as c FROM vectors").fetchone()
        if row[0] > MAX_VECTORS:
            conn.execute(
                "DELETE FROM vectors WHERE id IN (SELECT id FROM vectors ORDER BY indexed_at ASC LIMIT ?)",
                (row[0] - MAX_VECTORS,)
            )
            conn.commit()
        logger.info("[RAG] indexed id=%s, total=%d", doc_id, min(row[0], MAX_VECTORS))
    except Exception as e:
        logger.warning("[RAG] index write failed: %s", e)
    finally:
        conn.close()


def search(query, api_key, api_base, top_k=3):
    conn = _init_db()
    try:
        rows = conn.execute("SELECT id, vec_json, body_preview FROM vectors").fetchall()
    except Exception as e:
        logger.warning("[RAG] search read failed: %s", e)
        conn.close()
        return []
    conn.close()

    if not rows:
        return []

    qv = call_embedding(query, api_key, api_base)
    if qv is None:
        return []

    scored = []
    for row in rows:
        try:
            vec = json.loads(row["vec_json"])
            sim = _cosine_similarity(qv, vec)
            if sim > SIMILARITY_THRESHOLD:
                scored.append((sim, row["id"], row["body_preview"]))
        except Exception:
            continue

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {"similarity": round(s, 3), "id": pid, "preview": prev[:100]}
        for s, pid, prev in scored[:top_k]
    ]


def context(query, api_key, api_base):
    items = search(query, api_key, api_base)
    if not items:
        return ""
    ctx = "\n## RAG 历史相关\n"
    for i, item in enumerate(items, 1):
        ctx += f"{i}. (相似度{item['similarity']}) {item['preview'][:80]}...\n"
    return ctx


