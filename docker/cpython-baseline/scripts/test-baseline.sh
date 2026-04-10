#!/bin/bash
# Test CPython baseline performance (no CinderX)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SAMPLES=${SAMPLES:-10}
WARMUP=${WARMUP:-3}
BENCHMARK=${BENCHMARK:-generators}

echo "=== CPython Baseline Test (no CinderX) ==="
echo "Benchmark: $BENCHMARK"
echo "Samples: $SAMPLES, Warmup: $WARMUP"
echo ""

/scripts/prepare-stock-cpython.sh

export SCRIPT_DIR
eval "$(python3 <<'PY'
import os
import sys

sys.path.insert(0, os.environ["SCRIPT_DIR"])
from benchmark_harness import stock_cpython_python, stock_cpython_runtime_env

print(f'STOCK_CPYTHON_PYTHON="{stock_cpython_python()}"')
print(f'export PYTHON_JIT="{stock_cpython_runtime_env()["PYTHON_JIT"]}"')
PY
)"

# Run benchmark with stock CPython JIT enabled, without importing cinderx.
export SAMPLES WARMUP
"$STOCK_CPYTHON_PYTHON" << PY
import os
import sys
import time
import statistics

samples = int(os.environ["SAMPLES"])
warmup = int(os.environ["WARMUP"])

print(f"Stock CPython executable: {sys.executable}")
print(f"JIT available: {hasattr(sys, '_jit') and sys._jit.is_available()}")
print(f"JIT enabled: {hasattr(sys, '_jit') and sys._jit.is_enabled()}")

sys.path.insert(0, "$SCRIPT_DIR")
from benchmark_harness import load_benchmark, resolve_benchmark

spec = resolve_benchmark("$BENCHMARK")
module, bench = load_benchmark("/root/benchmarks", "$BENCHMARK")
bench_args = spec.bench_args

# Warmup
print(f"Warming up ({warmup} runs)...")
for _ in range(warmup):
    bench(*bench_args)

# Measure
print(f"\nMeasuring ({samples} runs)...")
times = []
for i in range(samples):
    start = time.perf_counter()
    bench(*bench_args)
    end = time.perf_counter()
    elapsed = end - start
    times.append(elapsed)
    print(f"  Run {i+1:2d}: {elapsed:.6f}s")

# Calculate statistics
avg = statistics.mean(times)
stdev = statistics.stdev(times) if len(times) > 1 else 0.0

print(f"\nBaseline Result: {avg:.6f}s ± {stdev:.6f}s")
PY
