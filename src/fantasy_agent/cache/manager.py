import sqlite3
import pickle
import hashlib
import time
import functools
from pathlib import Path

CACHE_DIR = Path.home() / ".fantasy_agent"
CACHE_DB = CACHE_DIR / "cache.db"


def _get_conn() -> sqlite3.Connection:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CACHE_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            key TEXT PRIMARY KEY,
            value BLOB,
            expires_at REAL
        )
    """)
    conn.commit()
    return conn


def cache(ttl_seconds: int = 300):
    """
    Decorator that caches function return values in SQLite with TTL.
    Skips the first positional arg (self) when building the cache key.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Skip self/cls for the cache key
            key_data = f"{func.__qualname__}:{args[1:]}:{sorted(kwargs.items())}"
            key = hashlib.md5(key_data.encode()).hexdigest()

            conn = _get_conn()
            try:
                row = conn.execute(
                    "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
                ).fetchone()

                if row and time.time() < row[1]:
                    return pickle.loads(row[0])

                result = func(*args, **kwargs)

                conn.execute(
                    "INSERT OR REPLACE INTO cache (key, value, expires_at) "
                    "VALUES (?, ?, ?)",
                    (key, pickle.dumps(result), time.time() + ttl_seconds),
                )
                conn.commit()
                return result
            finally:
                conn.close()

        return wrapper
    return decorator


def clear_cache(prefix: str = None):
    """Clear all cached data, or just entries matching a prefix string."""
    conn = _get_conn()
    try:
        if prefix:
            # We can't filter by key prefix easily since keys are MD5 hashes,
            # so we delete all — prefix arg is kept for future label-based caching
            conn.execute("DELETE FROM cache")
        else:
            conn.execute("DELETE FROM cache")
        conn.commit()
    finally:
        conn.close()


def cache_status() -> dict:
    """Returns stats about the current cache."""
    conn = _get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        active = conn.execute(
            "SELECT COUNT(*) FROM cache WHERE expires_at > ?", (time.time(),)
        ).fetchone()[0]
        size_bytes = CACHE_DB.stat().st_size if CACHE_DB.exists() else 0
        return {
            "path": str(CACHE_DB),
            "total_entries": total,
            "active_entries": active,
            "expired_entries": total - active,
            "size_kb": round(size_bytes / 1024, 1),
        }
    finally:
        conn.close()


def evict_expired():
    """Remove expired entries to keep the DB tidy."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM cache WHERE expires_at <= ?", (time.time(),))
        conn.commit()
    finally:
        conn.close()
