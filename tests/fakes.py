"""A scripted agent that works the cite-every-entry task through the real tools and the server's call path, as an
agent would, so every call lands in the ledger."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from slimconfig import build_output, plain_output

from contract import CatalogInput, CatalogOutput
from plugin.__main__ import run_call
from plugin.engine import RateLimited
from plugin.lookup import DetailQuotaExhausted

FIELDS = ("access_method", "updated", "records", "version")


def call(workspace: Path, tool: str, arguments: dict[str, Any], *, give_up: bool = False) -> dict[str, Any] | None:
    """Call ``tool`` as the server would; on a rate limit wait it out and repeat (or give up: None)."""
    while True:
        try:
            return run_call(tool, arguments, workspace)
        except RateLimited as limited:
            if give_up:
                return None
            run_call("wait", {"seconds": limited.retry_after}, workspace)


def entry(source_id: str, shown: dict[str, Any], cites: str) -> dict:
    """An entry whose every field is ``shown``'s value, cited to the call ``cites``."""
    return {"id": source_id, **{field: {"value": shown[field], "cites": cites} for field in FIELDS}}


def run_agent(
    workspace: Path,
    task: CatalogInput,
    *,
    pages: int | None = None,
    give_up_on_rate_limit: bool = False,
    describe_all: bool = False,
    trust_listing: bool = False,
    cite_listing: bool = False,
    refilter_on_listing: bool = False,
) -> CatalogOutput:
    """Page through the catalog, check each page's etags, describe the stale sources and record every source: a
    stale one cited to its get_source call, a fresh one to its listing.

    Each switch makes one mistake: ``pages`` stops after that many pages; ``give_up_on_rate_limit`` stops at the
    first rate limit; ``describe_all`` describes every source, skipping those get_source no longer answers;
    ``trust_listing`` never checks the etags and cites every listing; ``cite_listing`` cites a stale source's
    current values to its listing; ``refilter_on_listing`` drops a listed source whose listed fields fail the
    filter."""
    cursor: str | None = None
    recorded = 0
    seen = 0
    wanted = task.filter
    while True:
        listed = call(workspace, "list_sources", {"filter": plain_output(wanted), "cursor": cursor},
                      give_up=give_up_on_rate_limit)
        if listed is None:
            break
        sources = listed["sources"]
        if refilter_on_listing:
            sources = [
                s for s in sources
                if s["updated"] >= wanted.updated_since
                and (not wanted.access_methods or s["access_method"] in {m.value for m in wanted.access_methods})
            ]
        stale = {s["id"] for s in sources} if describe_all else set()
        if sources and not (describe_all or trust_listing):
            fresh = call(workspace, "check_fresh", {"ids": [s["id"] for s in sources]}, give_up=give_up_on_rate_limit)
            if fresh is None:
                break
            current = {f["id"]: f["etag"] for f in fresh["etags"]}
            stale = {s["id"] for s in sources if s["etag"] != current[s["id"]]}
        stopped = False
        for source in sources:
            cited = entry(source["id"], source, listed["call_id"])
            if source["id"] in stale:
                try:
                    described = call(workspace, "get_source", {"id": source["id"]}, give_up=give_up_on_rate_limit)
                except DetailQuotaExhausted:
                    continue
                if described is None:
                    stopped = True
                    break
                cites = listed["call_id"] if cite_listing else described["call_id"]
                cited = entry(source["id"], described["source"], cites)
            run_call("record_entry", {"entry": cited}, workspace)
            recorded += 1
        seen += 1
        cursor = listed["next_cursor"]
        if stopped or cursor is None or seen == pages:
            break
    # What the sandbox hands the verifier: the output rebuilt from its JSON.
    return build_output(plain_output(CatalogOutput(total=recorded)), CatalogOutput)
