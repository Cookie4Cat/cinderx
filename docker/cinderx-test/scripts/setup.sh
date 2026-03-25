#!/bin/bash
# Setup cinderx and pyperformance in the container
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Installing cinderx ==="
pip3 install --quiet /dist/cinderx-*-linux_aarch64.whl 2>&1 | grep -v notice | tail -1

echo "=== Installing pyperformance ==="
python3 -m pip install --quiet -e /pyperformance 2>&1 | grep -v notice | tail -1 || true

echo "=== Verifying installation ==="
python3 << 'PY'
import cinderx
import cinderx.jit as jit
import pyperformance

assert cinderx.is_initialized(), "cinderx not initialized"
print("✓ cinderx initialized and JIT enabled")
print(f"✓ pyperformance available: {pyperformance.__file__}")
PY

echo ""
echo "=== Setup complete ==="
echo "Run '/scripts/smoke.sh' to verify JIT functionality"
echo "Run 'BENCHMARK=mdp /scripts/test-benchmark.sh' to run a pyperformance benchmark"
