"""Reads the call ledger the MCP server writes (src/plugin/engine.py). Shared by every plugin: edit only the
canonical copy in catalog-every-source, then run eval/plugins/sync_engine.py."""

import json
from pathlib import Path

LEDGER = Path(".ledger") / "calls.jsonl"


def read_calls(workspace):
    """Every recorded call, in order, as dicts; [] when no call was made. Raises ValueError on a broken line."""
    path = Path(workspace) / LEDGER
    if not path.is_file():
        return []
    calls = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            call = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"ledger line {number} is not JSON") from error
        if not isinstance(call, dict) or "call_id" not in call or "tool" not in call:
            raise ValueError(f"ledger line {number} is not a call")
        calls.append(call)
    return calls


def calls_by_id(workspace):
    return {call["call_id"]: call for call in read_calls(workspace)}
