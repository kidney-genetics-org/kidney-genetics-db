"""Read-only httpx client restricted to the endpoint allowlist, with a TTL cache."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

import httpx

from ..contract import (
    ANNOTATION_SOURCE_VALUES,
    EVIDENCE_GROUP_VALUES,
    EVIDENCE_TIER_VALUES,
    GENE_SORT_FIELD_VALUES,
)
from ..services.errors import McpToolError
from .allowlist import assert_allowed

#: Wall-clock times (epoch seconds) at which the data read in the current tool
#: call was obtained from the API; a cache hit reports its original fetch time.
#: ``run_tool`` sets a fresh list per call and reports ``_meta.retrieved_at``.
FETCH_TIMES: ContextVar[list[float] | None] = ContextVar("FETCH_TIMES", default=None)


def _note_fetch(fetched_at: float) -> None:
    times = FETCH_TIMES.get()
    if times is not None:
        times.append(fetched_at)


#: Map upstream query-parameter names → the contract enum that constrains them,
#: so a 422 error envelope can surface ``allowed`` values and a calling LLM can
#: self-correct in a single retry.
_FIELD_ALLOWED: dict[str, list[str]] = {
    "tier": sorted(EVIDENCE_TIER_VALUES),
    "group": sorted(EVIDENCE_GROUP_VALUES),
    "sort": sorted(GENE_SORT_FIELD_VALUES),
    "source": sorted(ANNOTATION_SOURCE_VALUES),
}


def _build_422_error(resp: httpx.Response) -> McpToolError:
    """Translate an upstream 422 into an actionable ``invalid_input`` error.

    Parses the FastAPI validation body
    (``{"detail":[{"loc":[...],"msg":"...","input":...}]}``) to name the
    offending field and value, attaching ``field``, ``allowed`` (when the field
    maps to a known contract enum) and a fixed ``hint`` (never the caller's value
    or the upstream body, GTS-CORE-TXT-04) so
    a consuming model can correct its call without fetching raw schemas.

    Args:
        resp: The 422 :class:`httpx.Response` returned by the upstream API.

    Returns:
        A populated :class:`McpToolError` with code ``invalid_input``.
    """
    try:
        body: Any = resp.json()
    except (json.JSONDecodeError, ValueError):
        body = None

    detail = body.get("detail") if isinstance(body, dict) else None

    if isinstance(detail, list) and detail and isinstance(detail[0], dict):
        first = detail[0]
        loc = first.get("loc") or []
        field = str(loc[-1]) if loc else "unknown"
        allowed = _FIELD_ALLOWED.get(field)
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,63}", field):
            field = "unknown"

        return McpToolError(
            "invalid_input",
            "the data API rejected a parameter value",
            field=field,
            allowed_values=allowed,
            hint=(
                "use one of allowed_values"
                if allowed is not None
                else "check the parameter against get_capabilities filterable_fields"
            ),
        )

    return McpToolError(
        "invalid_input",
        "the data API rejected the request parameters",
        field="unknown",
        hint="check parameters against get_capabilities filterable_fields",
    )


class ApiClient:
    """Async client for the public KGDB ``/api`` surface (allowlisted GETs)."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        cache_ttl: int = 300,
        cache_max_entries: int = 1024,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize the client with a base URL, request timeout, and cache TTL.

        Args:
            base_url: Base URL for the API (e.g. ``http://localhost:8000``).
            timeout: HTTP request timeout in seconds.
            cache_ttl: Time-to-live for cached responses in seconds.
            cache_max_entries: Maximum number of cached responses retained;
                the oldest entry is evicted first once the bound is reached.
            clock: Monotonic clock callable (injectable for deterministic tests).
        """
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )
        self._cache_ttl = cache_ttl
        self._cache_max_entries = max(cache_max_entries, 1)
        self._clock = clock
        self._cache: dict[str, tuple[float, Any, float]] = {}

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET an allowlisted path and return the parsed JSON body.

        Args:
            path: The API path relative to ``base_url`` (must be allowlisted).
            params: Optional query parameters forwarded to the request.

        Returns:
            The deserialized JSON response body.

        Raises:
            PermissionError: If a ``GET`` on *path* is not on the allowlist.
            McpToolError: On 404 (``not_found``), 422/400/409
                (``invalid_input``), 300 (``ambiguous_query``), or 5xx / other
                4xx / network errors (``upstream_unavailable``). Messages are
                domain-framed and never echo the internal route/host.
        """
        assert_allowed("GET", path)
        key = path + "?" + json.dumps(params or {}, sort_keys=True)
        now = self._clock()
        hit = self._cache.get(key)
        if hit and hit[0] > now:
            _note_fetch(hit[2])
            return hit[1]
        try:
            resp = await self._client.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise McpToolError(
                "upstream_unavailable", "upstream API timed out"
            ) from exc
        except httpx.HTTPError as exc:
            raise McpToolError("upstream_unavailable", "upstream API error") from exc

        if resp.status_code == 300:
            # Multiple candidates — surface the body's candidates as choices so
            # the caller can disambiguate.
            choices = _extract_choices(resp)
            raise McpToolError(
                "ambiguous_query",
                "the query matched multiple records; choose one",
                choices=choices,
            )
        if resp.status_code == 404:
            raise McpToolError(
                "not_found",
                "the requested record was not found",
                hint=(
                    "verify the identifier via resolve_gene or"
                    " search_genes before fetching"
                ),
            )
        if resp.status_code == 422:
            raise _build_422_error(resp)
        if resp.status_code >= 500:
            raise McpToolError("upstream_unavailable", "upstream API unavailable")
        if 400 <= resp.status_code < 500:
            if resp.status_code in (400, 409):
                raise McpToolError(
                    "invalid_input",
                    "the data API rejected the request parameters",
                    hint=(
                        "check the parameter values against"
                        " get_capabilities filterable_fields"
                    ),
                )
            raise McpToolError(
                "upstream_unavailable",
                "the data API rejected the request",
            )
        resp.raise_for_status()
        data = resp.json()
        fetched_at = time.time()
        self._store(key, now, data, fetched_at)
        _note_fetch(fetched_at)
        return data

    def _store(self, key: str, now: float, data: Any, fetched_at: float) -> None:
        """Cache *data* under *key*, dropping expired entries and keeping the bound.

        Args:
            key: The request cache key.
            now: The clock reading taken when the request started.
            data: The parsed response body to cache.
            fetched_at: Wall-clock time the body was obtained from the API.
        """
        self._cache.pop(key, None)
        for stale in [k for k, (expires, *_) in self._cache.items() if expires <= now]:
            del self._cache[stale]
        while len(self._cache) >= self._cache_max_entries:
            del self._cache[next(iter(self._cache))]  # oldest insertion first
        self._cache[key] = (now + self._cache_ttl, data, fetched_at)

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()


def _extract_choices(resp: httpx.Response) -> list[Any]:
    """Pull a ``candidates`` list out of a 300 response body (best-effort).

    Args:
        resp: The 300 :class:`httpx.Response`.

    Returns:
        The candidate list when present, otherwise an empty list.
    """
    try:
        body: Any = resp.json()
    except (json.JSONDecodeError, ValueError):
        return []
    if isinstance(body, dict):
        meta = body.get("meta")
        if isinstance(meta, dict) and isinstance(meta.get("candidates"), list):
            return list(meta["candidates"])
        if isinstance(body.get("candidates"), list):
            return list(body["candidates"])
    return []
