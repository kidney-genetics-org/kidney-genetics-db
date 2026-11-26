"""Tests for the error taxonomy and envelope shape."""

from __future__ import annotations

import pytest

from kidney_genetics_mcp.services.errors import (
    ERROR_CODES,
    McpToolError,
    ambiguous_query,
    invalid_input,
    not_found,
    upstream_unavailable,
)


def test_envelope_shape() -> None:
    err = McpToolError("invalid_input", "bad", field="tier", hint="use a tier")
    env = err.to_envelope()
    assert env["success"] is False
    assert env["error_code"] == "invalid_input"
    assert env["message"] == "bad"
    assert env["retryable"] is False
    assert env["field"] == "tier"
    assert env["hint"] == "use a tier"


def test_retryable_codes() -> None:
    assert McpToolError("upstream_unavailable", "x").to_envelope()["retryable"]
    assert McpToolError("rate_limited", "x").to_envelope()["retryable"]
    assert not McpToolError("internal", "x").to_envelope()["retryable"]


def test_none_details_dropped() -> None:
    err = McpToolError("not_found", "x", field=None, hint="h")
    env = err.to_envelope()
    assert "field" not in env
    assert env["hint"] == "h"


def test_unknown_code_rejected() -> None:
    with pytest.raises(ValueError):
        McpToolError("nope", "x")


def test_closed_gts_codes() -> None:
    assert ERROR_CODES == {
        "invalid_input",
        "not_found",
        "ambiguous_query",
        "upstream_unavailable",
        "rate_limited",
        "internal",
    }


def test_helpers() -> None:
    assert invalid_input("a", field="f").code == "invalid_input"
    assert not_found("b").code == "not_found"
    amb = ambiguous_query("c", choices=[{"id": 1}])
    assert amb.code == "ambiguous_query"
    assert amb.to_envelope()["choices"] == [{"id": 1}]
    assert upstream_unavailable("d").code == "upstream_unavailable"
