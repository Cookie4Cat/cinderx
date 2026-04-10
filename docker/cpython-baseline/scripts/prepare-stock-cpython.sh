#!/bin/bash
# Build a stock CPython interpreter with experimental JIT enabled.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export SCRIPT_DIR

eval "$(python3 <<'PY'
import os
import sys

sys.path.insert(0, os.environ["SCRIPT_DIR"])
from benchmark_harness import (
    stock_cpython_configure_args,
    stock_cpython_python,
    stock_cpython_runtime_env,
    stock_cpython_source_root,
)

print(f'STOCK_CPYTHON_SOURCE="{stock_cpython_source_root()}"')
print(f'STOCK_CPYTHON_PYTHON="{stock_cpython_python()}"')
print(f'STOCK_CPYTHON_JIT_ENV="{stock_cpython_runtime_env()["PYTHON_JIT"]}"')
print("STOCK_CPYTHON_CONFIGURE_ARGS=(")
for arg in stock_cpython_configure_args():
    print(f'  "{arg}"')
print(")")
PY
)"

if [ ! -f "$STOCK_CPYTHON_SOURCE/configure" ]; then
  echo "error: missing CPython source mount at $STOCK_CPYTHON_SOURCE" >&2
  echo "hint: set CPYTHON_ROOT to your stock CPython checkout before starting docker compose" >&2
  exit 1
fi

if [ -x "$STOCK_CPYTHON_PYTHON" ]; then
  if PYTHON_JIT="$STOCK_CPYTHON_JIT_ENV" "$STOCK_CPYTHON_PYTHON" - <<'PY'
import sys
raise SystemExit(0 if hasattr(sys, "_jit") and sys._jit.is_available() and sys._jit.is_enabled() else 1)
PY
  then
    echo "✓ Reusing existing stock CPython JIT build at $STOCK_CPYTHON_PYTHON"
    exit 0
  fi
fi

BUILD_ROOT="/tmp/cpython-jit-build"
rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT"
cp -a "$STOCK_CPYTHON_SOURCE"/. "$BUILD_ROOT"/

cd "$BUILD_ROOT"
echo "=== Building stock CPython with experimental JIT ==="
echo "Source:  $STOCK_CPYTHON_SOURCE"
echo "Prefix:  $(dirname "$(dirname "$STOCK_CPYTHON_PYTHON")")"
echo "Config:  ${STOCK_CPYTHON_CONFIGURE_ARGS[*]}"
echo ""

"${STOCK_CPYTHON_CONFIGURE_ARGS[@]}"
make -j"${CPYTHON_BUILD_JOBS:-2}"
make install

PYTHON_JIT="$STOCK_CPYTHON_JIT_ENV" "$STOCK_CPYTHON_PYTHON" - <<'PY'
import sys

print("version", sys.version)
print("jit_available", hasattr(sys, "_jit") and sys._jit.is_available())
print("jit_enabled", hasattr(sys, "_jit") and sys._jit.is_enabled())
if not (hasattr(sys, "_jit") and sys._jit.is_available() and sys._jit.is_enabled()):
    raise SystemExit("stock CPython JIT build verification failed")
PY
