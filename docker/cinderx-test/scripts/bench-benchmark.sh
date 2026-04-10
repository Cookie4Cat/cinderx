#!/bin/bash
# Run a benchmark from /root/benchmarks/<module_dir>/run_benchmark.py
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BENCHMARK=${BENCHMARK:-generators}
SAMPLES=${SAMPLES:-10}
WARMUP=${WARMUP:-3}

echo "=== $BENCHMARK benchmark ==="
echo "Samples: $SAMPLES, Warmup: $WARMUP"
echo ""

export SCRIPT_DIR BENCHMARK SAMPLES WARMUP
python3 << 'PY'
import os
import statistics
import sys
import time

sys.path.insert(0, os.environ["SCRIPT_DIR"])
from benchmark_harness import benchmark_root, load_benchmark, resolve_benchmark

benchmark = os.environ["BENCHMARK"]
samples = int(os.environ["SAMPLES"])
warmup = int(os.environ["WARMUP"])

spec = resolve_benchmark(benchmark)
_, bench = load_benchmark(benchmark_root(), benchmark)
bench_args = spec.bench_args

print(f"Warming up ({warmup} runs)...")
for _ in range(warmup):
    bench(*bench_args)

print(f"\nMeasuring ({samples} runs)...")
times = []
for i in range(samples):
    start = time.perf_counter()
    bench(*bench_args)
    end = time.perf_counter()
    elapsed = end - start
    times.append(elapsed)
    print(f"  Run {i+1:2d}: {elapsed:.6f}s")

avg = statistics.mean(times)
stdev = statistics.stdev(times) if len(times) > 1 else 0.0
print(f"\nResult: {avg:.6f}s ± {stdev:.6f}s")
PY
