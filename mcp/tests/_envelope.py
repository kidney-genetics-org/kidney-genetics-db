"""Test helper: read a tool's GTS envelope."""

from __future__ import annotations

from typing import Any


def unwrap(envelope: dict[str, Any]) -> dict[str, Any]:
    """Return the payload of a success envelope, or the error frame itself."""
    if envelope.get("success") is True:
        assert set(envelope) >= {"result", "_meta"}
        result: dict[str, Any] = envelope["result"]
        return result
    assert envelope.get("success") is False
    return envelope
