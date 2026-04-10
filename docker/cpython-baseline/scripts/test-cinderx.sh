#!/bin/bash
# Test CPython + CinderX performance
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SAMPLES=${SAMPLES:-10}
WARMUP=${WARMUP:-3}
BENCHMARK=${BENCHMARK:-generators}
ENABLE_OPTIMIZATION=${ENABLE_OPTIMIZATION:-0}
OPT_ENV_FILE=${OPT_ENV_FILE:-}
OPT_CONFIG_NAME=${OPT_CONFIG_NAME:-}

echo "=== CPython + CinderX Test ==="
echo "Benchmark: $BENCHMARK"
echo "Samples: $SAMPLES, Warmup: $WARMUP"
echo "Enable optimization: $ENABLE_OPTIMIZATION"
echo ""

export SCRIPT_DIR
eval "$(python3 <<'PY'
import glob
import os
import sys

sys.path.insert(0, os.environ["SCRIPT_DIR"])
from benchmark_harness import cinderx_wheel_glob

matches = sorted(glob.glob(str(cinderx_wheel_glob())))
if not matches:
    raise SystemExit("no CinderX wheel found under /dist")
print(f'CINDERX_WHEEL="{matches[-1]}"')
PY
)"

export BENCHMARK ENABLE_OPTIMIZATION OPT_ENV_FILE OPT_CONFIG_NAME
eval "$(python3 <<'PY'
import os
import sys

sys.path.insert(0, os.environ["SCRIPT_DIR"])
from benchmark_harness import (
    default_opt_env_file,
    load_opt_env_file,
    opt_config_name,
)

enabled = os.environ["ENABLE_OPTIMIZATION"] not in ("", "0")
env = {}
resolved_env_file = ""
config_name = opt_config_name(os.environ.get("OPT_ENV_FILE") or None, enabled)
if enabled:
    candidate = os.environ.get("OPT_ENV_FILE") or str(default_opt_env_file(os.environ["BENCHMARK"]))
    resolved_env_file = candidate
    env = load_opt_env_file(candidate)
    if os.environ.get("OPT_CONFIG_NAME"):
        config_name = os.environ["OPT_CONFIG_NAME"]

print(f'export OPT_CONFIG_NAME_RESOLVED="{config_name}"')
print(f'export OPT_ENV_FILE_RESOLVED="{resolved_env_file}"')
for key, value in env.items():
    print(f'export {key}="{value}"')
PY
)"

python3 - <<PY
import importlib.util
import subprocess
import sys

if importlib.util.find_spec("cinderx") is None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "$CINDERX_WHEEL"])
PY

# Run benchmark with CinderX enabled
export SAMPLES WARMUP
python3 << PY
import os
import sys
import time
import statistics

samples = int(os.environ["SAMPLES"])
warmup = int(os.environ["WARMUP"])

# Import and enable CinderX
import cinderx
import cinderx.jit as jit
jit.enable()

print(f"CinderX version: {cinderx.__version__ if hasattr(cinderx, '__version__') else 'unknown'}")
print(f"JIT enabled: {jit.is_enabled()}")

opt_env = {
    key: value
    for key, value in os.environ.items()
    if key.startswith("PYTHONJIT_ARM_")
}
if opt_env:
    print(f"Optimization config: {os.environ.get('OPT_CONFIG_NAME_RESOLVED', 'unknown')}")
    if os.environ.get("OPT_ENV_FILE_RESOLVED"):
        print(f"Optimization env file: {os.environ['OPT_ENV_FILE_RESOLVED']}")
    for key in sorted(opt_env):
        print(f"Optimization enabled: {key}={opt_env[key]}")

sys.path.insert(0, "$SCRIPT_DIR")
from benchmark_harness import load_benchmark, resolve_benchmark

spec = resolve_benchmark("$BENCHMARK")
module, bench = load_benchmark("/root/benchmarks", "$BENCHMARK")
bench_args = spec.bench_args

# Warmup
print(f"\nWarming up ({warmup} runs)...")
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

opt_status = " (optimized)" if $ENABLE_OPTIMIZATION else ""
print(f"\nCinderX Result{opt_status}: {avg:.6f}s ± {stdev:.6f}s")
PY
