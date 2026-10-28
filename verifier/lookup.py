"""get_source: the requested source's every field, under its own call_id."""

from .checks import SOURCE_ID, call_id_problem, result


def verify_input(value):
    if not SOURCE_ID.fullmatch(value.id):
        return result(False, f"{value.id!r} is not a catalog source id")
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    problem = call_id_problem(output_value.call_id)
    if problem:
        return result(False, problem)
    source = output_value.source
    if source.id != input_value.id:
        return result(False, f"asked for {input_value.id}, described {source.id}")
    if source.records < 0 or not source.version:
        return result(False, "the source's records or version is not a real value")
    return result(True, f"{source.id} is described")
