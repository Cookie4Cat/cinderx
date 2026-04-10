#!/bin/bash
# Build CinderX wheel for ARM64 Linux
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

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
    echo "Building wheel (single-threaded to avoid OOM)..."
    export CMAKE_BUILD_PARALLEL_LEVEL=1
    export CINDERX_BUILD_JOBS=1
    python -m build --wheel 2>&1 | tail -5

    echo ""
    echo "✓ Build complete:"
    ls -lh dist/cinderx-*-linux_aarch64.whl
  '

echo ""
echo "=== Build successful ==="
echo "Wheel: $PROJECT_ROOT/dist/cinderx-*-linux_aarch64.whl"
