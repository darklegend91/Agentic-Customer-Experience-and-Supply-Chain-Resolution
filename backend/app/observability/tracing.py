"""Non-blocking Langfuse monitoring with minimized trace payloads."""
from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from functools import lru_cache, wraps
from typing import Any

from ..security.pii_masking import mask_sensitive_text

logger = logging.getLogger(__name__)
_SAFE_FIELDS = {
    'workflow_id', 'request_id', 'status', 'specialist', 'intent', 'confidence',
    'classifier_provider', 'classifier_version', 'triage_status', 'fallback_used',
    'needs_human_review', 'automatic_routing_enabled', 'review_threshold',
    'model', 'stage', 'error_type', 'outcome', 'requires_approval', 'valid',
    'safety_passed', 'reference_count', 'langgraph_node', 'langgraph_step',
    'input_truncated', 'schema_version', 'disposition', 'error_code',
    'method', 'route', 'status_code', 'latency_ms',
}
_SAFE_LISTS = {'risk_flags', 'reason_codes', 'validation_errors'}
_SAFE_CONTAINERS = {'classification', 'resolution', 'metadata'}


def mask_trace_data(*, data: Any, **_kwargs: Any) -> Any:
    """Keep diagnostic fields; never export customer text, records or credentials."""
    if isinstance(data, dict):
        safe: dict[str, Any] = {}
        for key, value in data.items():
            if key in _SAFE_FIELDS and isinstance(value, (str, int, float, bool, type(None))):
                safe[key] = mask_sensitive_text(value)[:200] if isinstance(value, str) else value
            elif key in _SAFE_LISTS and isinstance(value, list):
                safe[key] = [mask_sensitive_text(v)[:100] for v in value[:20] if isinstance(v, str)]
            elif key in _SAFE_CONTAINERS:
                safe[key] = mask_trace_data(data=value)
        return safe
    if isinstance(data, (list, tuple)):
        return [mask_trace_data(data=value) for value in data[:20]]
    return '[content omitted]'


def mask_trace_spans(*, params: Any) -> Any:
    """Also redact exported error details and metadata from third-party callbacks."""
    from langfuse.types import MaskOtelSpansResult, OtelSpanPatch
    patches = {}
    for identifier, span in params.spans.items():
        delete = []
        updates = {}
        for key, value in span.attributes.items():
            if key.endswith('.input') or key.endswith('.output'):
                try:
                    parsed = json.loads(value) if isinstance(value, str) else value
                except (ValueError, TypeError):
                    parsed = None
                updates[key] = json.dumps(mask_trace_data(data=parsed))
            elif '.metadata.' in key:
                field = key.split('.metadata.', 1)[1]
                if field not in _SAFE_FIELDS | _SAFE_LISTS | _SAFE_CONTAINERS:
                    delete.append(key)
            elif key.endswith('status_message') or key in {'exception.message', 'exception.stacktrace'}:
                updates[key] = 'Error details omitted; inspect safe application logs.'
        if delete or updates:
            patches[identifier] = OtelSpanPatch(set_attributes=updates, delete_attributes=delete)
    return MaskOtelSpansResult(span_patches=patches)


def is_langfuse_configured() -> bool:
    return bool(os.getenv('LANGFUSE_PUBLIC_KEY', '').strip()
                and os.getenv('LANGFUSE_SECRET_KEY', '').strip()
                and os.getenv('LANGFUSE_TRACING_ENABLED', 'true').lower() not in {'false', '0', 'no'})


@lru_cache(maxsize=1)
def _configured_client() -> Any:
    from langfuse import Langfuse
    return Langfuse(
        public_key=os.environ['LANGFUSE_PUBLIC_KEY'].strip(),
        secret_key=os.environ['LANGFUSE_SECRET_KEY'].strip(),
        base_url=os.getenv('LANGFUSE_BASE_URL') or os.getenv('LANGFUSE_HOST') or 'https://cloud.langfuse.com',
        environment=os.getenv('APP_ENV', 'local'),
        timeout=3,
        flush_interval=2,
        mask=mask_trace_data,
        mask_otel_spans=mask_trace_spans,
    )


def get_langfuse_client() -> Any | None:
    if not is_langfuse_configured():
        return None
    try:
        return _configured_client()
    except Exception as exc:
        logger.warning('Langfuse initialization unavailable: %s', type(exc).__name__)
        return None


def get_langfuse_callback(*, session_id: str | None = None, user_id: str | None = None,
                         tags: list[str] | None = None, metadata: dict[str, Any] | None = None) -> Any | None:
    """Use SDK v5 arguments; per-run attribution belongs in LangChain config."""
    if get_langfuse_client() is None:
        return None
    try:
        from langfuse.langchain import CallbackHandler
        return CallbackHandler(public_key=os.environ['LANGFUSE_PUBLIC_KEY'].strip())
    except Exception as exc:
        logger.warning('Langfuse callback unavailable: %s', type(exc).__name__)
        return None


@contextmanager
def trace_stage(name: str, metadata: dict[str, Any] | None = None):
    """Record local timing; tracing failures must not affect business execution."""
    client = get_langfuse_client()
    if client is None:
        yield None
        return
    try:
        context = client.start_as_current_observation(name=name, as_type='span', metadata=metadata or {})
        span = context.__enter__()
    except Exception as exc:
        logger.warning('Langfuse stage unavailable: %s', type(exc).__name__)
        yield None
        return
    try:
        yield span
    except BaseException as exc:
        try:
            span.update(level='ERROR', metadata={'error_type': type(exc).__name__})
        except Exception:
            pass
        raise
    finally:
        try:
            # Do not forward raw exception text or stack data to the exporter.
            context.__exit__(None, None, None)
        except Exception as exc:
            logger.warning('Langfuse stage completion unavailable: %s', type(exc).__name__)


def shutdown_langfuse() -> None:
    """Flush only at process shutdown, never on the request's critical path."""
    if _configured_client.cache_info().currsize:
        try:
            _configured_client().shutdown()
        except Exception as exc:
            logger.warning('Langfuse shutdown unavailable: %s', type(exc).__name__)
        finally:
            _configured_client.cache_clear()


def traced_stage(name: str):
    """Time a synchronous stage without capturing arguments or return content."""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with trace_stage(name):
                return function(*args, **kwargs)
        return wrapped
    return decorate


def update_trace_span(span: Any, **attributes: Any) -> None:
    if span is not None:
        try:
            span.update(**attributes)
        except Exception as exc:
            logger.warning('Langfuse span update unavailable: %s', type(exc).__name__)
