#!/usr/bin/env bash
set -euo pipefail

PY="${PY:-/opt/python-3.14/bin/python3.14}"
RUNNER="${RUNNER:-/root/work/incoming/bench_single_mode.py}"
BENCH="${BENCH:-nbody}"
OUTDIR="${OUTDIR:-/root/work/perf_${BENCH}_analysis}"
EVENT="${EVENT:-cpu-clock}"
FREQ="${FREQ:-999}"
WARMUP="${WARMUP:-20}"
ROUNDS="${ROUNDS:-35}"
AUTOJIT="${AUTOJIT:-1}"
RUN_ARGS_JSON="${RUN_ARGS_JSON:-}"
RUN_REPEAT="${RUN_REPEAT:--1}"
SORT_KEY="${SORT_KEY:-symbol,dso}"
ANNOTATE_SYMBOL="${ANNOTATE_SYMBOL:-}"
READY_MARKER="${READY_MARKER:-READY_FOR_PERF}"
READY_TIMEOUT_SEC="${READY_TIMEOUT_SEC:-120}"
PERF_START_DELAY_SEC="${PERF_START_DELAY_SEC:-1}"

mkdir -p "$OUTDIR"

wait_for_ready_marker() {
  local runlog="$1"
  local runner_pid="$2"
  local marker="$3"
  local timeout_sec="$4"
  local ticks=$((timeout_sec * 10))
  local i
  for ((i = 0; i < ticks; i++)); do
    if [[ -f "$runlog" ]] && grep -Fq "$marker" "$runlog"; then
      return 0
    fi
    if ! kill -0 "$runner_pid" 2>/dev/null; then
      return 1
    fi
    sleep 0.1
  done
  return 1
}

run_one() {
  local mode="$1"
  local data="$OUTDIR/perf.${mode}.data"
  local report="$OUTDIR/perf.${mode}.report.txt"
  local annotate="$OUTDIR/perf.${mode}.annotate.txt"
  local runlog="$OUTDIR/run.${mode}.txt"
  local perf_record_log="$OUTDIR/perf.${mode}.record.log"
  local gate_file="$OUTDIR/gate.${mode}.go"
  rm -f "$gate_file"

  local -a runner_cmd=(
    "$PY" "$RUNNER"
    --bench "$BENCH"
    --mode "$mode"
    --warmup-rounds "$WARMUP"
    --rounds "$ROUNDS"
    --autojit "$AUTOJIT"
    --repeat "$RUN_REPEAT"
    --wait-after-warmup
    --ready-marker "$READY_MARKER"
    --gate-file "$gate_file"
    --gate-timeout-sec "$READY_TIMEOUT_SEC"
  )
  if [[ -n "$RUN_ARGS_JSON" ]]; then
    runner_cmd+=(--args-json "$RUN_ARGS_JSON")
  fi

  echo "[perf] mode=$mode (sample measured phase only)"
  if [[ "$mode" == "cinderx" ]]; then
    JIT_PERFMAP=1 "${runner_cmd[@]}" > "$runlog" 2>&1 &
  else
    "${runner_cmd[@]}" > "$runlog" 2>&1 &
  fi
  local runner_pid=$!

  if ! wait_for_ready_marker "$runlog" "$runner_pid" "$READY_MARKER" "$READY_TIMEOUT_SEC"; then
    echo "[error] runner did not reach ready marker in time: mode=$mode"
    set +e
    kill "$runner_pid" 2>/dev/null
    wait "$runner_pid" 2>/dev/null
    set -e
    rm -f "$gate_file"
    return 1
  fi

  perf record -o "$data" -e "$EVENT" -F "$FREQ" -p "$runner_pid" > "$perf_record_log" 2>&1 &
  local perf_pid=$!

  sleep "$PERF_START_DELAY_SEC"
  : > "$gate_file"

  set +e
  wait "$runner_pid"
  local runner_rc=$?
  set -e

  if kill -0 "$perf_pid" 2>/dev/null; then
    kill -INT "$perf_pid" 2>/dev/null || true
  fi
  set +e
  wait "$perf_pid"
  local perf_rc=$?
  set -e

  rm -f "$gate_file"

  if [[ "$runner_rc" -ne 0 ]]; then
    echo "[error] runner failed: mode=$mode rc=$runner_rc"
    tail -n 80 "$runlog" || true
    return "$runner_rc"
  fi
  if [[ "$perf_rc" -ne 0 && "$perf_rc" -ne 130 ]]; then
    echo "[warn] perf record exited with rc=$perf_rc (mode=$mode)"
  fi
  if [[ ! -s "$data" ]]; then
    echo "[error] perf data file missing/empty: $data"
    tail -n 80 "$perf_record_log" || true
    return 1
  fi

  perf report -i "$data" --stdio --sort "$SORT_KEY" --percent-limit 0.2 > "$report"
  if [[ -n "$ANNOTATE_SYMBOL" ]]; then
    perf annotate -i "$data" --stdio --symbol "$ANNOTATE_SYMBOL" > "$annotate" || true
  else
    : > "$annotate"
  fi

  echo "  data:     $data"
  echo "  run log:  $runlog"
  echo "  perf log: $perf_record_log"
  echo "  report:   $report"
  echo "  annotate: $annotate"
}

run_one cpython
run_one cinderx

echo
echo "== top symbols (each mode) | bench=$BENCH =="
for mode in cpython cinderx; do
  echo
  echo "---- $mode ----"
  sed -n '1,80p' "$OUTDIR/perf.${mode}.report.txt"
done

echo
echo "== JIT symbols =="
for mode in cinderx; do
  echo
  echo "---- $mode ----"
  grep "__CINDER_JIT:" "$OUTDIR/perf.${mode}.report.txt" || true
done
