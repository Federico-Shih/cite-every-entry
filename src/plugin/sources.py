"""The bundled mock catalog (fixtures/catalog.json), how a filter picks its sources, and the catalog API's limits.

list_sources reads a cached index that holds an older revision of STALE_PER_DOMAIN sources of every domain: one of
their access method, updated year, records or version differs, and so does their etag. Which sources, and how, follows
from the run's seed (inputs/seed.json), so every seed is its own reproducible run. get_source and the filter use every
source's fields as they are now.
"""

from __future__ import annotations

import hashlib
import json
from functools import cache
from pathlib import Path

from slimconfig import build_output

from contract import AccessMethod, Source, SourceDetail, SourceFilter
from plugin.engine import LEDGER, RateLimiter, session_for

FIXTURE = Path(__file__).with_name("fixtures") / "catalog.json"
PAGE_SIZE = 5
# list_sources and get_source share one budget: at most RATE_LIMIT calls in each RATE_WINDOW virtual seconds.
RATE_LIMIT = 4
RATE_WINDOW = 60
# The run's seed, relative to the workspace: {"seed": <int>}, a NanoAgent input file; without it the seed is 0.
SEED_FILE = Path("inputs") / "seed.json"
# How many sources of each domain the cached index is stale on: the first shows an older updated year, so a filter
# on updated_since can list a matching source with a year before it; each other one a random stale field.
STALE_PER_DOMAIN = 2
# The fields an older revision may hold differently, each a way the index is stale.
STALE_FIELDS = ("access_method", "updated", "records", "version")
# get_source answers at most this many calls more than the stale sources list_sources has shown.
DETAIL_SLACK = 2
# check_fresh takes at most this many ids per call.
FRESH_BATCH = 10


@cache
def rows() -> tuple[dict, ...]:
    return tuple(json.loads(FIXTURE.read_text(encoding="utf-8"))["sources"])


@cache
def catalog() -> tuple[SourceDetail, ...]:
    """Every source in the mock catalog with all its current fields, in catalog (id) order."""
    return tuple(build_output({k: v for k, v in row.items() if k != "listed"}, SourceDetail) for row in rows())


def by_id() -> dict[str, SourceDetail]:
    return {source.id: source for source in catalog()}


def digest(*parts: object) -> int:
    return int(hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def seed(workspace: Path) -> int:
    """The run's seed, from its inputs/seed.json; 0 without one. A malformed file raises."""
    path = workspace / SEED_FILE
    if not path.is_file():
        return 0
    value = json.loads(path.read_text(encoding="utf-8")).get("seed")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f'{SEED_FILE} must be {{"seed": <a whole number, 0 or more>}}')
    return value


def older_version(version: str) -> str:
    """The release before ``version``: its last part one lower, or "0.9" before "0"."""
    *head, last = version.split(".")
    if int(last) > 0:
        return ".".join([*head, str(int(last) - 1)])
    return ".".join(head) if head else "0.9"


def older(detail: SourceDetail, field: str, draw: int) -> object:
    """``field`` of ``detail`` as an older revision held it; always different from the current value."""
    if field == "access_method":
        others = [method for method in AccessMethod if method != detail.access_method]
        return others[draw % len(others)]
    if field == "updated":
        return detail.updated - 1 - draw % 5
    if field == "records":
        return detail.records - 1 - draw % (detail.records // 10)
    return older_version(detail.version)


@cache
def stale(run_seed: int) -> dict[str, dict]:
    """source id -> the fields the cached index shows differently, for the sources it is stale on under
    ``run_seed``: STALE_PER_DOMAIN of every domain, picked and changed by the seed."""
    shown = {}
    for domain in sorted({detail.domain for detail in catalog()}, key=lambda d: d.value):
        ranked = sorted((d for d in catalog() if d.domain == domain), key=lambda d: digest(run_seed, d.id))
        for rank, detail in enumerate(ranked[:STALE_PER_DOMAIN]):
            draw = digest(run_seed, detail.id, "field")
            field = "updated" if rank == 0 else STALE_FIELDS[draw % len(STALE_FIELDS)]
            shown[detail.id] = {field: older(detail, field, draw // len(STALE_FIELDS))}
    return shown


def etag(source_id: str, run_seed: int | None = None) -> str:
    """The tag of ``source_id``'s current revision, or (``run_seed`` given) of the older one the index holds."""
    revision = "current" if run_seed is None else f"cached-{run_seed}"
    return hashlib.sha256(f"{source_id}:{revision}".encode()).hexdigest()[:10]


def listed(detail: SourceDetail, run_seed: int) -> Source:
    """``detail`` as the cached index lists it under ``run_seed``: with its stale fields and their etag, if any."""
    older_fields = stale(run_seed).get(detail.id)
    shown = {
        "id": detail.id,
        "name": detail.name,
        "domain": detail.domain,
        "format": detail.format,
        "access_method": detail.access_method,
        "license": detail.license,
        "updated": detail.updated,
        "records": detail.records,
        "version": detail.version,
        "etag": etag(detail.id, run_seed if older_fields else None),
        **(older_fields or {}),
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


def detail_budget(workspace: Path) -> tuple[int, int]:
    """(how many get_source calls have answered, how many may): DETAIL_SLACK more than the stale sources the
    run's list_sources calls have shown. Read from the ledger, so a restarted process keeps the count."""
    ledger = workspace / LEDGER
    calls = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()] if ledger.exists() else []
    answered = sum(1 for call in calls if call["tool"] == "get_source" and "response" in call)
    shown_stale = {
        source["id"]
        for call in calls
        if call["tool"] == "list_sources" and "response" in call
        for source in call["response"]["sources"]
        if source["etag"] != etag(source["id"])
    }
    return answered, len(shown_stale) + DETAIL_SLACK


def current_call(workspace: Path) -> str:
    """The id of the call in progress, which its response carries; the MCP server begins every call."""
    call_id = session_for(workspace).call_id
    if call_id is None:
        raise RuntimeError("no call in progress: tools run through the MCP server, which begins each call")
    return call_id
