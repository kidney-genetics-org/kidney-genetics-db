"""Uniform tool execution wrapper: the GTS response envelope around a service.

Every tool returns the GeneFoundry response envelope v1.2: ``success``, the
service payload unchanged under ``result``, and ``_meta`` provenance
(``source``, ``data_version``, ``retrieved_at``). ``request_id``,
``elapsed_ms`` and ``unsafe_for_clinical_use`` are stamped by
:class:`~kidney_genetics_mcp.server.EnvelopeMiddleware`, which also sets MCP
``isError`` on a ``success: false`` frame.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ..client.api_client import FETCH_TIMES
from ..contract import VERSION
from .errors import McpToolError
from .shaping import build_meta

if TYPE_CHECKING:
    from ..client.api_client import ApiClient

#: ``_meta.source``: the source database's short name (the namespace token).
SOURCE = "kgdb"


def _utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _data_version(client: ApiClient) -> str:
    """The live API's version: the data are served live, not from a release."""
    try:
        body: Any = await client.get(VERSION)
        version = body["backend"]["version"]
    except Exception:  # noqa: BLE001 — provenance must not fail a good answer
        return "unknown"
    return str(version) if version else "unknown"


async def run_tool(
    coro_factory: Callable[[], Awaitable[dict[str, Any]]],
    *,
    data_class: str,
    response_mode: str,
    client: ApiClient | None = None,
) -> dict[str, Any]:
    """Execute a service handler and wrap it in the success or error envelope.

    Times the handler, attaches the ``data_class`` tag and a ``meta`` block to
    the payload, and consumes the internal ``_dropped``/``_meta`` channels a
    service may set:

    - ``_dropped`` — a ``dropped_summary`` from
      :func:`~kidney_genetics_mcp.services.shaping.apply_budget` (signals
      truncation).
    - ``_meta`` — extra meta fields to surface (sampling signals,
      ``applied_sort``, ``ignored_params``, …) so no server behavior stays
      silent.

    A :class:`~kidney_genetics_mcp.services.errors.McpToolError` is returned as
    its error frame. Any other (unexpected) exception is mapped to an
    ``internal`` frame so a bug never leaks a stack trace or internal route.

    Args:
        coro_factory: A zero-arg callable returning the awaitable service
            handler (so timing wraps the actual work, not coroutine creation).
        data_class: The ``data_class`` tag for the payload.
        response_mode: The resolved response_mode echoed in ``meta``.
        client: The API client the handler reads through; it supplies the
            ``_meta`` provenance. ``None`` for a tool that returns no data.

    Returns:
        ``{"success": True, "result": payload, "_meta": {...}}`` or an error
        frame ``{"success": False, "error_code", "message", "retryable", ...}``.
    """
    start = time.monotonic()
    token = FETCH_TIMES.set([])
    try:
        result = await coro_factory()
        fetched = FETCH_TIMES.get() or []
    except McpToolError as exc:
        return exc.to_envelope()
    except Exception:  # noqa: BLE001 — never leak an internal error to clients
        return McpToolError(
            "internal",
            "the request could not be completed",
        ).to_envelope()
    finally:
        FETCH_TIMES.reset(token)
    elapsed_ms = round((time.monotonic() - start) * 1000, 1)
    dropped = result.pop("_dropped", None)
    extra_meta = result.pop("_meta", None)
    # Attach data_class before measuring so effective_chars reflects the real
    # serialized payload (everything except the self-referential meta block).
    result["data_class"] = data_class
    effective_chars = len(json.dumps(result, default=str))
    meta = build_meta(
        mode=response_mode,
        effective_chars=effective_chars,
        dropped=dropped,
        extra=extra_meta,
    )
    meta["elapsed_ms"] = elapsed_ms
    result["meta"] = meta
    envelope_meta: dict[str, Any] = {"source": SOURCE}
    if client is not None:
        envelope_meta["data_version"] = await _data_version(client)
        envelope_meta["retrieved_at"] = _utc(min(fetched) if fetched else time.time())
    return {"success": True, "result": result, "_meta": envelope_meta}
