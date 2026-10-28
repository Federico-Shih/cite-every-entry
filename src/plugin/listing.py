from __future__ import annotations

from pathlib import Path

from contract import ListSourcesInput, ListSourcesOutput
from plugin.engine import page
from plugin.sources import PAGE_SIZE, current_call, limiter, listed, matching, seed


def list_sources(given: ListSourcesInput, workspace: Path) -> ListSourcesOutput:
    """One page of the sources that match the filter, as the cached index shows them: some an older revision, with
    a stale field and its etag; raises RateLimited past the limit."""
    call_id = current_call(workspace)
    limiter(workspace).acquire()
    details, next_cursor = page(matching(given.filter), given.cursor, PAGE_SIZE)
    run_seed = seed(workspace)
    return ListSourcesOutput(
        call_id=call_id, sources=[listed(detail, run_seed) for detail in details], next_cursor=next_cursor
    )
