#!/bin/bash
# Test stock CPython JIT with pyperformance.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WARMUP=${WARMUP:-3}
BENCHMARK=${BENCHMARK:-mdp}
OUTPUT_FILE=${OUTPUT_FILE:-/tmp/pyperformance-baseline.json}
PYPERFORMANCE_TMP="$(mktemp -d /tmp/pyperformance.XXXXXX)"
trap 'rm -rf "$PYPERFORMANCE_TMP"' EXIT

echo "=== CPython Baseline pyperformance ==="
echo "Benchmark selector: $BENCHMARK"
echo "Warmup: $WARMUP"
echo "Output: $OUTPUT_FILE"

/scripts/prepare-stock-cpython.sh

export SCRIPT_DIR BENCHMARK WARMUP OUTPUT_FILE
eval "$(python3 <<'PY'
import os
import sys

sys.path.insert(0, os.environ["SCRIPT_DIR"])
from benchmark_harness import (
    pyperformance_benchmark_filter,
    pyperformance_source_root,
    stock_cpython_python,
    stock_cpython_runtime_env,
)

print(f'STOCK_CPYTHON_PYTHON="{stock_cpython_python()}"')
print(f'export PYTHON_JIT="{stock_cpython_runtime_env()["PYTHON_JIT"]}"')
print(f'export BENCHMARK_FILTER="{pyperformance_benchmark_filter(os.environ["BENCHMARK"])}"')
print(f'export PYPERFORMANCE_ROOT_RESOLVED="{pyperformance_source_root()}"')
PY
)"

cp -a "$PYPERFORMANCE_ROOT_RESOLVED"/. "$PYPERFORMANCE_TMP"/
"$STOCK_CPYTHON_PYTHON" -m pip install --quiet "$PYPERFORMANCE_TMP" 2>&1 | grep -v notice | tail -1 || true

PYTHON_JIT="$PYTHON_JIT" "$STOCK_CPYTHON_PYTHON" -m pyperformance run \
  --debug-single-value \
  --warmups "$WARMUP" \
  -b "$BENCHMARK_FILTER" \
  -o "$OUTPUT_FILE"

PYTHON_JIT="$PYTHON_JIT" "$STOCK_CPYTHON_PYTHON" <<'PY'
import os
import pyperf

suite = pyperf.BenchmarkSuite.load(os.environ["OUTPUT_FILE"])
bench = suite.get_benchmarks()[0]
print(f"\nBaseline Result ({bench.get_name()}): {bench.mean():.6f}s")
print(f"Results saved to {os.environ['OUTPUT_FILE']}")
PY
