from __future__ import annotations

from pathlib import Path

from contract import GetSourceInput, GetSourceOutput
from plugin.sources import by_id, current_call, limiter


def get_source(given: GetSourceInput, workspace: Path) -> GetSourceOutput:
    """Every field of one source; an unknown id raises, and so does a call past the rate limit."""
    call_id = current_call(workspace)
    limiter(workspace).acquire()
    source = by_id().get(given.id)
    if source is None:
        raise ValueError(f"unknown source id: {given.id!r}; pass an id exactly as list_sources lists it")
    return GetSourceOutput(call_id=call_id, source=source)
