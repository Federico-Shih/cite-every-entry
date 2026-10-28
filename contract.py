"""Each tool's and task's typed input and output (see nanoagent.plugin.v0001.contract): declarations only."""

from dataclasses import dataclass
from enum import Enum
from typing import Annotated

from slimconfig import Output


class Tool(Enum):
    LIST_SOURCES = "list_sources"
    GET_SOURCE = "get_source"
    CHECK_FRESH = "check_fresh"
    WAIT = "wait"
    RECORD_ENTRY = "record_entry"
    CATALOG_TRUTH = "catalog_truth"


class Task(Enum):
    CITE_EVERY_ENTRY = "cite-every-entry"


class AccessMethod(Enum):
    """How a source is read; mirrors Empiric's AccessKind (src/empiric/contracts/sources.py)."""

    REST = "rest"
    FILE = "file"
    HUB = "hub"
    SQL = "sql"


class Domain(Enum):
    CLIMATE = "climate"
    HEALTH = "health"
    FINANCE = "finance"
    TRANSPORT = "transport"
    EDUCATION = "education"
    ENERGY = "energy"


class Format(Enum):
    CSV = "csv"
    JSON = "json"
    PARQUET = "parquet"
    XML = "xml"


class License(Enum):
    CC_BY = "cc-by"
    CC0 = "cc0"
    ODBL = "odbl"
    PROPRIETARY = "proprietary"


SOURCE_ID = "The source's catalog id, e.g. src-007"
ACCESS_METHOD = "How the source is read: rest, file, hub or sql"
CURSOR = "Where the page starts: null for the first page, else the next_cursor the previous page returned"
CALL_ID = "This call's id, e.g. call-0007: what a catalog entry cites for a value this response holds"
CITES = (
    "The call_id of the list_sources or get_source call whose response holds this value for this source; the value"
    " must also be the source's current one, as get_source gives it"
)
ETAG = "The tag of a revision of the source's fields: two different tags mean different revisions"


@dataclass
class SourceFilter(Output):
    domains: Annotated[list[Domain], "Keep sources in one of these domains; empty keeps every domain"]
    formats: Annotated[list[Format], "Keep sources in one of these formats; empty keeps every format"]
    access_methods: Annotated[list[AccessMethod], "Keep sources read one of these ways; empty keeps every way"]
    licenses: Annotated[list[License], "Keep sources under one of these licenses; empty keeps every license"]
    updated_since: Annotated[int, "Keep sources last updated in this year or later; 0 keeps every year"]


@dataclass
class Source(Output):
    """A source as list_sources lists it, from a cached index: for some sources the index holds an older revision,
    so its access method, updated year, records or version may be stale. Its etag names the revision the index holds;
    check_fresh gives the current one, and get_source every field as it is now."""

    id: Annotated[str, SOURCE_ID]
    name: Annotated[str, "The source's name"]
    domain: Annotated[Domain, "The source's subject area"]
    format: Annotated[Format, "The format its records come in"]
    access_method: Annotated[AccessMethod, ACCESS_METHOD]
    license: Annotated[License, "The license it is published under"]
    updated: Annotated[int, "The year it was last updated"]
    records: Annotated[int, "How many records the source holds"]
    version: Annotated[str, "The source's release version, a string such as 3 or 4.0.2"]
    etag: Annotated[str, ETAG]


@dataclass
class SourceDetail(Output):
    """A source as get_source describes it: every field as it is now."""

    id: Annotated[str, SOURCE_ID]
    name: Annotated[str, "The source's name"]
    domain: Annotated[Domain, "The source's subject area"]
    format: Annotated[Format, "The format its records come in"]
    access_method: Annotated[AccessMethod, ACCESS_METHOD]
    license: Annotated[License, "The license it is published under"]
    updated: Annotated[int, "The year it was last updated"]
    records: Annotated[int, "How many records the source holds"]
    version: Annotated[str, "The source's release version, a string such as 3 or 4.0.2"]


@dataclass
class CitedText(Output):
    value: Annotated[str, "The text exactly as the cited response gives it"]
    cites: Annotated[str, CITES]


@dataclass
class CitedNumber(Output):
    value: Annotated[int, "The number exactly as the cited response gives it"]
    cites: Annotated[str, CITES]


@dataclass
class CitedAccessMethod(Output):
    value: Annotated[AccessMethod, ACCESS_METHOD]
    cites: Annotated[str, CITES]


@dataclass
class CitedEntry(Output):
    """One catalog entry: every field is a value and the call it came from."""

    id: Annotated[str, SOURCE_ID]
    access_method: Annotated[CitedAccessMethod, "The source's access method and the call that gave it"]
    updated: Annotated[CitedNumber, "The year it was last updated and the call that gave it"]
    records: Annotated[CitedNumber, "How many records it holds and the call that gave it"]
    version: Annotated[CitedText, "Its version string and the call that gave it"]


@dataclass
class CatalogInput(Output):
    filter: Annotated[SourceFilter, "Which sources of the catalog to record"]


@dataclass
class CatalogOutput(Output):
    total: Annotated[int, "How many sources match the filter: the number of entries in catalog.json"]


@dataclass
class ListSourcesInput(Output):
    filter: Annotated[SourceFilter, "Which sources to list; pass the same filter for every page"]
    cursor: Annotated[str | None, CURSOR]


@dataclass
class ListSourcesOutput(Output):
    call_id: Annotated[str, CALL_ID]
    sources: Annotated[
        list[Source], "This page's sources that match the filter, in catalog order, as the cached index shows them"
    ]
    next_cursor: Annotated[str | None, "The cursor of the next page; null when this page is the last"]


@dataclass
class GetSourceInput(Output):
    id: Annotated[str, "The id of the source to describe, as list_sources lists it"]


@dataclass
class GetSourceOutput(Output):
    call_id: Annotated[str, CALL_ID]
    source: Annotated[SourceDetail, "The source's every field"]


@dataclass
class CheckFreshInput(Output):
    ids: Annotated[list[str], "1 to 10 source ids, as list_sources lists them"]


@dataclass
class Freshness(Output):
    id: Annotated[str, SOURCE_ID]
    etag: Annotated[str, "The source's current etag: a listing that shows another one shows an older revision"]


@dataclass
class CheckFreshOutput(Output):
    call_id: Annotated[str, CALL_ID]
    etags: Annotated[list[Freshness], "Each asked source's current etag, in the order asked"]


@dataclass
class WaitInput(Output):
    seconds: Annotated[int, "How many seconds to wait, 0 to 3600: the retry_after a rate-limited call named"]


@dataclass
class WaitOutput(Output):
    call_id: Annotated[str, CALL_ID]
    now: Annotated[int, "The catalog's clock after waiting, in seconds since the run began"]


@dataclass
class RecordEntryInput(Output):
    entry: Annotated[CitedEntry, "The entry to add to catalog.json, each value cited to the call that gave it"]


@dataclass
class RecordEntryOutput(Output):
    call_id: Annotated[str, CALL_ID]
    recorded: Annotated[CitedEntry, "The entry added to catalog.json"]
    count: Annotated[int, "How many entries catalog.json holds now"]
    path: Annotated[str, "The catalog file, relative to the plugin workspace: catalog.json"]


@dataclass
class CatalogTruthOutput(Output):
    ids: Annotated[list[str], "The id of every source that matches the filter, in catalog order"]
    total: Annotated[int, "How many sources match the filter"]
    sources: Annotated[list[SourceDetail], "Every matching source's authoritative fields, as get_source gives them"]


TOOLS = {
    Tool.LIST_SOURCES: (ListSourcesInput, ListSourcesOutput),
    Tool.GET_SOURCE: (GetSourceInput, GetSourceOutput),
    Tool.CHECK_FRESH: (CheckFreshInput, CheckFreshOutput),
    Tool.WAIT: (WaitInput, WaitOutput),
    Tool.RECORD_ENTRY: (RecordEntryInput, RecordEntryOutput),
    Tool.CATALOG_TRUTH: (CatalogInput, CatalogTruthOutput),
}
TASKS = {Task.CITE_EVERY_ENTRY: (CatalogInput, CatalogOutput)}
