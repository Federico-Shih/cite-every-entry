#!/usr/bin/env bash
# Run this plugin's agent task with NanoAgent on OpenRouter, and print its verdict.
#
#   tests/run_agent.sh [arguments.json]
#
# arguments.json defaults to tests/examples/<plugin-id>.json. OPENROUTER_API_KEY comes from the environment,
# or from the file ENV_FILE names (KEY=value lines); this plugin's own .env lists names only.
# Each run goes to tests/results/<time>/ (ignored), next to the config it ran as tests/results/<time>.yaml:
# result.json, verdict.json, reference.json, messages.json, run.log and workspace/.
#
# Overrides: NANOAGENT (the command to run, default nanoagent from PATH),
# MODEL (an OpenRouter model id), MAX_STEPS, TIMEOUT (seconds per tool call), ENV_FILE.
# Exits 0 only when the verifier judged the run valid. It lives in tests/ because NanoAgent's layout rule
# allows no other file at the plugin's top level.
set -euo pipefail

tests="$(cd "$(dirname "$0")" && pwd)"
here="$(dirname "$tests")"
[[ -f "$here/nanoagent.yaml" ]] || { echo "no nanoagent.yaml in $here" >&2; exit 2; }
id="$(sed -n 's/^id: *//p' "$here/nanoagent.yaml")"
default="$tests/examples/$id.json"
arguments="$(cd "$(dirname "${1:-$default}")" && pwd)/$(basename "${1:-$default}")"
read -r -a nanoagent <<< "${NANOAGENT:-nanoagent}"
model="${MODEL:-deepseek/deepseek-v4-flash}"

[[ -f "$arguments" ]] || { echo "no arguments file: $arguments" >&2; exit 2; }
command -v "${nanoagent[0]}" > /dev/null || { echo "no ${nanoagent[0]} on PATH: see 'Develop and run' in $here/README.md (or set NANOAGENT)" >&2; exit 2; }
if [[ -n "${ENV_FILE:-}" ]]; then
  [[ -f "$ENV_FILE" ]] || { echo "no ENV_FILE: $ENV_FILE" >&2; exit 2; }
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi
# NanoAgent hands the plugin its own workspace; never pass one through.
unset NANOAGENT_WORKSPACE
[[ -n "${OPENROUTER_API_KEY:-}" ]] || { echo "OPENROUTER_API_KEY is not set: export it, or set ENV_FILE to a file that sets it" >&2; exit 2; }

runs="$tests/results"
home="$runs/$(date +%Y%m%d-%H%M%S)"
config="$home.yaml"
mkdir -p "$runs"
cat > "$config" <<EOF
_ > nanoagent.cli.plugin.PluginOpenRouterAgentConfig:
plugin: $here
task: $id
arguments: $arguments
inputs: []
timeout: ${TIMEOUT:-60.0}
llm > nanoagent.llm.openrouter.OpenRouterConfig:
  model: $model
  max_tokens: null
  temperature: 0.0
  max_attempts: 3
  read_timeout: 120.0
  input_price: 0.0
  output_price: 0.0
harness > nanoagent.harness.nanoagent.NanoAgentConfig:
  max_steps: ${MAX_STEPS:-80}
  cost_limit: null
  token_limit: null
  context_window: null
  hooks: []
  skills: null
  context_files: []
  events: null
EOF

echo "running $id with $model -> $home"
status=0
"${nanoagent[@]}" plugin agent "config=$config" "home=$home" || status=$?
if [[ -f "$home/verdict.json" ]]; then
  echo "--- verdict ($home/verdict.json)"
  cat "$home/verdict.json"
fi
exit "$status"
