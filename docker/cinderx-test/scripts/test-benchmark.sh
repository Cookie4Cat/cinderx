#!/bin/bash
# Run full benchmark comparison: baseline vs optimized
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BENCHMARK=${BENCHMARK:-generators}
SAMPLES=${SAMPLES:-10}
WARMUP=${WARMUP:-3}
OPT_ENV_FILE=${OPT_ENV_FILE:-}
OPT_CONFIG_NAME=${OPT_CONFIG_NAME:-}

echo "========================================"
echo "  Benchmark Comparison"
echo "========================================"
echo "Benchmark: $BENCHMARK"
echo "Samples:   $SAMPLES"
echo "Warmup:    $WARMUP"
echo ""

export SCRIPT_DIR BENCHMARK OPT_ENV_FILE OPT_CONFIG_NAME
eval "$(python3 <<'PY'
import os
import sys

sys.path.insert(0, os.environ["SCRIPT_DIR"])
from benchmark_harness import default_opt_env_file, load_opt_env_file, opt_config_name

path = os.environ.get("OPT_ENV_FILE") or str(default_opt_env_file(os.environ["BENCHMARK"]))
config_name = os.environ.get("OPT_CONFIG_NAME") or opt_config_name(path, True)
env = load_opt_env_file(path)

print(f'export OPT_ENV_FILE_RESOLVED="{path}"')
print(f'export OPT_CONFIG_NAME_RESOLVED="{config_name}"')
for key, value in env.items():
    print(f'export {key}="{value}"')
PY
)"

echo "=== BASELINE (no optimization) ==="
PYTHONJIT=1 \
PYTHONJITAUTO=50 \
BENCHMARK="$BENCHMARK" \
SAMPLES="$SAMPLES" \
WARMUP="$WARMUP" \
/scripts/bench-benchmark.sh 2>&1 | tee /tmp/baseline.txt

echo ""

echo "=== OPTIMIZED (${OPT_CONFIG_NAME_RESOLVED}) ==="
env \
  PYTHONJIT=1 \
  PYTHONJITAUTO=50 \
  BENCHMARK="$BENCHMARK" \
  SAMPLES="$SAMPLES" \
  WARMUP="$WARMUP" \
  OPT_ENV_FILE="$OPT_ENV_FILE_RESOLVED" \
  OPT_CONFIG_NAME="$OPT_CONFIG_NAME_RESOLVED" \
  $(python3 <<'PY'
import os

for key, value in sorted(os.environ.items()):
    if key.startswith("PYTHONJIT_ARM_"):
        print(f"{key}={value}")
PY
) \
  /scripts/bench-benchmark.sh 2>&1 | tee /tmp/optimized.txt

echo ""
echo "========================================"
echo "  COMPARISON"
echo "========================================"

export SAMPLES WARMUP BENCHMARK OPT_ENV_FILE OPT_CONFIG_NAME
python3 << 'PY'
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.environ["SCRIPT_DIR"])
from benchmark_harness import comparison_results_path, default_opt_env_file, opt_config_name, results_root


def extract_time(filename):
    with open(filename) as f:
        content = f.read()
    match = re.search(r"Result: ([\d.]+)s", content)
    if match:
        return float(match.group(1))
    return None


baseline = extract_time("/tmp/baseline.txt")
optimized = extract_time("/tmp/optimized.txt")

if baseline is None or optimized is None:
    raise SystemExit("failed to extract timing data")

speedup = baseline / optimized
delta = (speedup - 1.0) * 100

print(f"Baseline:  {baseline:.6f}s")
print(f"Optimized: {optimized:.6f}s")
print(f"Speedup:   {speedup:.4f}x")
print(f"Delta:     {delta:+.2f}%")

results = {
    "timestamp": datetime.now().isoformat(),
    "samples": int(os.environ["SAMPLES"]),
    "warmup": int(os.environ["WARMUP"]),
    "benchmark": os.environ["BENCHMARK"],
    "baseline": baseline,
    "optimized": optimized,
    "speedup": speedup,
    "delta_pct": delta,
}

opt_env_file = os.environ.get("OPT_ENV_FILE") or str(default_opt_env_file(os.environ["BENCHMARK"]))
config_name = os.environ.get("OPT_CONFIG_NAME") or opt_config_name(opt_env_file, True)
output_path = comparison_results_path(results_root(), os.environ["BENCHMARK"], config_name)
output_path.parent.mkdir(parents=True, exist_ok=True)
with open(output_path, "w") as f:
    json.dump(results, f, indent=2)

print(f"\nResults saved to {output_path}")
PY
