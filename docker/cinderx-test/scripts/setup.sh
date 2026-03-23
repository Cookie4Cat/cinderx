#!/bin/bash
# Setup cinderx and dependencies in the container
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BENCHMARK=${BENCHMARK:-generators}

echo "=== Installing cinderx ==="
pip3 install --quiet /dist/cinderx-*-linux_aarch64.whl 2>&1 | grep -v notice | tail -1

echo "=== Preparing benchmark: $BENCHMARK ==="
# Download benchmark files manually (pip is broken in Python 3.14)
mkdir -p /root/benchmarks
export SCRIPT_DIR BENCHMARK
python3 << 'PY'
import urllib.request
import pathlib
import sys
import os

sys.path.insert(0, os.environ["SCRIPT_DIR"])
from benchmark_harness import benchmark_downloads, benchmark_module_path, benchmark_root, pyperf_shim_code

benchmark = os.environ["BENCHMARK"]
output_path = benchmark_module_path(benchmark_root(), benchmark)
output_path.parent.mkdir(parents=True, exist_ok=True)

for filename, url in benchmark_downloads(benchmark):
    target = output_path.parent / filename
    print(f"Downloading {url}...")
    urllib.request.urlretrieve(url, target)
    print(f"✓ Saved to {target}")

pyperf_path = pathlib.Path("/root/benchmarks/pyperf.py")
pyperf_path.write_text(pyperf_shim_code(), encoding="utf-8")
print(f"✓ Created pyperf shim at {pyperf_path}")

local_pyperf_path = output_path.parent / "pyperf.py"
local_pyperf_path.write_text(pyperf_shim_code(), encoding="utf-8")
print(f"✓ Created local pyperf shim at {local_pyperf_path}")
PY

echo "=== Verifying installation ==="
python3 << 'PY'
import cinderx
import cinderx.jit as jit

assert cinderx.is_initialized(), "cinderx not initialized"
print("✓ cinderx initialized and JIT enabled")
PY

echo ""
echo "=== Setup complete ==="
echo "Run '/scripts/smoke.sh' to verify JIT functionality"
echo "Run 'BENCHMARK=$BENCHMARK /scripts/test-benchmark.sh' to run benchmark comparison"
