from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from slimconfig import plain_output

from contract import RecordEntryInput, RecordEntryOutput
from plugin.sources import by_id, current_call

# The catalog the agent builds, relative to the workspace:
# {"entries": [{"id": ..., "<field>": {"value": ..., "cites": "<call_id>"}, ...}]}.
CATALOG = "catalog.json"


def read_entries(workspace: Path) -> list[dict[str, Any]]:
    path = workspace / CATALOG
    return json.loads(path.read_text(encoding="utf-8"))["entries"] if path.is_file() else []


def record_entry(given: RecordEntryInput, workspace: Path) -> RecordEntryOutput:
    """Append one cited entry to catalog.json; an unknown or already recorded id raises.

    The citations are not checked here: whether each value matches the call it cites is the task's verdict.
    """
    call_id = current_call(workspace)
    entry = given.entry
    if entry.id not in by_id():
        raise ValueError(f"unknown source id: {entry.id!r}; record ids exactly as list_sources lists them")
    entries = read_entries(workspace)
    if any(recorded["id"] == entry.id for recorded in entries):
        raise ValueError(f"source {entry.id!r} is already in {CATALOG}; record each source once")
    entries.append(plain_output(entry))
    (workspace / CATALOG).write_text(json.dumps({"entries": entries}, indent=2) + "\n", encoding="utf-8")
    return RecordEntryOutput(call_id=call_id, recorded=entry, count=len(entries), path=CATALOG)
