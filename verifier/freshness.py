"""check_fresh: one etag for each asked source, in the order asked, under its own call_id."""

from .checks import FRESH_BATCH, SOURCE_ID, call_id_problem, duplicates, result


def verify_input(value):
    ids = value.ids
    if not 1 <= len(ids) <= FRESH_BATCH:
        return result(False, f"ask for 1 to {FRESH_BATCH} ids, not {len(ids)}")
    strays = [source_id for source_id in ids if not SOURCE_ID.fullmatch(source_id)]
    if strays:
        return result(False, "not catalog source ids", ids=strays)
    if duplicates(ids):
        return result(False, "an id is asked for twice", ids=duplicates(ids))
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    problem = call_id_problem(output_value.call_id)
    if problem:
        return result(False, problem)
    answered = [fresh.id for fresh in output_value.etags]
    if answered != input_value.ids:
        return result(False, "the etags are not the asked sources, in order", ids=answered)
    if not all(fresh.etag for fresh in output_value.etags):
        return result(False, "an etag is empty")
    return result(True, f"{len(answered)} current etags")
