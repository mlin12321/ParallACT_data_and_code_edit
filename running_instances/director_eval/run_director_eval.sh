#!/usr/bin/env bash
# Run the agent-director on a fixed random sample of ParallACT, grade it and
# summarize it. Every setting is a variable below; override any of them in the
# environment:
#
#   NUM_TASKS=5 SCENARIOS="oracle parallel_unaware" ./run_director_eval.sh
#   STEPS="grade summarize" ./run_director_eval.sh      # only those steps
#
# The run can be stopped and started again: finished bundles are skipped, and
# the budget ledger remembers what was spent.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

# --- what to run ---
SEED="${SEED:-20261127}"                 # fixes the sample
NUM_TASKS="${NUM_TASKS:-30}"             # instances drawn at most
CORPUS="${CORPUS:-v1,v2}"                # v1, v2 or both
FAMILY="${FAMILY:-contradictory,complementary}"
SCENARIOS="${SCENARIOS:-oracle}"         # see scenarios.py; oracle = one org, both requests
STEPS="${STEPS:-sample run grade summarize}"

# --- the agents ---
# Either a LiteLLM model the director's own agents call (needs its API key) ...
MODEL="${MODEL:-anthropic/claude-sonnet-5-5}"
export DIRECTOR_API_KEY_ENV="${DIRECTOR_API_KEY_ENV:-ANTHROPIC_API_KEY}"
# ... or a whole agent, e.g. Cursor over ACP (agents/cursor.json). It then names the run.
AGENT_JSON="${AGENT_JSON:-}"
LABEL="${LABEL:-}"                       # name of the run; default from MODEL or AGENT_JSON
export DIRECTOR_MAX_DEPTH="${DIRECTOR_MAX_DEPTH:-}"   # 1 = no sub-teams (a solo run)

# --- limits ---
BUDGET_USD="${BUDGET_USD:-40}"           # every turn of every run on this ledger, together
BUDGET_FILE="${BUDGET_FILE:-$REPO/.local/director_budget.json}"
COST_LIMIT="${COST_LIMIT:-5}"            # dollars one turn may spend
TURN_TIMEOUT="${TURN_TIMEOUT:-2700}"     # seconds one turn may take
# Dollars per million tokens, for an agent that reports no usage (Cursor): the
# driver then estimates tokens from the agents' events. An assumption, not a bill.
PRICE_IN="${PRICE_IN:-3}"
PRICE_OUT="${PRICE_OUT:-15}"
SCENARIO_CONCURRENCY="${SCENARIO_CONCURRENCY:-2}"
GRADE_JOBS="${GRADE_JOBS:-2}"
GRADE_STRATEGIES="${GRADE_STRATEGIES:-concat,git-merge}"

# --- where things are ---
export DIRECTOR_SDK="${DIRECTOR_SDK:-$REPO/../software-director-sdk}"
export DIRECTOR_EVAL_DRIVER="${DIRECTOR_EVAL_DRIVER:-$REPO/../DirectorEvalDriver}"
RUN_NAME="${RUN_NAME:-seed${SEED}_n${NUM_TASKS}}"
OUT="${OUT:-$REPO/.local/director_eval/$RUN_NAME}"

if [[ -n "$AGENT_JSON" ]]; then
    AGENT_JSON="$(realpath "$AGENT_JSON")"
    export DIRECTOR_AGENT_JSON="$AGENT_JSON"
    MODEL="${LABEL:-$(basename "$AGENT_JSON" .json)}"
fi
export DIRECTOR_BUDGET_FILE="$BUDGET_FILE" DIRECTOR_BUDGET_USD="$BUDGET_USD"
export DIRECTOR_COST_LIMIT="$COST_LIMIT" DIRECTOR_PRICE_IN="$PRICE_IN" DIRECTOR_PRICE_OUT="$PRICE_OUT"

mkdir -p "$OUT"
SAMPLE="$OUT/sample.txt"
SOLO=""; [[ "$DIRECTOR_MAX_DEPTH" == "1" ]] && SOLO="-solo"
HARNESS_MODEL="director${SOLO}__${MODEL##*/}"
SCENARIO_ARGS=(); for s in $SCENARIOS; do SCENARIO_ARGS+=(--scenario "$s"); done

{
    echo "run=$RUN_NAME harness_model=$HARNESS_MODEL seed=$SEED num=$NUM_TASKS corpus=$CORPUS"
    echo "scenarios=$SCENARIOS budget=\$$BUDGET_USD ($BUDGET_FILE) per_turn=\$$COST_LIMIT timeout=${TURN_TIMEOUT}s"
    echo "sdk=$(git -C "$DIRECTOR_SDK" rev-parse --short HEAD) driver=$(git -C "$DIRECTOR_EVAL_DRIVER" rev-parse --short HEAD) parallact=$(git -C "$REPO" rev-parse --short HEAD)"
} | tee "$OUT/settings.txt"

cd "$REPO"
for step in $STEPS; do
    case "$step" in
    sample)
        uv run python "$HERE/sample_instances.py" --seed "$SEED" --num "$NUM_TASKS" \
            --corpus "$CORPUS" --family "$FAMILY" --out "$SAMPLE"
        ;;
    run)
        for corpus in ${CORPUS//,/ }; do
            (cd running_instances/common && uv run python run.py --harness director --model "$MODEL" \
                --corpus "$corpus" --family both --instances-file "$SAMPLE" "${SCENARIO_ARGS[@]}" \
                --scenario-concurrency "$SCENARIO_CONCURRENCY" --timeout "$TURN_TIMEOUT" \
                --out "$OUT/runs/$corpus") 2>&1 | tee -a "$OUT/run.log"
        done
        ;;
    grade)
        for corpus in ${CORPUS//,/ }; do
            for folder in $( [[ $corpus == v1 ]] && echo "generated seeds" || echo "generated" ); do
                uv run python -m eval.grade --input-folder "dataset/$corpus/$folder" --family both \
                    --runs "$OUT/runs/$corpus" --out "$OUT/eval/$corpus" --harness-model "$HARNESS_MODEL" \
                    "${SCENARIO_ARGS[@]}" --strategies "$GRADE_STRATEGIES" --jobs "$GRADE_JOBS" \
                    2>&1 | tee -a "$OUT/grade.log"
            done
        done
        ;;
    summarize)
        uv run python "$HERE/summarize.py" --runs "$OUT/runs" --eval "$OUT/eval" \
            --harness-model "$HARNESS_MODEL" --ledger "$BUDGET_FILE" --out "$OUT/summary.json" \
            | tee "$OUT/summary.txt"
        ;;
    *) echo "unknown step: $step" >&2; exit 2 ;;
    esac
done
