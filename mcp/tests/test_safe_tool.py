"""Tests for the uniform tool-execution wrapper."""

from __future__ import annotations

from typing import Any

import pytest

from kidney_genetics_mcp.services.dataclass import GENE
from kidney_genetics_mcp.services.errors import McpToolError
from kidney_genetics_mcp.services.safe_tool import run_tool


async def test_success_attaches_meta_and_data_class() -> None:
    async def handler() -> dict[str, Any]:
        return {"gene": {"id": 1}}

    envelope = await run_tool(handler, data_class=GENE, response_mode="compact")
    assert envelope["success"] is True
    assert envelope["_meta"] == {"source": "kgdb"}  # no client: no data provenance
    out = envelope["result"]
    assert out["data_class"] == GENE
    assert out["gene"] == {"id": 1}
    assert out["meta"]["response_mode"] == "compact"
    assert isinstance(out["meta"]["effective_chars"], int)
    assert isinstance(out["meta"]["elapsed_ms"], float)
    assert "is_error" not in out


async def test_internal_channels_consumed() -> None:
    async def handler() -> dict[str, Any]:
        return {
            "items": [1, 2],
            "_dropped": {"dropped_records": 1, "reason": "max_response_chars"},
            "_meta": {"applied_sort": "score"},
        }

    out = (await run_tool(handler, data_class=GENE, response_mode="full"))["result"]
    assert "_dropped" not in out
    assert "_meta" not in out
    assert out["meta"]["truncated"] is True
    assert out["meta"]["dropped_summary"]["dropped_records"] == 1
    assert out["meta"]["applied_sort"] == "score"


async def test_mcp_tool_error_caught() -> None:
    async def handler() -> dict[str, Any]:
        raise McpToolError("not_found", "no such gene", hint="resolve first")

    out = await run_tool(handler, data_class=GENE, response_mode="compact")
    assert out["success"] is False
    assert out["error_code"] == "not_found"
    assert out["hint"] == "resolve first"
    assert "meta" not in out


async def test_unexpected_error_mapped_to_internal() -> None:
    async def handler() -> dict[str, Any]:
        raise RuntimeError("boom internal /api/secret")

    out = await run_tool(handler, data_class=GENE, response_mode="compact")
    assert out["success"] is False
    assert out["error_code"] == "internal"
    # internal detail must NOT leak
    assert "secret" not in out["message"]


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
