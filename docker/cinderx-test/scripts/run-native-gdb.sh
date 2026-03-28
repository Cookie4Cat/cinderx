#!/usr/bin/env bash

set -euo pipefail

BENCHMARK="${BENCHMARK:-mdp}"
WARMUP="${WARMUP:-1}"
AUTOJIT="${PYTHONJITAUTO:-2}"
RESULTS_ROOT="${RESULTS_ROOT:-/results}"
OUTPUT_FILE="${OUTPUT_FILE:-/tmp/pyperformance-cinderx.json}"
JIT_LOG_FILE="${JIT_LOG_FILE:-$RESULTS_ROOT/${BENCHMARK}-native-jit.log}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
GDB_ARGS=("$@")

export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-/opt/python314/lib:/opt/openEuler/gcc-toolset-14/root/usr/lib64}"
export PYTHONJIT=1
export PYTHONJITAUTO="$AUTOJIT"
export PYTHONJITHUGEPAGES=0
export PYTHONJITLOGFILE="$JIT_LOG_FILE"
export PYTHONJITDUMPFINALHIR=1
export PYTHONJITDUMPSTATS=1
export PYTHONPATH="${PYTHONPATH:-/opt/python314/lib/python3.14/site-packages}"

exec gdb -q "${GDB_ARGS[@]}" --args \
  "$PYTHON_BIN" -m pyperformance run \
  --debug-single-value \
  --warmups "$WARMUP" \
  -b "$BENCHMARK" \
  --inherit-environ \
LD_LIBRARY_PATH,PYTHONJIT,PYTHONJITAUTO,PYTHONJITHUGEPAGES,PYTHONJITLOGFILE,PYTHONJITDUMPFINALHIR,PYTHONJITDUMPSTATS \
  -o "$OUTPUT_FILE"
