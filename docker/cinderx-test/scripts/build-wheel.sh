#!/bin/bash
# Build ARM64 wheel for testing
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=== Building ARM64 wheel ==="
echo "Project root: $PROJECT_ROOT"
echo ""

# Build wheel using Docker
docker run --rm --platform linux/arm64 \
  -v "$PROJECT_ROOT:/cinderx" \
  -w /cinderx \
  python:3.14-slim bash -c '
    set -e
    echo "Installing build dependencies..."
    apt-get update -qq > /dev/null 2>&1
    apt-get install -y -qq build-essential cmake git > /dev/null 2>&1
    pip install --quiet build 2>&1 | grep -v notice | tail -1

    echo ""
    echo "Building wheel (single-threaded to avoid OOM)..."
    export CMAKE_BUILD_PARALLEL_LEVEL=1
    export CINDERX_BUILD_JOBS=1
    python -m build --wheel 2>&1 | tail -5

    echo ""
    echo "Build complete:"
    ls -lh dist/cinderx-*-linux_aarch64.whl
  '

echo ""
echo "=== Build complete ==="
echo "Wheel location: $PROJECT_ROOT/dist/cinderx-*-linux_aarch64.whl"
