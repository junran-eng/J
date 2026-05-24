# ============================================================
# infra/sqlite_utils.py — SQLite 维护工具
# ============================================================
import logging, sqlite3

logger = logging.getLogger("infra.sqlite")


def checkpoint(db_path):
    """缩小 WAL 文件，将日志合并回主库"""
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
    except Exception as e:
        logger.debug("[SQLite] checkpoint %s: %s", db_path, e)


def vacuum(db_path):
    """回收磁盘空间（启动时跑一次即可）"""
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("VACUUM")
        conn.close()
        logger.info("[SQLite] vacuum %s done", db_path)
    except Exception as e:
        logger.warning("[SQLite] vacuum %s failed: %s", db_path, e)
