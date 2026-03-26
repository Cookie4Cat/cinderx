#!/bin/bash
# Full comparison: CPython baseline vs CPython + CinderX.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WARMUP=${WARMUP:-3}
BENCHMARK=${BENCHMARK:-mdp}
OPT_ENV_FILE=${OPT_ENV_FILE:-}
OPT_CONFIG_NAME=${OPT_CONFIG_NAME:-}
BASELINE_OUTPUT=${BASELINE_OUTPUT:-/tmp/pyperformance-baseline.json}
CINDERX_BASELINE_OUTPUT=${CINDERX_BASELINE_OUTPUT:-/tmp/pyperformance-cinderx-baseline.json}
CINDERX_OPT_OUTPUT=${CINDERX_OPT_OUTPUT:-/tmp/pyperformance-cinderx-optimized.json}

echo "========================================"
echo "  CinderX Performance Comparison"
echo "========================================"
echo "Warmup:  $WARMUP"
echo "Benchmark: $BENCHMARK"
echo "Optimization config: ${OPT_CONFIG_NAME:-stable}"
if [ -n "$OPT_ENV_FILE" ]; then
  echo "Optimization env file: $OPT_ENV_FILE"
fi
echo ""

echo "========================================"
echo "  Test 1: CPython Baseline"
echo "========================================"
BENCHMARK="$BENCHMARK" WARMUP="$WARMUP" OUTPUT_FILE="$BASELINE_OUTPUT" /scripts/test-baseline.sh

echo ""
echo "========================================"
echo "  Test 2: CinderX (no optimization)"
echo "========================================"
BENCHMARK="$BENCHMARK" WARMUP="$WARMUP" ENABLE_OPTIMIZATION=0 OUTPUT_FILE="$CINDERX_BASELINE_OUTPUT" /scripts/test-cinderx.sh

echo ""
echo "========================================"
echo "  Test 3: CinderX (optimized)"
echo "========================================"
BENCHMARK="$BENCHMARK" WARMUP="$WARMUP" ENABLE_OPTIMIZATION=1 OPT_ENV_FILE="$OPT_ENV_FILE" OPT_CONFIG_NAME="$OPT_CONFIG_NAME" OUTPUT_FILE="$CINDERX_OPT_OUTPUT" /scripts/test-cinderx.sh

echo ""
echo "========================================"
echo "  COMPARISON"
echo "========================================"
python3 -m pyperformance compare "$BASELINE_OUTPUT" "$CINDERX_BASELINE_OUTPUT" || true
echo ""
python3 -m pyperformance compare "$BASELINE_OUTPUT" "$CINDERX_OPT_OUTPUT" || true

export BENCHMARK WARMUP OPT_ENV_FILE OPT_CONFIG_NAME BASELINE_OUTPUT CINDERX_BASELINE_OUTPUT CINDERX_OPT_OUTPUT
python3 <<'PY'
import json
import os
import pyperf
import sys
from datetime import datetime

sys.path.insert(0, "/scripts")
from benchmark_harness import (
    comparison_results_path,
    default_opt_env_file,
    opt_config_name,
    results_root,
)


def extract_time(filename):
    suite = pyperf.BenchmarkSuite.load(filename)
    return suite.get_benchmarks()[0].mean()


baseline = extract_time(os.environ["BASELINE_OUTPUT"])
cinderx_baseline = extract_time(os.environ["CINDERX_BASELINE_OUTPUT"])
cinderx_optimized = extract_time(os.environ["CINDERX_OPT_OUTPUT"])

print(f"CPython Baseline:        {baseline:.6f}s")
print(f"CinderX (no opt):        {cinderx_baseline:.6f}s")
print(f"CinderX (optimized):     {cinderx_optimized:.6f}s")
print()

print(f"Speedup (CinderX):       {baseline / cinderx_baseline:.4f}x")
print(f"Speedup (CinderX+opt):   {baseline / cinderx_optimized:.4f}x")
print(f"Optimization benefit:    {cinderx_baseline / cinderx_optimized:.4f}x")

results = {
    "timestamp": datetime.now().isoformat(),
    "warmup": int(os.environ["WARMUP"]),
    "benchmark": os.environ["BENCHMARK"],
    "baseline": baseline,
    "cinderx_baseline": cinderx_baseline,
    "cinderx_optimized": cinderx_optimized,
    "speedup_cinderx": baseline / cinderx_baseline,
    "speedup_cinderx_optimized": baseline / cinderx_optimized,
    "baseline_file": os.environ["BASELINE_OUTPUT"],
    "cinderx_baseline_file": os.environ["CINDERX_BASELINE_OUTPUT"],
    "cinderx_optimized_file": os.environ["CINDERX_OPT_OUTPUT"],
}

benchmark = os.environ["BENCHMARK"]
opt_env_file = os.environ.get("OPT_ENV_FILE")
if not opt_env_file:
    default_opt = default_opt_env_file(benchmark)
    opt_env_file = str(default_opt) if default_opt is not None else ""
config_name = os.environ.get("OPT_CONFIG_NAME") or opt_config_name(opt_env_file or None, True)
output_path = comparison_results_path(results_root(), benchmark, config_name)
output_path.parent.mkdir(parents=True, exist_ok=True)
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

print(f"\nResults saved to {output_path}")
PY
