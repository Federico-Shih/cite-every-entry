from __future__ import annotations

from pathlib import Path

from contract import CatalogInput, CatalogTruthOutput
from plugin.sources import matching


def catalog_truth(given: CatalogInput, workspace: Path) -> CatalogTruthOutput:
    """The reference tool: every source the filter matches, with its current fields, so the verifier knows which
    entries must be there and what each value must be. Where each value came from is checked against the call
    ledger. The agent never sees it."""
    sources = matching(given.filter)
    return CatalogTruthOutput(ids=[source.id for source in sources], total=len(sources), sources=sources)
