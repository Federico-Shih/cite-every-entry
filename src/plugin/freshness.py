from __future__ import annotations

from pathlib import Path

from contract import CheckFreshInput, CheckFreshOutput, Freshness
from plugin.sources import FRESH_BATCH, by_id, current_call, etag, limiter


def check_fresh(given: CheckFreshInput, workspace: Path) -> CheckFreshOutput:
    """Each asked source's current etag, so a listing that shows another one is known to be stale; raises on no
    ids, more than FRESH_BATCH, an unknown or repeated id, or past the rate limit."""
    call_id = current_call(workspace)
    if not 1 <= len(given.ids) <= FRESH_BATCH:
        raise ValueError(f"ask for 1 to {FRESH_BATCH} ids, not {len(given.ids)}")
    unknown = [source_id for source_id in given.ids if source_id not in by_id()]
    if unknown:
        raise ValueError(f"unknown source ids: {unknown}; pass ids exactly as list_sources lists them")
    if len(set(given.ids)) != len(given.ids):
        raise ValueError("ask for each id once")
    limiter(workspace).acquire()
    return CheckFreshOutput(call_id=call_id, etags=[Freshness(id=i, etag=etag(i)) for i in given.ids])
