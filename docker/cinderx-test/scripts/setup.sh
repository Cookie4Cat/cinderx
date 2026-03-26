#!/bin/bash
# Setup cinderx and pyperformance in the container
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYPERFORMANCE_TMP="$(mktemp -d /tmp/pyperformance.XXXXXX)"
CINDERX_WHEEL_TMP="$(mktemp -d /tmp/cinderx-wheel.XXXXXX)"
CINDERX_WHEEL_CACHE_DIR=${CINDERX_WHEEL_CACHE_DIR:-/opt/cinderx-wheel-cache}
trap 'rm -rf "$PYPERFORMANCE_TMP" "$CINDERX_WHEEL_TMP"' EXIT

export SCRIPT_DIR
eval "$(python3 <<'PY'
import os
import sys

sys.path.insert(0, os.environ["SCRIPT_DIR"])
from benchmark_harness import cinderx_source_root

print(f'export CINDERX_SOURCE_ROOT_RESOLVED="{cinderx_source_root()}"')
PY
)"

echo "=== Installing cinderx ==="
mkdir -p "$CINDERX_WHEEL_CACHE_DIR"
PYTHONJITDISABLE=1 python3 -m pip install --quiet build 2>&1 | grep -v notice | tail -1 || true
(
  cd "$CINDERX_SOURCE_ROOT_RESOLVED"
  PYTHONJITDISABLE=1 CMAKE_BUILD_PARALLEL_LEVEL=1 CINDERX_BUILD_JOBS=1 python3 -m build --wheel --outdir "$CINDERX_WHEEL_TMP" 2>&1 | tail -5
)
cp "$CINDERX_WHEEL_TMP"/cinderx-*-linux_aarch64.whl "$CINDERX_WHEEL_CACHE_DIR"/
PYTHONJITDISABLE=1 pip3 install --quiet --no-deps "$CINDERX_WHEEL_CACHE_DIR"/cinderx-*-linux_aarch64.whl 2>&1 | grep -v notice | tail -1

echo "=== Installing pyperformance ==="
cp -a /pyperformance/. "$PYPERFORMANCE_TMP"/
PYTHONJITDISABLE=1 python3 -m pip install --quiet "$PYPERFORMANCE_TMP" 2>&1 | grep -v notice | tail -1 || true

echo "=== Verifying installation ==="
python3 << 'PY'
import cinderx
import cinderx.jit as jit
import pyperformance

if cinderx.get_import_error() is not None:
    raise SystemExit(f"failed to import _cinderx: {cinderx.get_import_error()!r}")
print(f"✓ cinderx import ok, initialized={cinderx.is_initialized()}")
print(f"✓ pyperformance available: {pyperformance.__file__}")
PY

echo ""
echo "=== Setup complete ==="
echo "Run '/scripts/smoke.sh' to verify JIT functionality"
echo "Run 'BENCHMARK=mdp /scripts/test-benchmark.sh' to run a pyperformance benchmark"
