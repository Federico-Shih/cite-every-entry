from __future__ import annotations

from pathlib import Path

from contract import WaitInput, WaitOutput
from plugin.sources import current_call, limiter

MAX_WAIT = 3600


def wait(given: WaitInput, workspace: Path) -> WaitOutput:
    """Move the run's virtual clock forward; no wall time passes."""
    call_id = current_call(workspace)
    if not 0 <= given.seconds <= MAX_WAIT:
        raise ValueError(f"seconds must be 0 to {MAX_WAIT}")
    return WaitOutput(call_id=call_id, now=limiter(workspace).wait(given.seconds))
