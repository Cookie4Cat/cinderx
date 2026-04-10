#!/bin/bash
# Full comparison: CPython baseline vs CPython + CinderX (baseline and optimized)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SAMPLES=${SAMPLES:-10}
WARMUP=${WARMUP:-3}
BENCHMARK=${BENCHMARK:-generators}
OPT_ENV_FILE=${OPT_ENV_FILE:-}
OPT_CONFIG_NAME=${OPT_CONFIG_NAME:-}

echo "========================================"
echo "  CinderX Performance Comparison"
echo "========================================"
echo "Samples: $SAMPLES"
echo "Warmup:  $WARMUP"
echo "Benchmark: $BENCHMARK"
echo "Optimization config: ${OPT_CONFIG_NAME:-stable}"
if [ -n "$OPT_ENV_FILE" ]; then
  echo "Optimization env file: $OPT_ENV_FILE"
fi
echo ""

# Prepare benchmark
echo "=== Preparing benchmark ==="
mkdir -p /root/benchmarks
python3 << PY
import urllib.request
import pathlib
import sys

sys.path.insert(0, "$SCRIPT_DIR")
from benchmark_harness import benchmark_module_path, resolve_benchmark

spec = resolve_benchmark("$BENCHMARK")
output_path = benchmark_module_path(pathlib.Path("/root/benchmarks"), "$BENCHMARK")
output_path.parent.mkdir(parents=True, exist_ok=True)

if not output_path.exists():
    url = spec.benchmark_url
    print(f"Downloading {url}...")
    urllib.request.urlretrieve(url, output_path)
    print(f"✓ Saved to {output_path}")
else:
    print(f"✓ Benchmark already exists at {output_path}")

shim_path = output_path.parent / "pyperf.py"
if not shim_path.exists():
    shim_path.write_text(
        "import time\\n"
        "def perf_counter(): return time.perf_counter()\\n"
        "class Runner:\\n"
        "    def __init__(self, *a, **k): pass\\n"
        "    def bench_time_func(self, *a, **k): pass\\n",
        encoding="utf-8",
    )
    print(f"✓ pyperf shim written to {shim_path}")
else:
    print(f"✓ pyperf shim already exists at {shim_path}")
PY

echo ""

# Test 1: CPython baseline
echo "========================================"
echo "  Test 1: CPython Baseline"
echo "========================================"
BENCHMARK="$BENCHMARK" /scripts/test-baseline.sh 2>&1 | tee /tmp/baseline.txt

echo ""

# Test 2: CinderX (no optimization)
echo "========================================"
echo "  Test 2: CinderX (no optimization)"
echo "========================================"
BENCHMARK="$BENCHMARK" ENABLE_OPTIMIZATION=0 /scripts/test-cinderx.sh 2>&1 | tee /tmp/cinderx-baseline.txt

echo ""

# Test 3: CinderX (with optimization)
echo "========================================"
echo "  Test 3: CinderX (optimized)"
echo "========================================"
BENCHMARK="$BENCHMARK" ENABLE_OPTIMIZATION=1 OPT_ENV_FILE="$OPT_ENV_FILE" OPT_CONFIG_NAME="$OPT_CONFIG_NAME" /scripts/test-cinderx.sh 2>&1 | tee /tmp/cinderx-optimized.txt

echo ""

# Compare results
echo "========================================"
echo "  COMPARISON"
echo "========================================"

export SAMPLES WARMUP BENCHMARK OPT_ENV_FILE OPT_CONFIG_NAME
python3 << 'PY'
import os
import re
import sys

sys.path.insert(0, "/scripts")
from benchmark_harness import (
    comparison_results_path,
    default_opt_env_file,
    opt_config_name,
    results_root,
)

def extract_time(filename, pattern="Result"):
    with open(filename) as f:
        content = f.read()
    # Accept both "Pattern: X.XXXXXXs" and "Pattern (extra): X.XXXXXXs".
    match = re.search(rf'{pattern}(?:\s+\([^)]*\))?:\s+([\d.]+)s', content)
    if match:
        return float(match.group(1))
    return None

baseline = extract_time('/tmp/baseline.txt', 'Baseline Result')
cinderx_baseline = extract_time('/tmp/cinderx-baseline.txt', 'CinderX Result')
cinderx_optimized = extract_time('/tmp/cinderx-optimized.txt', 'CinderX Result')

if baseline is not None:
    print(f"CPython Baseline:        {baseline:.6f}s")
if cinderx_baseline is not None:
    print(f"CinderX (no opt):        {cinderx_baseline:.6f}s")
if cinderx_optimized is not None:
    print(f"CinderX (optimized):     {cinderx_optimized:.6f}s")
print()

if baseline and cinderx_baseline:
    speedup_base = baseline / cinderx_baseline
    delta_base = (speedup_base - 1.0) * 100
    print(f"Speedup (CinderX):       {speedup_base:.4f}x ({delta_base:+.2f}%)")

if baseline and cinderx_optimized:
    speedup_opt = baseline / cinderx_optimized
    delta_opt = (speedup_opt - 1.0) * 100
    print(f"Speedup (CinderX+opt):   {speedup_opt:.4f}x ({delta_opt:+.2f}%)")

if cinderx_baseline and cinderx_optimized:
    speedup_vs_cinderx = cinderx_baseline / cinderx_optimized
    delta_vs_cinderx = (speedup_vs_cinderx - 1.0) * 100
    print(f"Optimization benefit:    {speedup_vs_cinderx:.4f}x ({delta_vs_cinderx:+.2f}%)")

# Save results
import json
from datetime import datetime

results = {
    "timestamp": datetime.now().isoformat(),
    "samples": int(os.environ["SAMPLES"]),
    "warmup": int(os.environ["WARMUP"]),
    "baseline": baseline,
    "cinderx_baseline": cinderx_baseline,
    "cinderx_optimized": cinderx_optimized,
}

if baseline and cinderx_baseline:
    results["speedup_cinderx"] = baseline / cinderx_baseline
if baseline and cinderx_optimized:
    results["speedup_cinderx_optimized"] = baseline / cinderx_optimized

benchmark = os.environ.get("BENCHMARK", "generators")
enable_optimization = True
opt_env_file = os.environ.get("OPT_ENV_FILE") or str(default_opt_env_file(benchmark))
config_name = os.environ.get("OPT_CONFIG_NAME") or opt_config_name(opt_env_file, enable_optimization)
output_path = comparison_results_path(results_root(), benchmark, config_name)
output_path.parent.mkdir(parents=True, exist_ok=True)

with open(output_path, "w") as f:
    json.dump(results, f, indent=2)
    print(f"\nResults saved to {output_path}")
PY

echo ""
echo "========================================"
