#!/usr/bin/env bash
set -euo pipefail

DRIVER_VENV="${DRIVER_VENV:-/root/venv-cinderx314}"
WORKDIR="${WORKDIR:-$(pwd)}"
BENCHMARKS="${BENCHMARKS:-}"
SAMPLES="${SAMPLES:-3}"
OUTPUT="${OUTPUT:-/root/work/arm-sync/pyperf_subset_nojit.json}"

if [[ -z "$BENCHMARKS" ]]; then
  echo "ERROR: BENCHMARKS must be set"
  exit 2
fi

DRIVER_PY="$DRIVER_VENV/bin/python"
if [[ ! -x "$DRIVER_PY" ]]; then
  echo "ERROR: missing driver python: $DRIVER_PY"
  exit 2
fi

HOOK_DIR="$WORKDIR/scripts/arm/pyperf_env_hook"
if [[ ! -f "$HOOK_DIR/sitecustomize.py" ]]; then
  echo "ERROR: missing hook dir: $HOOK_DIR"
  exit 2
fi

TMPDIR="$(mktemp -d /tmp/pyperf_subset_nojit.XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT

echo "pyperf_subset_nojit_benchmarks=$BENCHMARKS"
echo "pyperf_subset_nojit_samples=$SAMPLES"
echo "pyperf_subset_nojit_output=$OUTPUT"

for ((i = 1; i <= SAMPLES; i++)); do
  out="$TMPDIR/run_${i}.json"
  echo ">> pyperformance subset nojit sample $i/$SAMPLES"
  env \
    PYTHONJITDISABLE=1 \
    PYTHONPATH="$HOOK_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    "$DRIVER_PY" -m pyperformance run --debug-single-value -b "$BENCHMARKS" \
      --inherit-environ PYTHONPATH,PYTHONJITDISABLE \
      -o "$out"
done

"$DRIVER_PY" - <<'PY' "$TMPDIR" "$OUTPUT" "$BENCHMARKS" "$SAMPLES"
import json
import statistics
import sys
from pathlib import Path

tmpdir = Path(sys.argv[1])
output = Path(sys.argv[2])
benchmarks = sys.argv[3].split(",")
samples = int(sys.argv[4])

rows = {}
for path in sorted(tmpdir.glob("run_*.json")):
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    for bench in data.get("benchmarks", []):
        name = bench.get("metadata", {}).get("name")
        if name is None:
            continue
        value = bench["runs"][0]["values"][0]
        rows.setdefault(name, []).append(float(value))

summary = {
    "benchmarks": [],
    "benchmark_filter": benchmarks,
    "samples": samples,
    "mode": "nojit",
}

for name in sorted(rows):
    vals = rows[name]
    summary["benchmarks"].append(
        {
            "name": name,
            "samples": vals,
            "median": statistics.median(vals),
            "min": min(vals),
            "max": max(vals),
        }
    )

output.parent.mkdir(parents=True, exist_ok=True)
with output.open("w", encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=2)
    fh.write("\n")

print(output)
PY
