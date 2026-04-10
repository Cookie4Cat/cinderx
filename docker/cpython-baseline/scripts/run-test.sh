#!/bin/bash
# End-to-end CinderX performance test
set -e

set -a
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
set +a

echo "========================================"
echo "  CinderX End-to-End Performance Test"
echo "========================================"
echo ""

# Step 1: Build CinderX wheel
echo "=== Step 1: Building CinderX wheel ==="
"$SCRIPT_DIR/build-cinderx.sh"

echo ""

# Step 2: Build CPython baseline image
echo "=== Step 2: Building CPython baseline image ==="
cd "$SCRIPT_DIR/.."
if ! docker images | grep -q "cpython-baseline"; then
  echo "Building Docker image (this may take 20-30 minutes on first run)..."
  docker compose build
else
  echo "Docker image already exists"
fi

echo ""

# Step 3: Start container
echo "=== Step 3: Starting container ==="
docker compose up -d
sleep 2
echo "Container status:"
docker ps | grep cpython-baseline

echo ""

# Step 4: Run comparison test
echo "=== Step 4: Running performance comparison ==="
echo "Running test with SAMPLES=${SAMPLES:-10}..."
docker compose exec cpython-baseline /scripts/test-comparison.sh

echo ""

# Step 5: Show results
echo "========================================"
echo "  Results"
echo "========================================"
if [ -f "$SCRIPT_DIR/../results/comparison.json" ]; then
  cat "$SCRIPT_DIR/../results/comparison.json" | python3 -m json.tool
else
  echo "Results file not found"
fi

echo ""
echo "========================================"
echo "  Test Complete"
echo "========================================"
echo ""
echo "To clean up:"
echo "  cd $SCRIPT_DIR/.."
echo "  docker compose down"
