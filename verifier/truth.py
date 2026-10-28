"""catalog_truth, the reference tool: a total that counts its unique source ids."""

from .checks import SOURCE_ID, duplicates, filter_problem, result


def verify_input(value):
    problem = filter_problem(value.filter)
    return result(False, problem) if problem else result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    ids = output_value.ids
    if duplicates(ids) or output_value.total != len(ids) or not all(SOURCE_ID.fullmatch(i) for i in ids):
        return result(False, "the truth repeats a source, miscounts them or names a non-source")
    if [source.id for source in output_value.sources] != ids:
        return result(False, "the truth's sources are not its ids, in order")
    return result(True, f"{output_value.total} matching sources")
