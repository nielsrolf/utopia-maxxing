#!/usr/bin/env bash
# Launch all 25 ablation experiments (5 models × 5 conditions).
# Each batch of 5 models runs in parallel; 10-min pause between batches.
# Each experiment type gets its own top-level runs directory.

set -euo pipefail
cd "$(dirname "$0")"

GENS=20
CONCURRENCY=5

MODELS=(
    "gpt-5"
    "claude-sonnet-4-6"
    "moonshotai/kimi-k2-0905"
    "google/gemini-3.1-pro-preview"
    "qwen/qwen3.5-397b-a17b"
)
SHORTS=(gpt5 claude kimi gemini qwen)

log() { echo "[$(date '+%H:%M:%S')] $*"; }

launch() {
    local runs_dir="$1"; local name="$2"; shift 2
    mkdir -p "$runs_dir"
    log "Launching: $runs_dir/$name"
    nohup uv run python evolve.py "$@" --runs-dir "$runs_dir" --run-name "$name" --generations "$GENS" --concurrency "$CONCURRENCY" \
        > "${runs_dir}/${name}.log" 2>&1 &
    echo $!
}

# =============================================================================
# Batch 1: Path dependence (same setup as originals, different random seed)
# =============================================================================
log "=== BATCH 1: Path dependence ==="
PIDS=()
for i in "${!MODELS[@]}"; do
    launch "path_dependence_runs" "${SHORTS[$i]}" --model "${MODELS[$i]}"
    PIDS+=($!)
done
log "Waiting for batch 1 (${#PIDS[@]} runs)..."
for pid in "${PIDS[@]}"; do wait "$pid" || true; done
log "Batch 1 complete."

sleep 600  # 10-min cooldown

# =============================================================================
# Batch 2: Remove top seed (per-model ablated populations)
# =============================================================================
log "=== BATCH 2: Remove top seed ==="

# GPT-5's top seed is dario, Claude/Gemini/Qwen's top is utopia-lol, Kimi's top is archive
NO_TOP_SEED_DIRS=(
    "population_no_dario"       # gpt5
    "population_no_utopia_lol"  # claude
    "population_no_archive"     # kimi
    "population_no_utopia_lol"  # gemini
    "population_no_utopia_lol"  # qwen
)

PIDS=()
for i in "${!MODELS[@]}"; do
    launch "no_top_seed_runs" "${SHORTS[$i]}" --model "${MODELS[$i]}" --population-dir "${NO_TOP_SEED_DIRS[$i]}"
    PIDS+=($!)
done
log "Waiting for batch 2 (${#PIDS[@]} runs)..."
for pid in "${PIDS[@]}"; do wait "$pid" || true; done
log "Batch 2 complete."

sleep 600

# =============================================================================
# Batch 3: Generic prompt (no rubric dimensions)
# =============================================================================
log "=== BATCH 3: Generic prompt ==="
PIDS=()
for i in "${!MODELS[@]}"; do
    launch "prompt_generic_runs" "${SHORTS[$i]}" --model "${MODELS[$i]}" \
        --selection-prompt-file prompts/generic-selection.txt \
        --crossover-prompt-file prompts/generic-crossover.txt
    PIDS+=($!)
done
log "Waiting for batch 3 (${#PIDS[@]} runs)..."
for pid in "${PIDS[@]}"; do wait "$pid" || true; done
log "Batch 3 complete."

sleep 600

# =============================================================================
# Batch 4: Meaning-focused prompt
# =============================================================================
log "=== BATCH 4: Meaning prompt ==="
PIDS=()
for i in "${!MODELS[@]}"; do
    launch "prompt_meaning_runs" "${SHORTS[$i]}" --model "${MODELS[$i]}" \
        --selection-prompt-file prompts/meaning-selection.txt \
        --crossover-prompt-file prompts/meaning-crossover.txt
    PIDS+=($!)
done
log "Waiting for batch 4 (${#PIDS[@]} runs)..."
for pid in "${PIDS[@]}"; do wait "$pid" || true; done
log "Batch 4 complete."

sleep 600

# =============================================================================
# Batch 5: Space/digital minds prompt
# =============================================================================
log "=== BATCH 5: Space/digital prompt ==="
PIDS=()
for i in "${!MODELS[@]}"; do
    launch "prompt_space_runs" "${SHORTS[$i]}" --model "${MODELS[$i]}" \
        --selection-prompt-file prompts/space-selection.txt \
        --crossover-prompt-file prompts/space-crossover.txt
    PIDS+=($!)
done
log "Waiting for batch 5 (${#PIDS[@]} runs)..."
for pid in "${PIDS[@]}"; do wait "$pid" || true; done
log "Batch 5 complete."

log "=== ALL 25 ABLATION RUNS COMPLETE ==="
