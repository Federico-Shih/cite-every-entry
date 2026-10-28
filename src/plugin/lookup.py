from __future__ import annotations

from pathlib import Path

from contract import GetSourceInput, GetSourceOutput
from plugin.sources import by_id, current_call, detail_budget, limiter


class DetailQuotaExhausted(RuntimeError):
    pass


def get_source(given: GetSourceInput, workspace: Path) -> GetSourceOutput:
    """Every field of one source as it is now; an unknown id raises, and so does a call past the rate limit or past
    the run's budget of answered calls (sources.detail_budget)."""
    call_id = current_call(workspace)
    answered, allowed = detail_budget(workspace)
    if answered >= allowed:
        raise DetailQuotaExhausted(
            f"get_source has answered {answered} calls, all this run allows so far: {allowed}, two more than the "
            "stale sources list_sources has shown. Use check_fresh to find which listed sources are stale"
        )
    limiter(workspace).acquire()
    source = by_id().get(given.id)
    if source is None:
        raise ValueError(f"unknown source id: {given.id!r}; pass an id exactly as list_sources lists it")
    return GetSourceOutput(call_id=call_id, source=source)
