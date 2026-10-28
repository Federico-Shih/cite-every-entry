"""list_sources: a page of at most PAGE_SIZE sources, each passing the filter, under its own call_id."""

from .checks import CURSOR, PAGE_SIZE, call_id_problem, duplicates, filter_problem, listing_matches, result


def verify_input(value):
    problem = filter_problem(value.filter)
    if problem:
        return result(False, problem)
    if value.cursor is not None and not CURSOR.fullmatch(value.cursor):
        return result(False, f"cursor {value.cursor!r} is not one a page returned")
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    problem = call_id_problem(output_value.call_id)
    if problem:
        return result(False, problem)
    sources = output_value.sources
    if len(sources) > PAGE_SIZE:
        return result(False, f"a page holds at most {PAGE_SIZE} sources, not {len(sources)}")
    strays = [source.id for source in sources if not listing_matches(source, input_value.filter)]
    if strays:
        return result(False, "the page lists sources the filter does not match", ids=strays)
    ids = [source.id for source in sources]
    if duplicates(ids) or ids != sorted(ids):
        return result(False, "the page's sources are repeated or out of catalog order", ids=ids)
    following = output_value.next_cursor
    if following is not None:
        given = CURSOR.fullmatch(input_value.cursor or "cursor-0")
        found = CURSOR.fullmatch(following)
        start = int(given.group(1)) if given else -1
        if not found or int(found.group(1)) != start + PAGE_SIZE or len(sources) != PAGE_SIZE:
            return result(False, f"next_cursor {following!r} does not follow a full page")
    return result(True, f"a page of {len(sources)} matching sources", last=following is None)
