"""record_entry: the cited entry is in catalog.json, where the output says. Whether its citations hold is the task's
verdict (citations.py)."""

import json
from pathlib import Path

from .checks import CATALOG, SOURCE_ID, call_id_problem, plain_entry, result


def verify_input(value):
    if not SOURCE_ID.fullmatch(value.entry.id):
        return result(False, f"{value.entry.id!r} is not a catalog source id")
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    problem = call_id_problem(output_value.call_id)
    if problem:
        return result(False, problem)
    if output_value.recorded != input_value.entry or output_value.path != CATALOG:
        return result(False, f"the output is not the requested entry in {CATALOG}")
    path = Path(workspace) / CATALOG
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))["entries"] if path.is_file() else []
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        return result(False, f'{CATALOG} is not {{"entries": [...]}}')
    count = output_value.count
    if not isinstance(entries, list) or not 1 <= count <= len(entries):
        return result(False, f"{CATALOG} does not hold {count} entries")
    if entries[count - 1] != plain_entry(input_value.entry):
        return result(False, f"{CATALOG} does not hold the entry at position {count}")
    return result(True, "the entry is recorded", count=count)
