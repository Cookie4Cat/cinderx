#!/bin/bash
# Build CinderX wheel for ARM64 Linux
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
CPU_JOBS="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo 4)"
MEM_JOBS="$(awk '/MemAvailable:/ {jobs = int($2 / 2097152); if (jobs < 1) jobs = 1; print jobs; exit}' /proc/meminfo 2>/dev/null || echo 1)"
if (( MEM_JOBS < CPU_JOBS )); then
  DEFAULT_BUILD_JOBS="$MEM_JOBS"
else
  DEFAULT_BUILD_JOBS="$CPU_JOBS"
fi
BUILD_JOBS="${CINDERX_BUILD_JOBS:-$DEFAULT_BUILD_JOBS}"
PARALLEL_LEVEL="${CMAKE_BUILD_PARALLEL_LEVEL:-$BUILD_JOBS}"

echo "=== Building CinderX ARM64 wheel ==="
echo "Project root: $PROJECT_ROOT"
echo ""

# Check if already built
if ls "$PROJECT_ROOT"/dist/cinderx-*-linux_aarch64.whl 1> /dev/null 2>&1; then
  echo "Found existing wheel:"
  ls -lh "$PROJECT_ROOT"/dist/cinderx-*-linux_aarch64.whl
  echo ""
  read -p "Rebuild? (y/N) " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Using existing wheel"
    exit 0
  fi
fi

# Build using Docker
docker run --rm --platform linux/arm64 \
  -v "$PROJECT_ROOT:/cinderx" \
  -w /cinderx \
  python:3.14-slim bash -c '
    set -e

    echo "Installing build dependencies..."
    apt-get update -qq > /dev/null 2>&1
    apt-get install -y -qq build-essential cmake git > /dev/null 2>&1
    pip install --quiet build 2>&1 | grep -v notice

    echo ""
    echo "Building wheel with '"$PARALLEL_LEVEL"' parallel jobs..."
    export CMAKE_BUILD_PARALLEL_LEVEL='"$PARALLEL_LEVEL"'
    export CINDERX_BUILD_JOBS='"$BUILD_JOBS"'
    python -m build --wheel 2>&1 | tail -5

    echo ""
    echo "✓ Build complete:"
    ls -lh dist/cinderx-*-linux_aarch64.whl
  '

echo ""
echo "=== Build successful ==="
echo "Wheel: $PROJECT_ROOT/dist/cinderx-*-linux_aarch64.whl"
