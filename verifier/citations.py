"""The cite-every-entry task: every field of workspace/catalog.json against the call it cites in the ledger."""

import json
from pathlib import Path

from .checks import CATALOG, CITABLE, FIELDS, check, duplicates, filter_problem, skipped, task_verdict
from .ledger import calls_by_id

# The score's multiplier when the submitted total is not the true count.
WRONG_TOTAL_FACTOR = 0.5


def read_catalog(workspace):
    """catalog.json's entries as (id, {field: cited value}) pairs, and a problem or None. No file: no entries.

    A field may be missing or badly cited (that is the task's grade); anything else off the shape is malformed."""
    path = Path(workspace) / CATALOG
    if not path.is_file():
        return [], None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return [], f"{CATALOG} is not JSON"
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return [], f'{CATALOG} is not {{"entries": [...]}}'
    pairs = []
    for entry in entries:
        if not (isinstance(entry, dict) and isinstance(entry.get("id"), str) and set(entry) <= {"id", *FIELDS}):
            return [], f"{CATALOG} holds an entry that is not {{id, {', '.join(FIELDS)}}}: {entry!r}"
        pairs.append((entry["id"], {field: entry[field] for field in FIELDS if field in entry}))
    return pairs, None


def cited_source(call, source_id):
    """The source ``source_id`` as the successful ``call`` returned it, or a reason it holds none."""
    if "response" not in call:
        return None, f"{call['call_id']} failed ({call.get('error')}), so it returned nothing"
    if call["tool"] not in CITABLE:
        return None, f"{call['call_id']} is a {call['tool']} call, not one of {', '.join(CITABLE)}"
    response = call["response"]
    if not isinstance(response, dict):
        return None, f"{call['call_id']} returned no source"
    found = [response.get("source")] if call["tool"] == "get_source" else response.get("sources") or []
    for source in found:
        if isinstance(source, dict) and source.get("id") == source_id:
            return source, None
    return None, f"{call['call_id']} did not return {source_id}"


# The checks of a verdict, in order: (id, constraint). The first four guard the run's integrity: when one fails the
# score is 0 and the outcome checks after them are not checked.
INTEGRITY = (
    ("reference", "catalog_truth pinned the matching sources before the agent ran"),
    ("task-input", "The task's filter is valid"),
    ("catalog-file", f"{CATALOG}, if written, is {{\"entries\": [...]}} with each entry {{id, {', '.join(FIELDS)}}}"),
    ("ledger", "The call ledger .ledger/calls.jsonl is readable, one call per line"),
)
OUTCOME = (
    ("all-recorded", f"Every source the filter matches is recorded in {CATALOG}"),
    ("no-extra", f"No source the filter does not match is recorded in {CATALOG}"),
    ("no-repeats", f"No source is recorded in {CATALOG} twice"),
    (
        "fields-cited",
        (
            "Every field is {value, cites}, citing a successful list_sources or get_source call that returned exactly "
            "that value for that source"
        ),
    ),
    ("values-current", "Every cited value is the source's current value, as get_source gives it"),
    ("total-exact", "The submitted total is the number of sources the filter matches"),
)


def field_problem(source_id, field, cited, calls, current):
    """Why ``cited``, the entry's ``field`` of ``source_id``, is not a value its cited call returned that is also
    the source's current value (``current``: its fields as get_source gives them, or None for an extra source), or
    None. A problem is (check id, why, the value expected or None)."""
    if cited is None:
        return "fields-cited", "missing", None
    if not (isinstance(cited, dict) and set(cited) == {"value", "cites"} and isinstance(cited["cites"], str)):
        return "fields-cited", "not {value, cites}", None
    call = calls.get(cited["cites"])
    if call is None:
        return "fields-cited", f"cites {cited['cites']!r}, a call that was never made", None
    source, problem = cited_source(call, source_id)
    if problem:
        return "fields-cited", problem, None
    if field not in source:
        return "fields-cited", f"{cited['cites']} has no {field} for {source_id}", None
    value, returned = cited["value"], source[field]
    # Exactly: the same JSON type and value, so "3" is not 3 and 1 is not true.
    if type(value) is not type(returned) or value != returned:
        return "fields-cited", f"{value!r} is not {returned!r}, what {cited['cites']} returned", returned
    # A cached listing can return a stale value; citing it faithfully does not make it the source's value.
    if current is not None and (type(value) is not type(current[field]) or value != current[field]):
        why = f"{value!r} is what {cited['cites']} returned, but the source's current {field} is {current[field]!r}"
        return "values-current", why, current[field]
    return None


def listed(values, limit=5):
    shown = ", ".join(str(value) for value in values[:limit])
    return shown + (f" and {len(values) - limit} more" if len(values) > limit else "")


def field_check(check_id, constraint, problems):
    """The check over every field whose problem is ``check_id``'s: {key: (why, expected, recorded)}."""
    if not problems:
        return check(check_id, constraint, True)
    shown = "; ".join(f"{key}: {why}" for key, (why, _expected, _recorded) in list(problems.items())[:5])
    more = f" (and {len(problems) - 5} more)" if len(problems) > 5 else ""
    what = "cited rightly" if check_id == "fields-cited" else "current"
    head = f"{len(problems)} field{' is' if len(problems) == 1 else 's are'} not {what}"
    return check(
        check_id,
        constraint,
        False,
        expected={key: expected for key, (_why, expected, _recorded) in problems.items()},
        actual={key: recorded for key, (_why, _expected, recorded) in problems.items()},
        message=f"{head}: {shown}{more}",
    )


def score_citations(recorded, calls, current, total, true_total, integrity=()):
    """The verdict on a cited catalog.

    ``recorded``: (id, {field: cited value}) pairs in catalog.json, in order; ``calls``: the ledger by call_id;
    ``current``: {id: {field: value}} of every source that must be recorded, its fields as get_source gives them;
    ``total``: the submitted count; ``true_total``: the true count; ``integrity``: the integrity checks before
    these, all holding.
    """
    # Valid only when every check holds (docs/PLUGINS_PLAN.md §3). score = cited x F1 x total factor, capped at
    # 0.99 unless valid, so it is 1.0 exactly when the catalog is valid:
    # - cited: the fraction of recorded fields (every entry's FIELDS, repeats included) that cite rightly a value
    #   that is current;
    # - F1 over ids: an extra entry lowers precision, a missing one recall, even when its citations hold;
    # - a wrong total halves the score: the count is the task's answer, but the citing work was real.
    required = list(current)
    ids = [source for source, _fields in recorded]
    repeated = duplicates(ids)
    extra = sorted(set(ids) - set(required))
    missing = sorted(set(required) - set(ids))
    bad_fields = {}
    by_check = {"fields-cited": {}, "values-current": {}}
    good = 0
    for source, fields in recorded:
        for field in FIELDS:
            problem = field_problem(source, field, fields.get(field), calls, current.get(source))
            if problem:
                check_id, why, expected = problem
                key = f"{source}.{field}"
                bad_fields[key] = why
                cited = fields.get(field)
                by_check[check_id][key] = (why, expected, cited.get("value") if isinstance(cited, dict) else cited)
            else:
                good += 1
    cited = good / (len(recorded) * len(FIELDS)) if recorded else 1.0
    found = len(set(ids) & set(required))
    if not required and not ids:
        f1 = 1.0
    elif found == 0:
        f1 = 0.0
    else:
        precision, recall = found / len(ids), found / len(required)
        f1 = 2 * precision * recall / (precision + recall)
    total_factor = 1.0 if total == true_total else WRONG_TOTAL_FACTOR
    constraint = dict(OUTCOME)
    counts = {source: ids.count(source) for source in repeated}
    outcome = [
        check("all-recorded", constraint["all-recorded"], True) if not missing else check(
            "all-recorded", constraint["all-recorded"], False, expected=missing,
            message=f"{len(missing)} matching source{'s are' if len(missing) > 1 else ' is'} not recorded: "
                    f"{listed(missing)}",
        ),
        check("no-extra", constraint["no-extra"], True) if not extra else check(
            "no-extra", constraint["no-extra"], False, actual=extra,
            message=f"{len(extra)} recorded source{'s do' if len(extra) > 1 else ' does'} not match the filter: "
                    f"{listed(extra)}",
        ),
        check("no-repeats", constraint["no-repeats"], True) if not repeated else check(
            "no-repeats", constraint["no-repeats"], False, expected={source: 1 for source in repeated}, actual=counts,
            message="recorded more than once: " + listed([f"{source} ({counts[source]} times)" for source in repeated]),
        ),
        field_check("fields-cited", constraint["fields-cited"], by_check["fields-cited"]),
        field_check("values-current", constraint["values-current"], by_check["values-current"]),
        check("total-exact", constraint["total-exact"], True) if total == true_total else check(
            "total-exact", constraint["total-exact"], False, expected=true_total, actual=total,
            message=f"total {total} is not the true count {true_total}",
        ),
    ]
    return task_verdict(
        [*integrity, *outcome],
        f"all {true_total} matching sources are recorded, every field cited",
        round(cited * f1 * total_factor, 4),
        cited=round(cited, 4),
        f1=round(f1, 4),
        total_factor=total_factor,
        bad_fields=bad_fields,
        extra=extra,
        missing=missing,
        repeated=repeated,
        total=total,
        true_total=true_total,
    )


def verify_task(arguments, output, reference, workspace):
    """``arguments``: the contract CatalogInput; ``output``: a contract CatalogOutput; ``reference``: the pinned
    CatalogTruthOutput."""
    constraint = dict(INTEGRITY)
    integrity = []
    if reference is None:
        integrity.append(check("reference", constraint["reference"], False, message="catalog_truth was not pinned"))
    else:
        integrity.append(check("reference", constraint["reference"], True))
    problem = filter_problem(arguments.filter)
    integrity.append(check("task-input", constraint["task-input"], not problem, message=problem or ""))
    recorded, problem = read_catalog(workspace)
    integrity.append(check("catalog-file", constraint["catalog-file"], not problem, message=problem or ""))
    try:
        calls = calls_by_id(workspace)
    except ValueError as error:
        integrity.append(check("ledger", constraint["ledger"], False, message=f"the call ledger is broken: {error}"))
    else:
        integrity.append(check("ledger", constraint["ledger"], True))
    failed = next((entry["id"] for entry in integrity if entry["ok"] is False), None)
    if failed:
        unchecked = [skipped(check_id, text, failed) for check_id, text in OUTCOME]
        return task_verdict([*integrity, *unchecked], "", 0.0)
    current = {
        source.id: {
            "access_method": source.access_method.value,
            "updated": source.updated,
            "records": source.records,
            "version": source.version,
        }
        for source in reference.sources
    }
    return score_citations(recorded, calls, current, output.total, reference.total, integrity)
