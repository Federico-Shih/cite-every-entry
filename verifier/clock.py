"""wait: moves the virtual clock forward."""

from .checks import MAX_WAIT, call_id_problem, result


def verify_input(value):
    if not 0 <= value.seconds <= MAX_WAIT:
        return result(False, f"seconds must be 0 to {MAX_WAIT}")
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    problem = call_id_problem(output_value.call_id)
    if problem:
        return result(False, problem)
    if output_value.now < input_value.seconds:
        return result(False, "the clock is behind the time waited")
    return result(True, "the clock moved", now=output_value.now)
