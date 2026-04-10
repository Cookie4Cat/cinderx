#!/usr/bin/env bash
set -euo pipefail

# Run auto-jit threshold crash matrix on ARM and collect coredump backtraces.
#
# Expected environment:
# - DRIVER_VENV: venv used to run pyperformance driver
# - BENCH: pyperformance benchmark name
# - THRESHOLDS: space-separated auto-jit thresholds
# - OUT_ROOT: output root
# - TIMEOUT_SEC: timeout per threshold run
# - EXE_MATCH: executable path used for coredumpctl matching

DRIVER_VENV="${DRIVER_VENV:-/root/venv-cinderx314}"
BENCH="${BENCH:-richards}"
THRESHOLDS="${THRESHOLDS:-20 50 80 100 200}"
OUT_ROOT="${OUT_ROOT:-/root/work/arm-sync}"
TIMEOUT_SEC="${TIMEOUT_SEC:-900}"
EXE_MATCH="${EXE_MATCH:-/opt/python-3.14/bin/python3.14}"
PYPERF_WORKDIR="${PYPERF_WORKDIR:-/root/work/cinderx-main}"
PYPERF_VENV_PATH="${PYPERF_VENV_PATH:-}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
SCRIPT_VERSION="v3-pyperf-workdir-pinned"

DRIVER_PY="$DRIVER_VENV/bin/python"
if [[ ! -x "$DRIVER_PY" ]]; then
  echo "ERROR: missing driver python: $DRIVER_PY"
  exit 1
fi

if ! "$DRIVER_PY" -m pyperformance --help >/dev/null 2>&1; then
  echo "ERROR: pyperformance is not available in $DRIVER_VENV"
  exit 1
fi

if [[ -n "$PYPERF_VENV_PATH" ]]; then
  PYPERF_VENV="$PYPERF_VENV_PATH"
else
  if [[ ! -d "$PYPERF_WORKDIR" ]]; then
    echo "ERROR: missing PYPERF_WORKDIR: $PYPERF_WORKDIR"
    exit 1
  fi
  PYPERF_VENV="$(
    cd "$PYPERF_WORKDIR" && \
      "$DRIVER_PY" -m pyperformance venv show 2>/dev/null | \
      sed -n 's/^Virtual environment path: \([^ ]*\).*$/\1/p'
  )"
fi
if [[ -z "$PYPERF_VENV" || ! -d "$PYPERF_VENV" ]]; then
  echo "ERROR: failed to resolve pyperformance venv path from $DRIVER_VENV"
  (
    cd "$PYPERF_WORKDIR" 2>/dev/null || true
    "$DRIVER_PY" -m pyperformance venv show || true
  )
  exit 1
fi

OUT_DIR="$OUT_ROOT/autojit_matrix_${RUN_ID}"
mkdir -p "$OUT_DIR"

RESULTS_TSV="$OUT_DIR/results.tsv"
cat >"$RESULTS_TSV" <<'EOF'
threshold	status	exit_code	duration_sec	value_sec	finished_total	main_compile_count	deopt_count	core_pid	json_path	log_path	stdout_path	stderr_path	core_info_path	core_bt_path	dmesg_tail_path
EOF

echo "== autojit crash matrix =="
echo "script_version=$SCRIPT_VERSION"
echo "run_id=$RUN_ID"
echo "driver_python=$DRIVER_PY"
echo "pyperf_workdir=$PYPERF_WORKDIR"
echo "pyperf_venv=$PYPERF_VENV"
echo "bench=$BENCH"
echo "thresholds=$THRESHOLDS"
echo "out_dir=$OUT_DIR"

for thr in $THRESHOLDS; do
  if ! [[ "$thr" =~ ^[0-9]+$ ]]; then
    echo "ERROR: invalid threshold '$thr' (must be integer)"
    exit 1
  fi

  json="$OUT_DIR/${BENCH}_autojit${thr}.json"
  log="$OUT_DIR/jit_${BENCH}_autojit${thr}.log"
  out="$OUT_DIR/autojit${thr}.stdout"
  err="$OUT_DIR/autojit${thr}.stderr"
  dmesg_tail="$OUT_DIR/autojit${thr}.dmesg_tail.txt"
  core_info=""
  core_bt=""
  core_pid=""

  echo
  echo ">> threshold=$thr"
  start_epoch="$(date +%s)"
  t0="$(date +%s)"

  set +e
  (
    cd "$PYPERF_WORKDIR"
    timeout "$TIMEOUT_SEC" env \
      PYTHONJITAUTO="$thr" \
      PYTHONJITDEBUG=1 \
      PYTHONJITLOGFILE="$log" \
      "$DRIVER_PY" -m pyperformance run --debug-single-value -b "$BENCH" \
        --inherit-environ PYTHONJITAUTO,PYTHONJITDEBUG,PYTHONJITLOGFILE \
        -o "$json" \
        >"$out" 2>"$err"
  )
  rc=$?
  set -e

  t1="$(date +%s)"
  duration="$((t1 - t0))"

  if [[ "$rc" -eq 0 ]]; then
    status="ok"
  elif [[ "$rc" -eq 124 ]]; then
    status="timeout"
  else
    status="fail"
  fi

  value="$("$DRIVER_PY" - <<'PY' "$json"
import json, sys
path = sys.argv[1]
try:
    d = json.load(open(path, "r", encoding="utf-8"))
    v = d["benchmarks"][0]["runs"][0]["values"][0]
    print(v)
except Exception:
    print("")
PY
)"
  finished_total="$(grep -c 'Finished compiling ' "$log" 2>/dev/null || true)"
  main_count="$(grep -c 'Finished compiling __main__:' "$log" 2>/dev/null || true)"
  deopt_count="$(grep -ic 'deopt' "$log" 2>/dev/null || true)"

  if [[ "$rc" -ne 0 ]]; then
    dmesg -T | tail -n 200 >"$dmesg_tail" 2>&1 || true

    core_list_json="$OUT_DIR/core_${thr}.list.json"
    coredumpctl --no-pager --json=short --reverse --since "@${start_epoch}" list "$EXE_MATCH" \
      >"$core_list_json" 2>/dev/null || true
    core_pid="$("$DRIVER_PY" - <<'PY' "$core_list_json"
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
if not path.exists():
    print("")
    raise SystemExit(0)
try:
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        print("")
        raise SystemExit(0)
    data = json.loads(text)
except Exception:
    print("")
    raise SystemExit(0)

if isinstance(data, list) and data:
    pid = data[0].get("pid")
    print("" if pid is None else str(pid))
else:
    print("")
PY
)"
    if [[ -n "$core_pid" ]]; then
      core_info="$OUT_DIR/core_${thr}_${core_pid}.info.txt"
      core_bt="$OUT_DIR/core_${thr}_${core_pid}.bt.txt"
      coredumpctl --no-pager info "$core_pid" >"$core_info" 2>&1 || true
      coredumpctl --no-pager debug "$core_pid" -A '-batch -ex bt' >"$core_bt" 2>&1 || true
    fi
  fi

  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
    "$thr" "$status" "$rc" "$duration" "$value" "$finished_total" "$main_count" \
    "$deopt_count" "$core_pid" "$json" "$log" "$out" "$err" "$core_info" "$core_bt" \
    "$dmesg_tail" >>"$RESULTS_TSV"

  echo "status=$status rc=$rc duration=${duration}s value=${value:-N/A} main=$main_count total=$finished_total deopt=$deopt_count core_pid=${core_pid:-N/A}"
done

SUMMARY_JSON="$OUT_DIR/summary.json"
"$DRIVER_PY" - <<'PY' "$RESULTS_TSV" "$SUMMARY_JSON" "$RUN_ID" "$BENCH"
import csv
import json
import pathlib
import sys

rows_path = pathlib.Path(sys.argv[1])
summary_path = pathlib.Path(sys.argv[2])
run_id = sys.argv[3]
bench = sys.argv[4]

rows = []
with rows_path.open("r", encoding="utf-8") as f:
    reader = csv.DictReader(f, delimiter="\t")
    for row in reader:
        row["threshold"] = int(row["threshold"])
        row["exit_code"] = int(row["exit_code"])
        row["duration_sec"] = int(row["duration_sec"])
        row["finished_total"] = int(row["finished_total"])
        row["main_compile_count"] = int(row["main_compile_count"])
        row["deopt_count"] = int(row["deopt_count"])
        if row["value_sec"] == "":
            row["value_sec"] = None
        else:
            row["value_sec"] = float(row["value_sec"])
        for key in (
            "core_pid",
            "core_info_path",
            "core_bt_path",
            "dmesg_tail_path",
        ):
            if row.get(key, "") == "":
                row[key] = None
        rows.append(row)

summary = {
    "run_id": run_id,
    "bench": bench,
    "rows": rows,
    "ok_thresholds": [r["threshold"] for r in rows if r["status"] == "ok"],
    "failed_thresholds": [r["threshold"] for r in rows if r["status"] != "ok"],
}
summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2, ensure_ascii=False))
PY

echo
echo "summary_json=$SUMMARY_JSON"
echo "results_tsv=$RESULTS_TSV"
