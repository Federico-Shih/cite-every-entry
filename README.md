# Cite Every Entry

A `nanoagent.plugin/v0001` plugin, created by `nanoagent plugin new` with the
structure of NanoAgent's reference plugin,
[arxiv-source](https://github.com/zeyuyang8/arxiv-source).

An agent pages through a rate-limited mock catalog of 48 data sources, looks up
every source that matches a structured filter, and records it in `catalog.json`
with five fields: `name`, `access_method` (`rest`, `file`, `hub` or `sql`, as
Empiric's `AccessKind`), `updated`, `records` and `version`. Every field is
`{value, cites}`: the value and the `call_id` of the `list_sources` or
`get_source` call that returned it. Every call is recorded in the call ledger,
`.ledger/calls.jsonl`, and the verifier replays each citation against it. The
catalog ships in `src/plugin/fixtures/catalog.json` and the rate limit runs on
a virtual clock, so every run is the same and needs no network.

`list_sources` reads a cached index. For 8 sources it shows a name cut short
with `…` or a stale `updated` year (a fixture row's `listed` fields), while
`get_source` gives every field as it is now. A value faithfully cited to a
listing that shows it stale is still wrong: every value must be the source's
current one. The filter goes by the current year too, so a listing can show a
year older than `updated_since` for a source that matches.

## Tools

| Tool | Does | Code |
|---|---|---|
| `list_sources` | Lists one page (5 sources) of the sources that match a filter, from a cached index that may show a name cut short or a stale year, without `records` and `version`; its response carries its `call_id`; rate-limited | `src/plugin/listing.py` |
| `get_source` | Describes one source with every field, `records` and `version` included; its response carries its `call_id`; rate-limited, and an unknown id raises | `src/plugin/lookup.py` |
| `wait` | Moves the run's virtual clock forward by 0 to 3600 seconds | `src/plugin/clock.py` |
| `record_entry` | Appends a source's id and its five cited fields to `catalog.json`; an unknown or repeated id raises, the citations are not checked | `src/plugin/recording.py` |
| `catalog_truth` | The hidden reference: the id and current fields of every source the filter matches, and their count | `src/plugin/truth.py` |

`list_sources` and `get_source` share one budget: at most 4 calls per 60
virtual seconds, else they raise `rate limited: wait N seconds`. Every call,
failed ones too, is a line of `.ledger/calls.jsonl` (`call_id`, `tool`,
`input`, and its `response` or `error`), written by the MCP server
(`run_call` in `src/plugin/__main__.py`).

### Tasks

| Task | Does | Runner |
|---|---|---|
| `cite-every-entry` | Records every source that matches the filter in `catalog.json`, each field citing the call it came from, and submits the total; checked against the call ledger and `catalog_truth` | `agent`, with `list_sources`, `get_source`, `wait` and `record_entry` |

## Checks

`verifier/citations.py` judges the task against 10 named checks, in order.
Each is an entry of the verdict's `details.checks` with the keys `{id,
constraint, ok, expected, actual, message}`. `ok` is `true` (holds), `false`
(fails) or `null` (not checked, because a check it needs did not hold).
`expected` and `actual` name only the sources or fields concerned, and are
`null` where they say nothing. `message` is `""` when the check holds, why it
fails, or `"Not checked: <id> did not hold."`. Checks 1 to 4 guard the run's
integrity: when one fails, checks 5 to 10 are not checked.

| # | id | What it checks | Example failure message |
|---|---|---|---|
| 1 | `reference` | `catalog_truth` pinned the matching sources before the agent ran | catalog_truth was not pinned |
| 2 | `task-input` | The task's filter is valid | updated_since must be a year, or 0 for every year |
| 3 | `catalog-file` | `catalog.json`, if written, is `{"entries": [...]}` with each entry `{id, name, access_method, updated, records, version}` | catalog.json holds an entry that is not {id, name, access_method, updated, records, version}: {'id': 6} |
| 4 | `ledger` | The call ledger `.ledger/calls.jsonl` is readable, one call per line | the call ledger is broken: ledger line 23 is not JSON |
| 5 | `all-recorded` | Every source the filter matches is recorded | 2 matching sources are not recorded: src-012, src-024 |
| 6 | `no-extra` | No source the filter does not match is recorded | 1 recorded source does not match the filter: src-001 |
| 7 | `no-repeats` | No source is recorded twice | recorded more than once: src-006 (2 times) |
| 8 | `fields-cited` | Every field is `{value, cites}`, citing a successful `list_sources` or `get_source` call that returned exactly that value for that source, JSON type included (`"3"` is not `3`) | 6 fields are not cited rightly: src-006.name: 'Hospital Bed Capacity' is not 'Hospital Bed Capac…', what call-0001 returned; … |
| 9 | `values-current` | Every rightly cited value is the source's current value in `catalog_truth` | 6 fields are not current: src-012.updated: 2016 is what call-0001 returned, but the source's current updated is 2019; … |
| 10 | `total-exact` | The submitted total is the number of sources the filter matches | total 7 is not the true count 8 |

A field fails at most one of 8 and 9: a citation that does not hold is never
also judged for being current.

### How it is scored

- **Valid** only when all 10 checks hold, and then the score is 1.0.
- **Score 0** when any of checks 1 to 4 fails.
- **Otherwise** the score is cited × F1 × total factor, at most 0.99
  (`score_citations`). *cited* is the share of recorded fields that hold checks
  8 and 9. *F1* is over the recorded ids against the matching ones, so an extra
  or repeated entry lowers precision and a missing one recall. The *total
  factor* is 0.5 when the total is wrong. The task is about provenance, so a
  catalog with every source but stale values should score lower than one with
  fewer sources that are all cited correctly. A product of the citing work and
  the coverage gives that, and a fully cited catalog with a miscounted total
  keeps half its credit.
- **The message** names the first failing check, why it fails, and how many
  more fail, e.g. `all-recorded: 2 matching sources are not recorded: src-012,
  src-024 (+1 more)`. A valid verdict says `all 8 matching sources are
  recorded, every field cited`.
- **`details`** also holds `cited`, `f1`, `total_factor`, `bad_fields` (every
  failing field and why), `extra`, `missing`, `repeated`, `total` and
  `true_total`.

## Layout

```text
.
├── nanoagent.yaml   # manifest (a slimconfig ManifestConfig): id, runtime, permissions, tools, tasks
├── contract.py      # each tool's and task's typed input and output: slimconfig Output classes
├── README.md
├── LICENSE
├── pyproject.toml
├── uv.lock
├── .gitignore
├── .env             # environment variable NAMEs this plugin needs, never values
├── src/plugin/      # the MCP server: __main__.py, its IMPLEMENTATIONS, one module per tool, engine.py
│   └── fixtures/    # the mock catalog, catalog.json
├── tests/
│   ├── run_agent.sh # one agent run on OpenRouter: config, nanoagent plugin agent, verdict
│   ├── examples/    # the task's example arguments, <id>.json
│   └── results/     # one folder per agent run (git-ignored)
├── ui/              # how the page draws the outputs: renderers.js and renderers.css
├── product/         # the product page a catalog shows: product.yaml and icon.svg
└── verifier/        # deterministic verifier package
```

`contract.py` is the one place a value's shape is declared. Its `Output`
classes are the JSON Schemas the server offers and the agent sees, and every
input and output is built into its class on the way in and out: the server,
NanoAgent and the verifier all get typed values, never loose dicts. A tool
that fails raises; NanoAgent sees an MCP error.

To add a tool: add a `Tool` member, its input and output classes and its
`TOOLS` entry to `contract.py` (a snake_case name, classes named `...Input`
and `...Output`); write its implementation in `src/plugin/`, taking its input
and the workspace and returning its output; write its `verify_input` /
`verify_output` in `verifier/`, and tests for both. Then register it in
`src/plugin/__main__.py` (`IMPLEMENTATIONS`), `verifier/__init__.py` (`TOOLS`),
`nanoagent.yaml` (`tools`) and this README's Tools table; a task goes in its
Tasks table.

`LICENSE` stays the template's MIT license under your name, `.gitignore`
keeps its entries, and this README keeps its title and sections: NanoAgent refuses a plugin
that changes them (rule 10 of `nanoagent.plugin.manifest`). Renaming the
plugin means renaming it in `nanoagent.yaml` and this title together.

To add a task, add a `Task` member (a kebab-case id) and its `TASKS` input and
output classes to `contract.py`, and declare it in `nanoagent.yaml` with its `runner` (`tool`,
`agent` or `decide`) and a `reference` tool, or `null` if it has none. A `tool`
task's classes are its tool's; an `agent` task's agent ends by calling `submit`
with the task's output; a `decide` task's model only chooses, and every tool
argument and output field is an Enum or bool, or copied from a value of exactly
its type in the task's input or an earlier tool output. Then add the check of
its output, `verify_task(arguments, output, reference, workspace)`, to `TASKS`
in `verifier/__init__.py`. People use the plugin by chatting with its agent,
which runs its tasks and shows each output on the page (see `ui/`).

## Develop and run

```bash
uv sync --extra dev
uv run pytest && uv run ruff check . && uv lock --check
```

`tests/fakes.py` is a scripted agent that works the task through the server's
call path, so its calls land in the ledger as a real run's do.

Run the `cite-every-entry` task with `nanoagent plugin agent`: its run config
names this plugin, the task and its `filter` argument, e.g. domains `[health]`
with every other list empty and `updated_since: 0`. The agent uses
`list_sources`, `get_source`, `wait` and `record_entry`; NanoAgent runs
`catalog_truth` before the task and pins its output for the verifier.

To run the agent, with NanoAgent on `PATH` and an OpenRouter key:

```bash
export OPENROUTER_API_KEY=...          # or ENV_FILE=path/to/keys.env
tests/run_agent.sh                     # tests/examples/cite-every-entry.json
tests/run_agent.sh path/to/arguments.json
```

The script writes a NanoAgent run config (`PluginOpenRouterAgentConfig`), runs
`nanoagent plugin agent`, prints the verdict and exits 0 only when it is
valid. Each run goes to `tests/results/<time>/`, next to the config it ran as
`tests/results/<time>.yaml`: `result.json` (what the agent submitted),
`verdict.json`, `reference.json` (the pinned reference), `messages.json` (the
trajectory), `run.log` and `workspace/` with `.ledger/calls.jsonl`. `MODEL`,
`MAX_STEPS` and `TIMEOUT` override the defaults (`deepseek/deepseek-v4-flash`,
80 steps, 60 seconds per tool call).

Publishing checks every plugin rule: push the plugin to a public GitHub
repository and run `rush publish <server> <github-url>`.
