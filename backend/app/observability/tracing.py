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
    'method', 'route', 'status_code', 'latency_ms', 'duration_ms', 'system',
    'operation', 'result_count', 'top_k', 'batch_size', 'dimensions', 'collection',
    'provider', 'attempt', 'locale', 'node',
    'expected_document_hit_at_1', 'expected_document_hit_at_k', 'mrr_at_k',
    'expected_version_at_1', 'expected_section_at_1', 'scope_compliance',
    'citation_metadata_completeness',
}
_SAFE_LISTS = {'risk_flags', 'reason_codes', 'validation_errors'}
_SAFE_CONTAINERS = {'classification', 'resolution', 'metadata', 'retrieval_metrics', 'semantic', 'keyword'}


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


def configure_langfuse(*, public_key: str = '', secret_key: str = '', base_url: str = '',
                       environment: str = '', enabled: str = '') -> None:
    """Load server-side Streamlit secrets into this process for shared tracing helpers."""
    values = {
        'LANGFUSE_PUBLIC_KEY': public_key,
        'LANGFUSE_SECRET_KEY': secret_key,
        'LANGFUSE_BASE_URL': base_url,
        'LANGFUSE_ENVIRONMENT': environment,
        'LANGFUSE_TRACING_ENABLED': enabled,
    }
    for key, value in values.items():
        if value:
            os.environ[key] = value.strip()


@lru_cache(maxsize=1)
def _configured_client() -> Any:
    from langfuse import Langfuse
    return Langfuse(
        public_key=os.environ['LANGFUSE_PUBLIC_KEY'].strip(),
        secret_key=os.environ['LANGFUSE_SECRET_KEY'].strip(),
        base_url=os.getenv('LANGFUSE_BASE_URL') or os.getenv('LANGFUSE_HOST') or 'https://cloud.langfuse.com',
        environment=os.getenv('LANGFUSE_ENVIRONMENT') or os.getenv('APP_ENV', 'local'),
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
def trace_attributes(*, session_id: str | None = None, tags: list[str] | None = None,
                     metadata: dict[str, Any] | None = None):
    """Propagate safe grouping attributes while keeping tracing optional."""
    client = get_langfuse_client()
    if client is None:
        yield
        return
    try:
        from langfuse import propagate_attributes
        safe_metadata = mask_trace_data(data=metadata or {})
        safe_metadata = {
            key.replace('_', ''): value
            for key, value in safe_metadata.items()
            if isinstance(key, str)
        }
        context = propagate_attributes(
            session_id=session_id,
            tags=tags,
            metadata=safe_metadata,
        )
        context.__enter__()
    except Exception as exc:
        logger.warning('Langfuse trace attributes unavailable: %s', type(exc).__name__)
        yield
        return
    try:
        yield
    finally:
        try:
            context.__exit__(None, None, None)
        except Exception as exc:
            logger.warning('Langfuse trace attribute completion unavailable: %s', type(exc).__name__)


@contextmanager
def trace_stage(name: str, metadata: dict[str, Any] | None = None,
                trace_context: dict[str, str] | None = None):
    """Record local timing; tracing failures must not affect business execution."""
    client = get_langfuse_client()
    if client is None:
        yield None
        return
    try:
        context = client.start_as_current_observation(
            name=name,
            as_type='span',
            metadata=mask_trace_data(data=metadata or {}),
            trace_context=trace_context,
        )
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


@contextmanager
def trace_model_call(name: str, model: str, *, as_type: str = 'generation',
                     metadata: dict[str, Any] | None = None):
    """Record model identity and latency without exporting prompt or output data."""
    client = get_langfuse_client()
    if client is None:
        yield None
        return
    try:
        context = client.start_as_current_observation(
            name=name,
            as_type=as_type,
            model=str(model)[:160],
            metadata=mask_trace_data(data=metadata or {}),
        )
        observation = context.__enter__()
    except Exception as exc:
        logger.warning('Langfuse model observation unavailable: %s', type(exc).__name__)
        yield None
        return
    try:
        yield observation
    except BaseException as exc:
        try:
            observation.update(level='ERROR', metadata={'error_type': type(exc).__name__})
        except Exception:
            pass
        raise
    finally:
        try:
            # Inputs and outputs intentionally remain unset to keep customer data out of traces.
            context.__exit__(None, None, None)
        except Exception as exc:
            logger.warning('Langfuse model observation completion unavailable: %s', type(exc).__name__)


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
            with trace_stage(name) as span:
                result = function(*args, **kwargs)
                if isinstance(result, (list, tuple, set)):
                    update_trace_span(span, output={'result_count': len(result)})
                elif isinstance(result, dict) and isinstance(result.get('metrics'), dict):
                    summary = {
                        'result_count': len(result['cases']) if isinstance(result.get('cases'), list) else 0,
                        'method': '+'.join(str(value) for value in result.get('methods', []) if isinstance(value, str)),
                        'top_k': result.get('top_k'),
                        'retrieval_metrics': result['metrics'],
                    }
                    update_trace_span(span, output=summary)
                elif isinstance(result, dict) and isinstance(result.get('cases'), list):
                    update_trace_span(span, output={'result_count': len(result['cases'])})
                return result
        return wrapped
    return decorate


def update_model_usage(observation: Any, usage: dict[str, Any] | None) -> None:
    """Attach provider-reported token counts, if present, without guessing usage."""
    if observation is None or not isinstance(usage, dict):
        return
    prompt_tokens = usage.get('prompt_tokens', usage.get('input_tokens'))
    completion_tokens = usage.get('completion_tokens', usage.get('output_tokens'))
    counts: dict[str, int] = {}
    if isinstance(prompt_tokens, int) and not isinstance(prompt_tokens, bool) and prompt_tokens >= 0:
        counts['input_tokens'] = prompt_tokens
    if isinstance(completion_tokens, int) and not isinstance(completion_tokens, bool) and completion_tokens >= 0:
        counts['output_tokens'] = completion_tokens
    if counts:
        try:
            observation.update(usage_details=counts)
        except Exception as exc:
            logger.warning('Langfuse usage update unavailable: %s', type(exc).__name__)


def update_trace_span(span: Any, **attributes: Any) -> None:
    if span is not None:
        try:
            for field in ('input', 'output', 'metadata'):
                if field in attributes:
                    attributes[field] = mask_trace_data(data=attributes[field])
            span.update(**attributes)
        except Exception as exc:
            logger.warning('Langfuse span update unavailable: %s', type(exc).__name__)
