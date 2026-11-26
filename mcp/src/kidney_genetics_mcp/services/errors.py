"""Typed tool-result error taxonomy for the MCP server."""

from __future__ import annotations

from typing import Any

#: The closed GTS error vocabulary (GeneFoundry response envelope v1.2).
ERROR_CODES = {
    "invalid_input",
    "not_found",
    "ambiguous_query",
    "upstream_unavailable",
    "rate_limited",
    "internal",
}

#: Codes a client may retry unchanged.
RETRYABLE_CODES = frozenset({"upstream_unavailable", "rate_limited"})


class McpToolError(Exception):
    """A recoverable tool error surfaced as an ``isError`` tool result."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        """Initialize with a known error code, message, and optional details.

        Args:
            code: One of the known :data:`ERROR_CODES` values.
            message: Human-readable error description (never leaks internal
                routes/hosts).
            **details: Optional extra fields merged into the error envelope
                (e.g. ``field``/``allowed``/``hint`` for ``invalid_input``,
                ``choices`` for ``ambiguous_query``). ``None`` values are
                dropped.

        Raises:
            ValueError: If *code* is not in :data:`ERROR_CODES`.
        """
        if code not in ERROR_CODES:
            raise ValueError(f"unknown error code: {code}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = {k: v for k, v in details.items() if v is not None}

    def to_envelope(self) -> dict[str, Any]:
        """Return the GTS error frame embedded in the tool result.

        ``_meta`` (request id, timing, source) and the clinical-use flag are
        added by the envelope middleware.

        Returns:
            ``{"success": False, "error_code", "message", "retryable", ...}``.
        """
        return {
            "success": False,
            "error_code": self.code,
            "message": self.message,
            "retryable": self.code in RETRYABLE_CODES,
            **self.details,
        }


def invalid_input(message: str, **details: Any) -> McpToolError:
    """Build an ``invalid_input`` error (caller-correctable parameter problem).

    Args:
        message: Human-readable description of what was wrong.
        **details: Optional ``field``/``allowed``/``hint`` for one-shot
            self-correction.

    Returns:
        A populated :class:`McpToolError` with code ``invalid_input``.
    """
    return McpToolError("invalid_input", message, **details)


def not_found(message: str, **details: Any) -> McpToolError:
    """Build a ``not_found`` error.

    Args:
        message: Human-readable description (domain-framed, never a route).
        **details: Optional extra fields (e.g. ``hint``).

    Returns:
        A populated :class:`McpToolError` with code ``not_found``.
    """
    return McpToolError("not_found", message, **details)


def ambiguous_query(message: str, choices: list[Any]) -> McpToolError:
    """Build an ``ambiguous_query`` error carrying candidate ``choices``.

    Args:
        message: Human-readable description of the ambiguity.
        choices: The candidate records the caller should disambiguate between.

    Returns:
        A populated :class:`McpToolError` with code ``ambiguous_query`` and a
        ``choices`` detail field.
    """
    return McpToolError("ambiguous_query", message, choices=choices)


def upstream_unavailable(message: str, **details: Any) -> McpToolError:
    """Build a ``upstream_unavailable`` error (transient upstream problem).

    Args:
        message: Human-readable description (domain-framed, never a route).
        **details: Optional extra fields.

    Returns:
        A populated :class:`McpToolError` with code ``upstream_unavailable``.
    """
    return McpToolError("upstream_unavailable", message, **details)
