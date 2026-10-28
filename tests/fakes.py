"""A scripted agent that works the cite-every-entry task through the real tools and the server's call path, as an
agent would, so every call lands in the ledger."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from slimconfig import build_output, plain_output

from contract import CatalogInput, CatalogOutput
from plugin.__main__ import run_call
from plugin.engine import RateLimited

LISTED = ("name", "access_method", "updated")  # the fields list_sources returns too


def call(workspace: Path, tool: str, arguments: dict[str, Any], *, give_up: bool = False) -> dict[str, Any] | None:
    """Call ``tool`` as the server would; on a rate limit wait it out and repeat (or give up: None)."""
    while True:
        try:
            return run_call(tool, arguments, workspace)
        except RateLimited as limited:
            if give_up:
                return None
            run_call("wait", {"seconds": limited.retry_after}, workspace)


def entry(
    source_id: str,
    detail: dict[str, Any],
    detail_call: str,
    listing_call: str | None = None,
    shown: dict[str, Any] | None = None,
) -> dict:
    """A cited entry: every field from the get_source call, or the listed ones cited to the list_sources call
    (``listing_call``), with get_source's value, or with the listing's own value when ``shown`` is that listing."""
    cited = {"id": source_id}
    for field in ("name", "access_method", "updated", "records", "version"):
        from_listing = listing_call is not None and field in LISTED
        value = (shown or detail)[field] if from_listing else detail[field]
        cited[field] = {"value": value, "cites": listing_call if from_listing else detail_call}
    return cited


def run_agent(
    workspace: Path,
    task: CatalogInput,
    *,
    pages: int | None = None,
    give_up_on_rate_limit: bool = False,
    cite_listing: bool = False,
    trust_listing: bool = False,
    refilter_on_listing: bool = False,
) -> CatalogOutput:
    """Page through the catalog, describe every listed source and record it with its citations.

    Each switch makes one mistake: ``pages`` stops after that many pages; ``give_up_on_rate_limit`` stops at the
    first rate limit; ``cite_listing`` cites the listed fields to the list_sources call, with get_source's values;
    ``trust_listing`` takes the listed fields' values from the listing too, and cites it; ``refilter_on_listing``
    drops a listed source whose listed updated year is before the filter's updated_since."""
    cursor: str | None = None
    recorded = 0
    seen = 0
    while True:
        listed = call(workspace, "list_sources", {"filter": plain_output(task.filter), "cursor": cursor},
                      give_up=give_up_on_rate_limit)
        if listed is None:
            break
        for source in listed["sources"]:
            if refilter_on_listing and source["updated"] < task.filter.updated_since:
                continue
            described = call(workspace, "get_source", {"id": source["id"]}, give_up=give_up_on_rate_limit)
            if described is None:
                break
            cited = entry(
                source["id"],
                described["source"],
                described["call_id"],
                listed["call_id"] if cite_listing or trust_listing else None,
                source if trust_listing else None,
            )
            run_call("record_entry", {"entry": cited}, workspace)
            recorded += 1
        else:
            seen += 1
            cursor = listed["next_cursor"]
            if cursor is not None and seen != pages:
                continue
        break
    # What the sandbox hands the verifier: the output rebuilt from its JSON.
    return build_output(plain_output(CatalogOutput(total=recorded)), CatalogOutput)
