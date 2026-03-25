#!/bin/bash
# Run a CinderX pyperformance benchmark inside the container.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BENCHMARK=${BENCHMARK:-mdp}
WARMUP=${WARMUP:-3}
AUTOJIT=${PYTHONJITAUTO:-10}
OPT_ENV_FILE=${OPT_ENV_FILE:-}
OPT_CONFIG_NAME=${OPT_CONFIG_NAME:-}
OUTPUT_FILE=${OUTPUT_FILE:-/tmp/pyperformance-cinderx.json}

echo "=== CinderX pyperformance ==="
echo "Benchmark selector: $BENCHMARK"
echo "Warmup: $WARMUP"
echo "AutoJIT: $AUTOJIT"
echo "Output: $OUTPUT_FILE"

export SCRIPT_DIR BENCHMARK OPT_ENV_FILE OPT_CONFIG_NAME AUTOJIT OUTPUT_FILE
eval "$(python3 <<'PY'
import os
import sys

sys.path.insert(0, os.environ["SCRIPT_DIR"])
from benchmark_harness import (
    default_opt_env_file,
    load_opt_env_file,
    opt_config_name,
    pyperformance_benchmark_filter,
    pyperformance_hook_root,
)

path = os.environ.get("OPT_ENV_FILE") or str(default_opt_env_file(os.environ["BENCHMARK"]))
config_name = os.environ.get("OPT_CONFIG_NAME") or opt_config_name(path, True)
env = load_opt_env_file(path)
benchmark_filter = pyperformance_benchmark_filter(os.environ["BENCHMARK"])
hook_root = pyperformance_hook_root()

print(f'export BENCHMARK_FILTER="{benchmark_filter}"')
print(f'export PYPERF_HOOK_ROOT_RESOLVED="{hook_root}"')
print(f'export OPT_ENV_FILE_RESOLVED="{path}"')
print(f'export OPT_CONFIG_NAME_RESOLVED="{config_name}"')
for key, value in env.items():
    print(f'export {key}="{value}"')
PY
)"

python3 -m pip install --quiet -e /pyperformance 2>&1 | grep -v notice | tail -1 || true

env \
  PYTHONJITDISABLE=1 \
  CINDERX_WORKER_PYTHONJITAUTO="$AUTOJIT" \
  PYTHONJITHUGEPAGES=0 \
  PYTHONPATH="$PYPERF_HOOK_ROOT_RESOLVED${PYTHONPATH:+:$PYTHONPATH}" \
  $(python3 <<'PY'
import os

for key, value in sorted(os.environ.items()):
    if key.startswith("PYTHONJIT_ARM_"):
        print(f"{key}={value}")
PY
) \
  python3 -m pyperformance run \
    --debug-single-value \
    --warmups "$WARMUP" \
    -b "$BENCHMARK_FILTER" \
    --inherit-environ PYTHONPATH,PYTHONJITDISABLE,CINDERX_WORKER_PYTHONJITAUTO,PYTHONJITHUGEPAGES \
    -o "$OUTPUT_FILE"

python3 <<'PY'
import os
import pyperf

suite = pyperf.BenchmarkSuite.load(os.environ["OUTPUT_FILE"])
bench = suite.get_benchmarks()[0]
print(f"\nCinderX Result ({bench.get_name()}): {bench.mean():.6f}s")
print(f"Results saved to {os.environ['OUTPUT_FILE']}")
PY
