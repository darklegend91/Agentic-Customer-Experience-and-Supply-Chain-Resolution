"""Pooled, read-only Neon sessions for allowlisted repositories."""

from __future__ import annotations

import os
from contextlib import contextmanager
from functools import wraps
from threading import Lock
from typing import Callable, Iterator, ParamSpec, TypeVar

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from ..observability.tracing import trace_stage
from ..runtime import require_local_development


class DatabaseUnavailable(RuntimeError):
    """The local read-only data source is not available."""


P = ParamSpec("P")
T = TypeVar("T")


def retry_readonly_connection(read: Callable[P, T]) -> Callable[P, T]:
    """Retry a complete read-only operation once after a connection failure."""
    @wraps(read)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return read(*args, **kwargs)
        except DatabaseUnavailable as exc:
            cause = exc.__cause__
            connection_error = isinstance(cause, psycopg2.InterfaceError) or (
                isinstance(cause, psycopg2.OperationalError)
                and (cause.pgcode in {None, "57P01", "57P02", "57P03"} or cause.pgcode.startswith("08"))
            )
            if not connection_error:
                raise
            with trace_stage("database.neon_readonly_retry", {"error_type": type(cause).__name__}):
                return read(*args, **kwargs)

    return wrapped


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
def _readonly_cursor_impl() -> Iterator[RealDictCursor]:
    """Yield a cursor from the shared pool, in a read-only transaction."""
    require_local_development()
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise DatabaseUnavailable("DATABASE_URL is not configured")

    try:
        pool = _get_readonly_pool(dsn)
        connection = pool.getconn()
        discard_connection = True
        try:
            connection.rollback()
            connection.set_session(readonly=True, autocommit=False)
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            try:
                yield cursor
            finally:
                cursor.close()
            connection.rollback()
            discard_connection = False
        finally:
            pool.putconn(connection, close=discard_connection or bool(connection.closed))
    except DatabaseUnavailable:
        raise
    except Exception as exc:
        raise DatabaseUnavailable("Neon read-only lookup failed") from exc


@contextmanager
def readonly_cursor() -> Iterator[RealDictCursor]:
    """Yield a cursor and record read-only database latency without SQL or row data."""
    with trace_stage("database.neon_readonly", {
        "system": "neon-postgresql",
        "operation": "read",
    }):
        with _readonly_cursor_impl() as cursor:
            yield cursor
