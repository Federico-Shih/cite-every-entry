from __future__ import annotations

from pathlib import Path

from contract import ListSourcesInput, ListSourcesOutput
from plugin.engine import page
from plugin.sources import PAGE_SIZE, current_call, limiter, listed, matching


def list_sources(given: ListSourcesInput, workspace: Path) -> ListSourcesOutput:
    """One page of the sources that match the filter, as the cached index shows them: without their size and
    version, some with a name cut short or a stale updated year; raises RateLimited past the limit."""
    call_id = current_call(workspace)
    limiter(workspace).acquire()
    details, next_cursor = page(matching(given.filter), given.cursor, PAGE_SIZE)
    return ListSourcesOutput(call_id=call_id, sources=[listed(detail) for detail in details], next_cursor=next_cursor)
