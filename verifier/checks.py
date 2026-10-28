"""Checks shared by the tool verifiers. Pure functions of their arguments and the files on disk."""

import re

# These mirror src/plugin (the verifier may import only the standard library and the contract);
# tests/test_verifier.py holds them equal.
PAGE_SIZE = 5
MAX_WAIT = 3600
FRESH_BATCH = 10
CATALOG = "catalog.json"
CURSOR = re.compile(r"cursor-(\d+)")
SOURCE_ID = re.compile(r"src-\d{3}")
CALL_ID = re.compile(r"call-\d{4,}")
# Every cited field of a catalog entry (contract.CitedEntry, less its id), and the tools whose responses it may cite.
# The name is not one: free text is never judged.
FIELDS = ("access_method", "updated", "records", "version")
CITABLE = ("list_sources", "get_source")


def result(valid, message, *, score=None, **details):
    return {
        "valid": valid,
        "score": float(valid) if score is None else score,
        "message": message,
        "details": details,
    }


def check(check_id, constraint, ok, *, expected=None, actual=None, message=""):
    """One entry of a task verdict's ``details.checks``: ``ok`` is True (holds), False (fails) or None (not checked)."""
    return {
        "id": check_id,
        "constraint": constraint,
        "ok": ok,
        "expected": expected,
        "actual": actual,
        "message": message,
    }


def skipped(check_id, constraint, waited_on):
    """A check left unchecked because ``waited_on``, a check it needs, did not hold."""
    return check(check_id, constraint, None, message=f"Not checked: {waited_on} did not hold.")


def task_verdict(checks, summary, score, **details):
    """The task's verdict from its ordered ``checks``: valid when every one holds, then with ``summary`` and score
    1.0. Otherwise the message is the first failing check's id and message (and how many more fail), and the score
    is ``score`` capped at 0.99."""
    failing = [entry for entry in checks if entry["ok"] is False]
    if not failing:
        return result(True, summary, score=1.0, checks=checks, **details)
    first = failing[0]
    more = f" (+{len(failing) - 1} more)" if len(failing) > 1 else ""
    return result(False, f"{first['id']}: {first['message']}{more}", score=min(score, 0.99), checks=checks, **details)


def listing_matches(source, wanted):
    """Whether the listed contract Source ``source`` passes the contract SourceFilter ``wanted`` on every field the
    cached index never shows stale: the filter goes by the current access method and updated year, which a listing
    may show stale."""
    return (
        (not wanted.domains or source.domain in wanted.domains)
        and (not wanted.formats or source.format in wanted.formats)
        and (not wanted.licenses or source.license in wanted.licenses)
    )


def filter_problem(wanted):
    if wanted.updated_since < 0:
        return "updated_since must be a year, or 0 for every year"
    return None


def call_id_problem(call_id):
    return None if CALL_ID.fullmatch(call_id) else f"call_id {call_id!r} is not a call id"


def duplicates(ids):
    return sorted({item for item in ids if ids.count(item) > 1})


def plain_entry(entry):
    """A contract CitedEntry as record_entry writes it to catalog.json."""
    return {
        "id": entry.id,
        "access_method": {"value": entry.access_method.value.value, "cites": entry.access_method.cites},
        "updated": {"value": entry.updated.value, "cites": entry.updated.cites},
        "records": {"value": entry.records.value, "cites": entry.records.cites},
        "version": {"value": entry.version.value, "cites": entry.version.cites},
    }
