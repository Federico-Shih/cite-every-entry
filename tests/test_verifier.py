from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from fakes import call, entry, run_agent
from slimconfig import build_output, plain_output

import verifier
from contract import (
    CatalogInput,
    CatalogOutput,
    CatalogTruthOutput,
    CitedEntry,
    GetSourceInput,
    GetSourceOutput,
    ListSourcesInput,
    ListSourcesOutput,
    RecordEntryInput,
    RecordEntryOutput,
    WaitInput,
    WaitOutput,
)
from plugin import catalog_truth
from plugin.__main__ import run_call
from plugin.clock import MAX_WAIT
from plugin.engine import LEDGER, RateLimited
from plugin.recording import CATALOG
from plugin.sources import PAGE_SIZE, RATE_LIMIT, RATE_WINDOW
from verifier import checks
from verifier.citations import INTEGRITY, OUTCOME, WRONG_TOTAL_FACTOR, score_citations

TASK = "cite-every-entry"
EVERY = {"domains": [], "formats": [], "access_methods": [], "licenses": [], "updated_since": 0}
HEALTH = {**EVERY, "domains": ["health"]}  # 8 matches over 2 pages; the last is the catalog's last, src-048
# The README's example: the same 8, all updated in 2019 or later, though the cached index lists src-012 as 2016
# and src-024 as 2017.
EXAMPLE = {**HEALTH, "updated_since": 2019}
NOTHING = {**EVERY, "updated_since": 2030}
# The health fields the cached index shows stale: a name cut short or an old year.
STALE = ["src-006.name", "src-012.updated", "src-024.name", "src-024.updated", "src-042.updated", "src-048.name"]


# The verifier gets contract instances, as NanoAgent's sandbox builds them from JSON.
def task(wanted: dict) -> CatalogInput:
    return build_output({"filter": wanted}, CatalogInput)


def truth(given: CatalogInput, scratch: Path) -> CatalogTruthOutput:
    return build_output(plain_output(catalog_truth(given, scratch)), CatalogTruthOutput)


def total(count: int) -> CatalogOutput:
    return build_output({"total": count}, CatalogOutput)


CHECK_IDS = [check_id for check_id, _constraint in (*INTEGRITY, *OUTCOME)]


def judge(workspace: Path, wanted: dict, output: CatalogOutput) -> dict:
    given = task(wanted)
    return assert_verdict(verifier.verify_task(TASK, given, output, truth(given, workspace / "scratch"), str(workspace)))


def assert_verdict(verdict: dict) -> dict:
    """What the README promises of every task verdict: its named checks, its message and its score."""
    checks_ = verdict["details"]["checks"]
    assert [c["id"] for c in checks_] == CHECK_IDS
    assert all(set(c) == {"id", "constraint", "ok", "expected", "actual", "message"} for c in checks_)
    assert all((c["message"] == "") is (c["ok"] is True) for c in checks_)
    failing = [c for c in checks_ if c["ok"] is False]
    assert verdict["valid"] is (not failing) and all(c["ok"] is True for c in checks_) is verdict["valid"]
    if failing:
        more = f" (+{len(failing) - 1} more)" if len(failing) > 1 else ""
        assert verdict["message"] == f"{failing[0]['id']}: {failing[0]['message']}{more}"
        assert verdict["score"] <= 0.99
    else:
        assert verdict["score"] == 1.0
    if any(c["ok"] is False for c in checks_[: len(INTEGRITY)]):
        assert verdict["score"] == 0.0
    return verdict


def failing(verdict: dict) -> list[str]:
    return [c["id"] for c in verdict["details"]["checks"] if c["ok"] is False]


def named(verdict: dict, check_id: str) -> dict:
    return next(c for c in verdict["details"]["checks"] if c["id"] == check_id)


def entries(workspace: Path) -> list[dict]:
    return json.loads((workspace / CATALOG).read_text())["entries"]


def write_entries(workspace: Path, rows: list) -> None:
    (workspace / CATALOG).write_text(json.dumps({"entries": rows}))


def calls(workspace: Path) -> list[dict]:
    return [json.loads(line) for line in (workspace / LEDGER).read_text().splitlines()]


def described_call(workspace: Path, source_id: str) -> str:
    return next(c["call_id"] for c in calls(workspace) if c["tool"] == "get_source" and c["input"]["id"] == source_id
                and "response" in c)


def edit_field(workspace: Path, index: int, field: str, **changes) -> dict:
    """Change one field of the ``index``-th entry in catalog.json; returns that entry."""
    rows = entries(workspace)
    rows[index][field].update(changes)
    write_entries(workspace, rows)
    return rows[index]


def test_the_verifier_mirrors_the_plugin_constants() -> None:
    assert (checks.PAGE_SIZE, checks.MAX_WAIT, checks.CATALOG) == (PAGE_SIZE, MAX_WAIT, CATALOG)
    assert checks.FIELDS == tuple(f.name for f in dataclasses.fields(CitedEntry) if f.name != "id")


# Correct
def test_approves_a_fully_cited_catalog(tmp_path: Path) -> None:
    verdict = judge(tmp_path, HEALTH, run_agent(tmp_path, task(HEALTH)))
    assert verdict["valid"] is True and verdict["score"] == 1.0
    assert verdict["details"]["true_total"] == 8 and verdict["details"]["bad_fields"] == {}


def test_approves_the_whole_catalog_through_many_rate_limits(tmp_path: Path) -> None:
    verdict = judge(tmp_path, EVERY, run_agent(tmp_path, task(EVERY)))
    assert verdict["valid"] is True and verdict["details"]["true_total"] == 48
    assert any("error" in c for c in calls(tmp_path))


# Wrong
def test_refuses_a_fabricated_call_id(tmp_path: Path) -> None:
    output = run_agent(tmp_path, task(HEALTH))
    edit_field(tmp_path, 0, "records", cites="call-9999")
    verdict = judge(tmp_path, HEALTH, output)
    assert verdict["valid"] is False and "never made" in verdict["details"]["bad_fields"]["src-006.records"]
    assert verdict["details"]["cited"] == round(39 / 40, 4) and verdict["score"] == round(39 / 40, 4)


def test_refuses_a_real_call_id_from_another_source(tmp_path: Path) -> None:
    output = run_agent(tmp_path, task(HEALTH))
    edit_field(tmp_path, 0, "version", cites=described_call(tmp_path, "src-012"))
    verdict = judge(tmp_path, HEALTH, output)
    assert verdict["valid"] is False and "did not return src-006" in verdict["details"]["bad_fields"]["src-006.version"]


@pytest.mark.parametrize("tool", ["record_entry", "wait"])
def test_refuses_a_real_call_id_of_a_tool_that_is_not_a_catalog_read(tmp_path: Path, tool: str) -> None:
    output = run_agent(tmp_path, task(HEALTH))
    run_call("wait", {"seconds": 0}, tmp_path)
    other = next(c["call_id"] for c in calls(tmp_path) if c["tool"] == tool)
    edit_field(tmp_path, 0, "name", cites=other)
    verdict = judge(tmp_path, HEALTH, output)
    assert verdict["valid"] is False and f"a {tool} call" in verdict["details"]["bad_fields"]["src-006.name"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("version", 7, id='version 7 for "7"'),
        pytest.param("updated", "2025", id='updated "2025" for 2025'),
        pytest.param("updated", 2025.0, id="updated 2025.0 for 2025"),
        pytest.param("records", True, id="records true for a number"),
    ],
)
def test_refuses_a_value_of_the_wrong_type(tmp_path: Path, field: str, value) -> None:
    output = run_agent(tmp_path, task(HEALTH))
    assert entries(tmp_path)[0]["version"]["value"] == "7" and entries(tmp_path)[0]["updated"]["value"] == 2025
    edit_field(tmp_path, 0, field, value=value)
    verdict = judge(tmp_path, HEALTH, output)
    assert verdict["valid"] is False and f"src-006.{field}" in verdict["details"]["bad_fields"]


@pytest.mark.parametrize(
    ("field", "value"),
    [("name", "Hospital Bed Capacity "), ("name", "hospital bed capacity"), ("records", 48515), ("access_method", "sql")],
)
def test_refuses_an_edited_value(tmp_path: Path, field: str, value) -> None:
    output = run_agent(tmp_path, task(HEALTH))
    edit_field(tmp_path, 0, field, value=value)
    verdict = judge(tmp_path, HEALTH, output)
    assert verdict["valid"] is False and list(verdict["details"]["bad_fields"]) == [f"src-006.{field}"]


def test_refuses_a_cite_of_a_failed_call(tmp_path: Path) -> None:
    for _ in range(RATE_LIMIT):
        run_call("list_sources", {"filter": HEALTH, "cursor": None}, tmp_path)
    with pytest.raises(RateLimited):
        run_call("get_source", {"id": "src-006"}, tmp_path)
    failed = calls(tmp_path)[-1]["call_id"]
    output = run_agent(tmp_path, task(HEALTH))
    assert judge(tmp_path, HEALTH, output)["valid"] is True
    edit_field(tmp_path, 0, "records", cites=failed)
    verdict = judge(tmp_path, HEALTH, output)
    assert verdict["valid"] is False and "failed" in verdict["details"]["bad_fields"]["src-006.records"]


def test_refuses_an_extra_source_even_when_cited_rightly(tmp_path: Path) -> None:
    run_agent(tmp_path, task(HEALTH))
    described = call(tmp_path, "get_source", {"id": "src-001"})
    run_call("record_entry", {"entry": entry("src-001", described["source"], described["call_id"])}, tmp_path)
    verdict = judge(tmp_path, HEALTH, total(9))
    assert verdict["valid"] is False and verdict["details"]["extra"] == ["src-001"]
    assert verdict["details"]["cited"] == 1.0 and 0 < verdict["score"] < 1
    assert failing(verdict) == ["no-extra", "total-exact"] and verdict["message"].endswith(" (+1 more)")
    assert named(verdict, "no-extra")["actual"] == ["src-001"]
    assert (named(verdict, "total-exact")["expected"], named(verdict, "total-exact")["actual"]) == (8, 9)


def test_refuses_a_repeated_entry(tmp_path: Path) -> None:
    output = run_agent(tmp_path, task(HEALTH))
    rows = entries(tmp_path)
    write_entries(tmp_path, [*rows, rows[0]])
    verdict = judge(tmp_path, HEALTH, output)
    assert verdict["valid"] is False and verdict["details"]["repeated"] == ["src-006"]


def test_refuses_a_wrong_total_even_with_a_fully_cited_catalog(tmp_path: Path) -> None:
    run_agent(tmp_path, task(HEALTH))
    verdict = judge(tmp_path, HEALTH, total(7))
    assert verdict["valid"] is False and verdict["score"] == WRONG_TOTAL_FACTOR
    assert verdict["message"] == "total-exact: total 7 is not the true count 8"


# Missing
def test_refuses_a_missing_catalog_file(tmp_path: Path) -> None:
    verdict = judge(tmp_path, HEALTH, total(8))
    assert verdict["valid"] is False and len(verdict["details"]["missing"]) == 8 and verdict["score"] == 0.0


@pytest.mark.parametrize(
    "cited",
    [
        pytest.param("Hospital Bed Capacity", id="a bare value"),
        pytest.param({"value": "Hospital Bed Capacity"}, id="no cites"),
        pytest.param({"value": "Hospital Bed Capacity", "cites": None}, id="null cites"),
        pytest.param({"value": "Hospital Bed Capacity", "cites": 2}, id="a number for cites"),
    ],
)
def test_refuses_a_field_without_a_citation(tmp_path: Path, cited) -> None:
    output = run_agent(tmp_path, task(HEALTH))
    rows = entries(tmp_path)
    rows[0]["name"] = cited
    write_entries(tmp_path, rows)
    verdict = judge(tmp_path, HEALTH, output)
    assert verdict["valid"] is False and verdict["details"]["bad_fields"] == {"src-006.name": "not {value, cites}"}
    assert verdict["score"] == round(39 / 40, 4)


def test_refuses_a_missing_field(tmp_path: Path) -> None:
    output = run_agent(tmp_path, task(HEALTH))
    rows = entries(tmp_path)
    del rows[3]["version"]
    write_entries(tmp_path, rows)
    verdict = judge(tmp_path, HEALTH, output)
    assert verdict["valid"] is False and verdict["details"]["bad_fields"] == {"src-024.version": "missing"}


def test_refuses_a_missing_source(tmp_path: Path) -> None:
    output = run_agent(tmp_path, task(HEALTH))
    write_entries(tmp_path, entries(tmp_path)[:-1])
    verdict = judge(tmp_path, HEALTH, output)
    assert verdict["valid"] is False and verdict["details"]["missing"] == ["src-048"]
    assert verdict["details"]["cited"] == 1.0


def test_refuses_citations_without_a_ledger(tmp_path: Path) -> None:
    run_agent(tmp_path, task(HEALTH))
    (tmp_path / LEDGER).unlink()
    verdict = judge(tmp_path, HEALTH, total(8))
    assert verdict["valid"] is False and len(verdict["details"]["bad_fields"]) == 40 and verdict["score"] == 0.0


def test_refuses_a_task_without_a_reference_or_with_a_bad_filter(tmp_path: Path) -> None:
    run_agent(tmp_path, task(HEALTH))
    verdict = assert_verdict(verifier.verify_task(TASK, task(HEALTH), total(8), None, str(tmp_path)))
    assert verdict["message"] == "reference: catalog_truth was not pinned"
    reference = truth(task(HEALTH), tmp_path / "scratch")
    bad = task({**HEALTH, "updated_since": -1})
    verdict = assert_verdict(verifier.verify_task(TASK, bad, total(8), reference, str(tmp_path)))
    assert failing(verdict) == ["task-input"] and verdict["score"] == 0.0


# Malformed
@pytest.mark.parametrize(
    "text",
    [
        "{not json",
        "[]",
        '{"entries": {}}',
        '{"entries": ["src-006"]}',
        '{"entries": [{"name": {"value": "x", "cites": "call-0001"}}]}',
        '{"entries": [{"id": 6}]}',
        '{"entries": [{"id": "src-006", "license": {"value": "odbl", "cites": "call-0001"}}]}',
    ],
)
def test_refuses_a_malformed_catalog_file(tmp_path: Path, text: str) -> None:
    run_agent(tmp_path, task(HEALTH))
    (tmp_path / CATALOG).write_text(text)
    verdict = judge(tmp_path, HEALTH, total(8))
    assert verdict["valid"] is False and verdict["score"] == 0.0 and CATALOG in verdict["message"]


def test_refuses_a_broken_ledger(tmp_path: Path) -> None:
    output = run_agent(tmp_path, task(HEALTH))
    with (tmp_path / LEDGER).open("a") as ledger:
        ledger.write("{not json\n")
    verdict = judge(tmp_path, HEALTH, output)
    assert verdict["valid"] is False and verdict["score"] == 0.0
    assert verdict["message"].startswith("ledger: the call ledger is broken: ledger line ")
    # Every outcome check waits on the integrity check that failed.
    unchecked = verdict["details"]["checks"][len(INTEGRITY):]
    assert {(c["ok"], c["message"]) for c in unchecked} == {(None, "Not checked: ledger did not hold.")}


# Boundary
def test_a_rate_limited_call_then_its_retry_cites_the_retry(tmp_path: Path) -> None:
    # Health's 5th catalog read (get_source src-024) is rate-limited, then retried after a wait.
    output = run_agent(tmp_path, task(HEALTH))
    failed = [c for c in calls(tmp_path) if "error" in c]
    assert failed and all(c["tool"] in ("list_sources", "get_source") for c in failed)
    assert judge(tmp_path, HEALTH, output)["valid"] is True
    for c in failed:
        assert all(f["cites"] != c["call_id"] for row in entries(tmp_path) for k, f in row.items() if k != "id")


def test_citing_list_sources_holds_only_where_its_listing_is_current(tmp_path: Path) -> None:
    # Current values cited to the listing: right wherever the cached index shows them as they are.
    output = run_agent(tmp_path, task(HEALTH), cite_listing=True)
    first = entries(tmp_path)[0]
    assert first["name"]["cites"] != first["records"]["cites"]
    verdict = judge(tmp_path, HEALTH, output)
    assert verdict["valid"] is False and sorted(verdict["details"]["bad_fields"]) == STALE
    assert "what call-" in verdict["details"]["bad_fields"]["src-012.updated"]


def test_a_stale_listing_value_cited_faithfully_is_still_wrong(tmp_path: Path) -> None:
    # The listing's own values cited to the listing: every citation holds, but 6 values are not current.
    output = run_agent(tmp_path, task(HEALTH), trust_listing=True)
    verdict = judge(tmp_path, HEALTH, output)
    assert verdict["valid"] is False and sorted(verdict["details"]["bad_fields"]) == STALE
    assert "current updated is 2019" in verdict["details"]["bad_fields"]["src-012.updated"]
    assert verdict["details"]["cited"] == round(1 - len(STALE) / 40, 4)
    # The citations hold; only the values are not current, and the check names what get_source gives.
    assert failing(verdict) == ["values-current"]
    assert named(verdict, "values-current")["expected"]["src-012.updated"] == 2019


def test_a_stale_listed_year_does_not_drop_a_match(tmp_path: Path) -> None:
    assert judge(tmp_path, EXAMPLE, run_agent(tmp_path, task(EXAMPLE)))["valid"] is True
    refiltered = tmp_path / "refiltered"
    refiltered.mkdir()
    verdict = judge(refiltered, EXAMPLE, run_agent(refiltered, task(EXAMPLE), refilter_on_listing=True))
    assert verdict["valid"] is False and verdict["details"]["missing"] == ["src-012", "src-024"]


def test_list_sources_cannot_be_cited_for_what_it_does_not_list(tmp_path: Path) -> None:
    output = run_agent(tmp_path, task(HEALTH), cite_listing=True)
    listing_call = entries(tmp_path)[0]["name"]["cites"]
    edit_field(tmp_path, 0, "records", cites=listing_call)
    verdict = judge(tmp_path, HEALTH, output)
    assert verdict["valid"] is False and "has no records" in verdict["details"]["bad_fields"]["src-006.records"]


def test_a_listing_page_is_cited_only_for_the_sources_it_lists(tmp_path: Path) -> None:
    output = run_agent(tmp_path, task(HEALTH), cite_listing=True)
    rows = entries(tmp_path)
    second_page = rows[-1]["name"]["cites"]
    edit_field(tmp_path, 0, "name", cites=second_page)
    verdict = judge(tmp_path, HEALTH, output)
    assert verdict["valid"] is False and "did not return src-006" in verdict["details"]["bad_fields"]["src-006.name"]


def test_an_empty_match_needs_no_catalog_and_a_zero_total(tmp_path: Path) -> None:
    output = run_agent(tmp_path, task(NOTHING))
    assert output.total == 0 and not (tmp_path / CATALOG).exists()
    assert judge(tmp_path, NOTHING, output)["valid"] is True
    write_entries(tmp_path, [])
    assert judge(tmp_path, NOTHING, output)["valid"] is True
    assert judge(tmp_path, NOTHING, total(1))["valid"] is False


def test_giving_up_at_a_rate_limit_misses_sources(tmp_path: Path) -> None:
    verdict = judge(tmp_path, HEALTH, run_agent(tmp_path, task(HEALTH), give_up_on_rate_limit=True))
    assert verdict["valid"] is False and len(verdict["details"]["missing"]) == 8 - (RATE_LIMIT - 1)
    assert verdict["details"]["cited"] == 1.0


# The scoring policy (verifier/citations.py): strict validity, score = cited fraction x F1 over ids x total factor.
def good_calls() -> tuple[list, dict]:
    """Four sources, each described by its own get_source call, and their rightly cited entries."""
    recorded, ledger = [], {}
    for number, source in enumerate("abcd", 1):
        call_id = f"call-{number:04d}"
        detail = {"id": source, "name": source.upper(), "access_method": "rest", "updated": 2020, "records": number,
                  "version": str(number)}
        ledger[call_id] = {"call_id": call_id, "tool": "get_source", "response": {"call_id": call_id, "source": detail}}
        recorded.append((source, {f: {"value": detail[f], "cites": call_id} for f in checks.FIELDS}))
    return recorded, ledger


def with_bad(recorded: list, count: int) -> list:
    """``recorded`` with its first ``count`` fields (in entry order) citing a call that was never made."""
    out, left = [], count
    for source, fields in recorded:
        fields = dict(fields)
        for f in checks.FIELDS:
            if left:
                fields[f] = {**fields[f], "cites": "call-9999"}
                left -= 1
        out.append((source, fields))
    return out


# The four sources' current fields, as get_source gives them: what good_calls cites.
CURRENT = {
    source: {"name": source.upper(), "access_method": "rest", "updated": 2020, "records": number, "version": str(number)}
    for number, source in enumerate("abcd", 1)
}


def test_a_faithfully_cited_value_that_is_not_current_is_miscited() -> None:
    recorded, ledger = good_calls()
    ledger["call-0001"]["response"]["source"]["name"] = "A (OLD)"
    recorded[0][1]["name"]["value"] = "A (OLD)"
    verdict = score_citations(recorded, ledger, CURRENT, 4, 4)
    assert verdict["valid"] is False and verdict["score"] == 0.95
    assert verdict["details"]["bad_fields"] == {"a.name": "'A (OLD)' is what call-0001 returned, but the source's "
                                                          "current name is 'A'"}


@pytest.mark.parametrize(
    ("change", "submitted", "valid", "score"),
    [
        pytest.param(lambda r: r, 4, True, 1.0, id="exact"),
        pytest.param(lambda r: r, 3, False, 0.5, id="exact catalog, wrong total"),
        pytest.param(lambda r: with_bad(r, 1), 4, False, 0.95, id="one of 20 fields miscited"),
        pytest.param(lambda r: with_bad(r, 10), 4, False, 0.5, id="half the fields miscited"),
        pytest.param(lambda r: with_bad(r, 20), 4, False, 0.0, id="every field miscited"),
        pytest.param(lambda r: r[:3], 4, False, 0.8571, id="one source missing"),
        pytest.param(lambda r: [*r, r[0]], 4, False, 0.8889, id="one source repeated"),
        pytest.param(lambda r: [], 0, False, 0.0, id="nothing recorded"),
    ],
)
def test_the_score_follows_the_policy(change, submitted, valid, score) -> None:
    recorded, ledger = good_calls()
    verdict = score_citations(change(recorded), ledger, CURRENT, submitted, len(CURRENT))
    assert (verdict["valid"], verdict["score"]) == (valid, score)
    assert (verdict["score"] == 1.0) is verdict["valid"] and 0.0 <= verdict["score"] <= 1.0


def test_an_empty_match_scores_by_the_policy() -> None:
    assert score_citations([], {}, {}, 0, 0)["score"] == 1.0
    assert score_citations([], {}, {}, 1, 0)["score"] == WRONG_TOTAL_FACTOR
    recorded, ledger = good_calls()
    assert score_citations(recorded[:1], ledger, {}, 1, 0)["score"] == 0.0


# Tools
def test_list_sources_checks(tmp_path: Path) -> None:
    given = build_output({"filter": HEALTH, "cursor": None}, ListSourcesInput)
    made = build_output(run_call("list_sources", plain_output(given), tmp_path), ListSourcesOutput)
    assert verifier.verify_input("list_sources", given)["valid"] is True
    assert verifier.verify_output("list_sources", given, made, str(tmp_path))["valid"] is True
    bad_cursor = build_output({"filter": HEALTH, "cursor": "page-2"}, ListSourcesInput)
    assert verifier.verify_input("list_sources", bad_cursor)["valid"] is False
    stray = build_output({"filter": {**EVERY, "domains": ["energy"]}, "cursor": None}, ListSourcesInput)
    assert verifier.verify_output("list_sources", stray, made, str(tmp_path))["valid"] is False
    last_page = build_output({"filter": HEALTH, "cursor": "cursor-5"}, ListSourcesInput)
    assert verifier.verify_output("list_sources", last_page, made, str(tmp_path))["valid"] is False
    uncited = build_output({**plain_output(made), "call_id": "page-1"}, ListSourcesOutput)
    assert verifier.verify_output("list_sources", given, uncited, str(tmp_path))["valid"] is False


def test_get_source_checks(tmp_path: Path) -> None:
    given = build_output({"id": "src-006"}, GetSourceInput)
    made = build_output(run_call("get_source", plain_output(given), tmp_path), GetSourceOutput)
    assert verifier.verify_input("get_source", given)["valid"] is True
    assert verifier.verify_output("get_source", given, made, str(tmp_path))["valid"] is True
    assert verifier.verify_input("get_source", build_output({"id": "health-6"}, GetSourceInput))["valid"] is False
    other = build_output({"id": "src-012"}, GetSourceInput)
    assert verifier.verify_output("get_source", other, made, str(tmp_path))["valid"] is False


def test_wait_checks(tmp_path: Path) -> None:
    given = build_output({"seconds": 30}, WaitInput)
    made = build_output(run_call("wait", plain_output(given), tmp_path), WaitOutput)
    assert verifier.verify_input("wait", given)["valid"] is True
    assert verifier.verify_output("wait", given, made, str(tmp_path))["valid"] is True
    assert verifier.verify_input("wait", build_output({"seconds": MAX_WAIT + 1}, WaitInput))["valid"] is False
    assert RATE_WINDOW <= MAX_WAIT


def test_record_entry_checks(tmp_path: Path) -> None:
    described = call(tmp_path, "get_source", {"id": "src-006"})
    given = build_output({"entry": entry("src-006", described["source"], described["call_id"])}, RecordEntryInput)
    made = build_output(run_call("record_entry", plain_output(given), tmp_path), RecordEntryOutput)
    assert verifier.verify_input("record_entry", given)["valid"] is True
    assert verifier.verify_output("record_entry", given, made, str(tmp_path))["valid"] is True
    bad_id = build_output({"entry": {**plain_output(given.entry), "id": "health-6"}}, RecordEntryInput)
    assert verifier.verify_input("record_entry", bad_id)["valid"] is False
    edit_field(tmp_path, 0, "records", value=1)
    assert verifier.verify_output("record_entry", given, made, str(tmp_path))["valid"] is False


def test_catalog_truth_checks(tmp_path: Path) -> None:
    given = task(HEALTH)
    made = truth(given, tmp_path)
    assert verifier.verify_input("catalog_truth", given)["valid"] is True
    assert verifier.verify_output("catalog_truth", given, made, str(tmp_path))["valid"] is True
    miscounted = build_output({**plain_output(made), "total": 9}, CatalogTruthOutput)
    assert verifier.verify_output("catalog_truth", given, miscounted, str(tmp_path))["valid"] is False
    assert verifier.verify_input("catalog_truth", task({**EVERY, "updated_since": -1}))["valid"] is False
