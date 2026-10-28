"""The bundled mock catalog (fixtures/catalog.json), how a filter picks its sources, and the catalog API's limits.

list_sources reads a cached index: for some sources it shows a name cut short or a stale updated year (a row's
"listed" fields). get_source and the filter use every source's fields as they are now.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from slimconfig import build_output

from contract import Source, SourceDetail, SourceFilter
from plugin.engine import RateLimiter, session_for

FIXTURE = Path(__file__).with_name("fixtures") / "catalog.json"
PAGE_SIZE = 5
# list_sources and get_source share one budget: at most RATE_LIMIT calls in each RATE_WINDOW virtual seconds.
RATE_LIMIT = 4
RATE_WINDOW = 60


@cache
def rows() -> tuple[dict, ...]:
    return tuple(json.loads(FIXTURE.read_text(encoding="utf-8"))["sources"])


@cache
def catalog() -> tuple[SourceDetail, ...]:
    """Every source in the mock catalog with all its current fields, in catalog (id) order."""
    return tuple(build_output({k: v for k, v in row.items() if k != "listed"}, SourceDetail) for row in rows())


def by_id() -> dict[str, SourceDetail]:
    return {source.id: source for source in catalog()}


@cache
def stale() -> dict[str, dict]:
    """source id -> the fields the cached index shows differently, for the sources it is stale on."""
    return {row["id"]: row["listed"] for row in rows() if "listed" in row}


def listed(detail: SourceDetail) -> Source:
    """``detail`` as the cached index lists it: without size and version, and with its stale fields."""
    shown = {
        "id": detail.id,
        "name": detail.name,
        "domain": detail.domain,
        "format": detail.format,
        "access_method": detail.access_method,
        "license": detail.license,
        "updated": detail.updated,
        **stale().get(detail.id, {}),
    }
    return Source(**shown)


def matches(source: SourceDetail, wanted: SourceFilter) -> bool:
    return (
        (not wanted.domains or source.domain in wanted.domains)
        and (not wanted.formats or source.format in wanted.formats)
        and (not wanted.access_methods or source.access_method in wanted.access_methods)
        and (not wanted.licenses or source.license in wanted.licenses)
        and source.updated >= wanted.updated_since
    )


def matching(wanted: SourceFilter) -> list[SourceDetail]:
    return [source for source in catalog() if matches(source, wanted)]


def limiter(workspace: Path) -> RateLimiter:
    return session_for(workspace).rate_limit(RATE_LIMIT, RATE_WINDOW)


def current_call(workspace: Path) -> str:
    """The id of the call in progress, which its response carries; the MCP server begins every call."""
    call_id = session_for(workspace).call_id
    if call_id is None:
        raise RuntimeError("no call in progress: tools run through the MCP server, which begins each call")
    return call_id
