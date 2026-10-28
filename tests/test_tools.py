from __future__ import annotations

import json
from pathlib import Path

import pytest
from fakes import call, entry

from contract import AccessMethod, GetSourceInput, Tool
from plugin import get_source
from plugin.__main__ import IMPLEMENTATIONS, run_call
from plugin.engine import LEDGER, RateLimited
from plugin.lookup import DetailQuotaExhausted
from plugin.recording import CATALOG
from plugin.sources import (
    DETAIL_SLACK,
    FRESH_BATCH,
    PAGE_SIZE,
    RATE_LIMIT,
    RATE_WINDOW,
    SEED_FILE,
    STALE_PER_DOMAIN,
    catalog,
    stale,
)

EVERY = {"domains": [], "formats": [], "access_methods": [], "licenses": [], "updated_since": 0}


def listing(cursor: str | None = None, **wanted) -> dict:
    return {"filter": {**EVERY, **wanted}, "cursor": cursor}


def seeded(workspace: Path, seed: int) -> Path:
    """``workspace`` with the run seed NanoAgent stages as an input file."""
    (workspace / SEED_FILE).parent.mkdir(parents=True, exist_ok=True)
    (workspace / SEED_FILE).write_text(json.dumps({"seed": seed}))
    return workspace


def ledger(workspace: Path) -> list[dict]:
    return [json.loads(line) for line in (workspace / LEDGER).read_text().splitlines()]


def test_every_tool_is_implemented() -> None:
    assert set(IMPLEMENTATIONS) == set(Tool)


def test_the_fixture_holds_48_unique_sources_with_sizes_and_versions() -> None:
    ids = [source.id for source in catalog()]
    assert len(ids) == 48 and ids == sorted(set(ids)) and ids[0] == "src-001"
    assert {source.access_method for source in catalog()} == set(AccessMethod)
    assert all(source.records > 0 and source.version for source in catalog())
    # Some versions read as numbers, so citing one exactly means keeping it a string.
    assert any(source.version.isdigit() for source in catalog())


def test_every_response_carries_its_own_call_id_as_the_ledger_records_it(tmp_path: Path) -> None:
    listed = run_call("list_sources", listing(domains=["health"]), tmp_path)
    described = run_call("get_source", {"id": "src-006"}, tmp_path)
    waited = run_call("wait", {"seconds": 0}, tmp_path)
    assert [listed["call_id"], described["call_id"], waited["call_id"]] == ["call-0001", "call-0002", "call-0003"]
    calls = ledger(tmp_path)
    assert [c["response"] for c in calls] == [listed, described, waited]
    assert [c["tool"] for c in calls] == ["list_sources", "get_source", "wait"]


def test_a_tool_run_outside_a_call_refuses(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="no call in progress"):
        get_source(GetSourceInput(id="src-006"), tmp_path)


def test_list_sources_pages_through_the_filtered_catalog_with_every_field(tmp_path: Path) -> None:
    first = run_call("list_sources", listing(domains=["health"]), tmp_path)
    assert len(first["sources"]) == PAGE_SIZE and first["next_cursor"] == "cursor-5"
    assert all(source["domain"] == "health" and {"records", "version", "etag"} <= set(source)
               for source in first["sources"])
    last = run_call("list_sources", listing(first["next_cursor"], domains=["health"]), tmp_path)
    assert last["sources"][-1]["id"] == "src-048" and last["next_cursor"] is None


@pytest.mark.parametrize("seed", [0, 7])
def test_the_listing_is_a_cached_index_that_check_fresh_and_get_source_correct(tmp_path: Path, seed: int) -> None:
    workspace = seeded(tmp_path, seed)
    shown = call(workspace, "list_sources", listing(domains=["health"]))["sources"]
    shown += call(workspace, "list_sources", listing("cursor-5", domains=["health"]))["sources"]
    fresh = call(workspace, "check_fresh", {"ids": [s["id"] for s in shown]})["etags"]
    current = {f["id"]: f["etag"] for f in fresh}
    flagged = {s["id"] for s in shown if s["etag"] != current[s["id"]]}
    # STALE_PER_DOMAIN of the domain's sources, exactly those whose etag check_fresh contradicts.
    assert flagged == {i for i in stale(seed) if i in current} and len(flagged) == STALE_PER_DOMAIN
    by_id = {s["id"]: s for s in shown}
    now = {i: call(workspace, "get_source", {"id": i})["source"] for i in flagged}
    for source_id in flagged:
        differs = [f for f in ("access_method", "updated", "records", "version") if by_id[source_id][f] != now[source_id][f]]
        assert differs == list(stale(seed)[source_id])
    # The first stale source of every domain shows an older year: a listing can look too old for the filter.
    assert any(by_id[i]["updated"] < now[i]["updated"] for i in flagged)


def test_the_seed_picks_the_stale_sources(tmp_path: Path) -> None:
    assert stale(0) != stale(7)
    # Without a seed file the seed is 0.
    unseeded = run_call("list_sources", listing(), tmp_path)["sources"]
    assert unseeded == run_call("list_sources", listing(), seeded(tmp_path / "zero", 0))["sources"]
    (seeded(tmp_path, 0) / SEED_FILE).write_text(json.dumps({"seed": "seven"}))
    with pytest.raises(ValueError, match="seed"):
        run_call("list_sources", listing(), tmp_path)


def test_get_source_answers_two_more_calls_than_the_stale_sources_shown(tmp_path: Path) -> None:
    shown = call(tmp_path, "list_sources", listing(domains=["health"]))["sources"]
    stale_shown = sum(s["id"] in stale(0) for s in shown)
    allowed = stale_shown + DETAIL_SLACK
    for source in shown[:allowed]:
        call(tmp_path, "get_source", {"id": source["id"]})
    with pytest.raises(DetailQuotaExhausted, match="check_fresh"):
        call(tmp_path, "get_source", {"id": shown[-1]["id"]})
    assert "error" in ledger(tmp_path)[-1]
    # Listing more stale sources raises the budget; a refused call does not spend it.
    more = call(tmp_path, "list_sources", listing("cursor-5", domains=["health"]))["sources"]
    assert sum(s["id"] in stale(0) for s in more) == STALE_PER_DOMAIN - stale_shown
    if STALE_PER_DOMAIN > stale_shown:
        assert call(tmp_path, "get_source", {"id": more[0]["id"]}) is not None


def test_check_fresh_takes_1_to_10_known_ids_once_each(tmp_path: Path) -> None:
    ids = [source.id for source in catalog()]
    assert len(run_call("check_fresh", {"ids": ids[:FRESH_BATCH]}, tmp_path)["etags"]) == FRESH_BATCH
    for asked, problem in ([], "1 to"), (ids[: FRESH_BATCH + 1], "1 to"), (["src-999"], "unknown"), (ids[:1] * 2, "once"):
        with pytest.raises(ValueError, match=problem):
            run_call("check_fresh", {"ids": asked}, tmp_path)


def test_get_source_describes_one_source_and_refuses_an_unknown_id(tmp_path: Path) -> None:
    described = run_call("get_source", {"id": "src-006"}, tmp_path)["source"]
    assert described["id"] == "src-006" and isinstance(described["records"], int)
    assert isinstance(described["version"], str)
    with pytest.raises(ValueError, match="unknown source id"):
        run_call("get_source", {"id": "src-999"}, tmp_path)
    assert "error" in ledger(tmp_path)[-1]


def test_listing_and_describing_share_one_rate_limit_and_failed_calls_are_recorded(tmp_path: Path) -> None:
    for _ in range(RATE_LIMIT - 1):
        run_call("list_sources", listing(), tmp_path)
    run_call("get_source", {"id": "src-001"}, tmp_path)
    with pytest.raises(RateLimited) as limited:
        run_call("get_source", {"id": "src-002"}, tmp_path)
    assert limited.value.retry_after == RATE_WINDOW
    failed = ledger(tmp_path)[-1]
    assert failed["call_id"] == f"call-{RATE_LIMIT + 1:04d}" and "rate limited" in failed["error"]
    assert "response" not in failed
    assert run_call("wait", {"seconds": RATE_WINDOW}, tmp_path)["now"] == RATE_WINDOW
    assert run_call("get_source", {"id": "src-002"}, tmp_path)["call_id"] == f"call-{RATE_LIMIT + 3:04d}"


def test_wait_refuses_negative_or_huge_waits(tmp_path: Path) -> None:
    for seconds in (-1, 3601):
        with pytest.raises(ValueError, match="seconds"):
            run_call("wait", {"seconds": seconds}, tmp_path)


def test_record_entry_appends_the_cited_entry_to_the_catalog_file(tmp_path: Path) -> None:
    described = call(tmp_path, "get_source", {"id": "src-006"})
    cited = entry("src-006", described["source"], described["call_id"])
    output = run_call("record_entry", {"entry": cited}, tmp_path)
    assert (output["count"], output["path"], output["recorded"]) == (1, CATALOG, cited)
    assert json.loads((tmp_path / CATALOG).read_text()) == {"entries": [cited]}


def test_record_entry_refuses_unknown_and_repeated_ids_but_not_bad_citations(tmp_path: Path) -> None:
    described = call(tmp_path, "get_source", {"id": "src-006"})["source"]
    with pytest.raises(ValueError, match="unknown source id"):
        run_call("record_entry", {"entry": entry("src-999", described, "call-0001")}, tmp_path)
    # The tool never checks a citation: that is the task's verdict.
    run_call("record_entry", {"entry": entry("src-006", described, "call-9999")}, tmp_path)
    with pytest.raises(ValueError, match="already"):
        run_call("record_entry", {"entry": entry("src-006", described, "call-0001")}, tmp_path)


def test_record_entry_takes_values_only_of_their_types(tmp_path: Path) -> None:
    described = call(tmp_path, "get_source", {"id": "src-006"})["source"]
    cited = entry("src-006", described, "call-0001")
    cited["access_method"]["value"] = "ftp"
    with pytest.raises(ValueError, match="not a valid AccessMethod"):
        run_call("record_entry", {"entry": cited}, tmp_path)


def test_catalog_truth_lists_every_match_without_rate_limit(tmp_path: Path) -> None:
    for _ in range(RATE_LIMIT + 2):
        truth = run_call("catalog_truth", {"filter": EVERY}, tmp_path)
    assert truth["total"] == len(truth["ids"]) == 48
    health = run_call("catalog_truth", {"filter": {**EVERY, "domains": ["health"]}}, tmp_path)
    assert health["total"] == 8 and health["ids"][-1] == "src-048"
    assert run_call("catalog_truth", {"filter": {**EVERY, "updated_since": 2030}}, tmp_path)["total"] == 0
