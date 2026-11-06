"""Pooled, read-only Neon sessions for allowlisted repositories."""

from __future__ import annotations

import os
from contextlib import contextmanager
from threading import Lock
from typing import Iterator

from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from ..runtime import require_local_development


class DatabaseUnavailable(RuntimeError):
    """The local read-only data source is not available."""


_pool: ThreadedConnectionPool | None = None
_pool_dsn: str | None = None
_pool_lock = Lock()


def _get_readonly_pool(dsn: str) -> ThreadedConnectionPool:
    """Reuse TLS connections; the Neon pooler rejects startup `options` flags."""
    global _pool, _pool_dsn
    with _pool_lock:
        if _pool is None or _pool_dsn != dsn:
            if _pool is not None:
                _pool.closeall()
            _pool = ThreadedConnectionPool(
                minconn=1,
                maxconn=8,
                dsn=dsn,
                sslmode="require",
                connect_timeout=5,
                application_name="agentic-customer-support-dev-readonly",
            )
            _pool_dsn = dsn
        return _pool


@contextmanager
def readonly_cursor() -> Iterator[RealDictCursor]:
    """Yield a cursor from the shared pool, in a read-only transaction."""
    require_local_development()
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise DatabaseUnavailable("DATABASE_URL is not configured")

    connection = None
    cursor = None
    pool = None
    discard_connection = False
    try:
        pool = _get_readonly_pool(dsn)
        connection = pool.getconn()
        connection.rollback()
        connection.set_session(readonly=True, autocommit=False)
        cursor = connection.cursor(cursor_factory=RealDictCursor)
        yield cursor
    except DatabaseUnavailable:
        discard_connection = connection is not None and bool(connection.closed)
        raise
    except Exception as exc:
        discard_connection = connection is not None
        raise DatabaseUnavailable("Neon read-only lookup failed") from exc
    finally:
        try:
            if cursor is not None:
                cursor.close()
        finally:
            if connection is not None:
                try:
                    connection.rollback()
                finally:
                    if pool is not None:
                        pool.putconn(connection, close=discard_connection or bool(connection.closed))
                    else:
                        connection.close()
