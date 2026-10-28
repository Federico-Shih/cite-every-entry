"""The mock-API engine every plugin shares: a rate limiter on a virtual clock, cursor paging, and the call ledger.

This file is the canonical copy. eval/plugins/sync_engine.py copies it into each plugin, so edit it only here.
Everything is deterministic: time moves only when the agent calls a wait tool, never with the wall clock.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Every tool call is one JSON line here, relative to the workspace; only the MCP server writes it.
LEDGER = Path(".ledger") / "calls.jsonl"
CURSOR_PREFIX = "cursor-"


class RateLimited(RuntimeError):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"rate limited: wait {retry_after} seconds before the next call")
        self.retry_after = retry_after


@dataclass
class RateLimiter:
    """At most ``limit`` calls in each fixed ``window`` of virtual seconds; only ``wait`` moves the clock."""

    limit: int
    window: int
    now: int = 0
    used: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1 or self.window < 1:
            raise ValueError("limit and window must be at least 1")

    def wait(self, seconds: int) -> int:
        if seconds < 0:
            raise ValueError("seconds must not be negative")
        before = self.now // self.window
        self.now += seconds
        if self.now // self.window != before:
            self.used = 0
        return self.now

    def acquire(self) -> None:
        if self.used >= self.limit:
            raise RateLimited(self.window - self.now % self.window)
        self.used += 1


def page(items: list[Any], cursor: str | None, size: int) -> tuple[list[Any], str | None]:
    """The page of ``items`` that ``cursor`` starts (None: the first) and the next page's cursor, None after the last."""
    if size < 1:
        raise ValueError("page size must be at least 1")
    start = 0
    if cursor is not None:
        offset = cursor.removeprefix(CURSOR_PREFIX)
        if not cursor.startswith(CURSOR_PREFIX) or not offset.isdigit() or int(offset) >= len(items):
            raise ValueError(f"unknown cursor: {cursor!r}; pass the next_cursor a previous page returned")
        start = int(offset)
    end = start + size
    return items[start:end], f"{CURSOR_PREFIX}{end}" if end < len(items) else None


@dataclass
class Session:
    """One run's state: the plugin process lives for the whole run, so this survives between tool calls."""

    workspace: Path
    limiter: RateLimiter | None = None
    call_id: str | None = None  # the call in progress, so a tool can cite itself
    calls: int = field(init=False)

    def __post_init__(self) -> None:
        # A restarted process keeps numbering after the calls already in the ledger.
        ledger = self.workspace / LEDGER
        self.calls = len(ledger.read_text(encoding="utf-8").splitlines()) if ledger.exists() else 0

    def rate_limit(self, limit: int, window: int) -> RateLimiter:
        """This run's limiter, made on first use with these settings."""
        if self.limiter is None:
            self.limiter = RateLimiter(limit, window)
        return self.limiter

    def begin(self) -> str:
        self.calls += 1
        self.call_id = f"call-{self.calls:04d}"
        return self.call_id

    def finish(self, tool: str, arguments: dict[str, Any], *, response: Any = None, error: str | None = None) -> None:
        if self.call_id is None:
            raise RuntimeError("finish without begin")
        entry: dict[str, Any] = {"call_id": self.call_id, "tool": tool, "input": arguments}
        entry.update({"error": error} if error is not None else {"response": response})
        ledger = self.workspace / LEDGER
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a", encoding="utf-8") as lines:
            lines.write(json.dumps(entry, sort_keys=True) + "\n")
        self.call_id = None


SESSIONS: dict[Path, Session] = {}


def session_for(workspace: Path) -> Session:
    key = workspace.resolve()
    if key not in SESSIONS:
        SESSIONS[key] = Session(key)
    return SESSIONS[key]
