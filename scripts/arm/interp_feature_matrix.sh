#!/usr/bin/env bash
set -euo pipefail

# Build+test CinderX with feature-flag combos, then measure pure interpreter
# baseline using bench_compare_modes.py.
#
# This script must run on the ARM host.

INCOMING_DIR="${INCOMING_DIR:-/root/work/incoming}"
WORKDIR="${WORKDIR:-/root/work/cinderx-main}"
REMOTE_ENTRY="${REMOTE_ENTRY:-$INCOMING_DIR/remote_update_build_test.sh}"
PY="${PYTHON:-/opt/python-3.14/bin/python3.14}"
DRIVER_VENV="${DRIVER_VENV:-/root/venv-cinderx314}"
BENCH="${BENCH:-richards}"
AUTOJIT="${AUTOJIT:-50}"
PARALLEL="${PARALLEL:-1}"
OUT_ROOT="${OUT_ROOT:-/root/work/arm-sync}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
COMBOS="${COMBOS:-1,1 1,0 0,1 0,0}"
ARM_RUNTIME_SKIP_TESTS="${ARM_RUNTIME_SKIP_TESTS:-test_aarch64_call_sites_are_compact,test_aarch64_duplicate_call_result_arg_chain_is_compact}"
# Keep interpreter baseline on the same CPython base as CinderX driver env.
CPYTHON_PY="${CPYTHON_PY:-/opt/python-3.14/bin/python3.14}"
N="${N:-250}"
WARMUP="${WARMUP:-20000}"
CALLS="${CALLS:-12000}"
REPEATS="${REPEATS:-5}"
REFRESH_TAR_FROM_WORKDIR="${REFRESH_TAR_FROM_WORKDIR:-1}"
UPDATE_TAR="${UPDATE_TAR:-$INCOMING_DIR/cinderx-update.tar}"

DRIVER_PY="$DRIVER_VENV/bin/python"
if [[ ! -x "$DRIVER_PY" ]]; then
  echo "ERROR: missing driver python: $DRIVER_PY"
  exit 1
fi
if [[ ! -x "$REMOTE_ENTRY" ]]; then
  echo "ERROR: missing remote entrypoint: $REMOTE_ENTRY"
  exit 1
fi

OUT_DIR="$OUT_ROOT/interp_feature_matrix_${RUN_ID}"
mkdir -p "$OUT_DIR"

RESULTS_TSV="$OUT_DIR/results.tsv"
cat >"$RESULTS_TSV" <<'EOF'
combo	status	build_rc	bench_rc	adaptive_static	lightweight_frames	runtime_adaptive	runtime_lightweight	median_sec	min_sec	check	cinderx_over_cpython	json_path	build_stdout	build_stderr	bench_stdout	bench_stderr	feature_json
EOF

CP_JSON="$OUT_DIR/cpython_interp.json"
CP_STDOUT="$OUT_DIR/cpython_interp.stdout"
CP_STDERR="$OUT_DIR/cpython_interp.stderr"
CPYTHON_MEDIAN=""

if [[ -x "$CPYTHON_PY" ]]; then
  set +e
  env PYTHON_JIT=0 "$CPYTHON_PY" "$WORKDIR/scripts/arm/bench_compare_modes.py" \
    --runtime cpython --mode interp --n "$N" --warmup "$WARMUP" --calls "$CALLS" \
    --repeats "$REPEATS" --output "$CP_JSON" >"$CP_STDOUT" 2>"$CP_STDERR"
  cp_rc=$?
  set -e
  if [[ "$cp_rc" -eq 0 ]]; then
    CPYTHON_MEDIAN="$("$DRIVER_PY" - <<'PY' "$CP_JSON"
import json, sys
try:
    d = json.load(open(sys.argv[1], "r", encoding="utf-8"))
    print(d.get("median_sec", ""))
except Exception:
    print("")
PY
)"
  fi
fi

echo "== interp feature matrix =="
echo "run_id=$RUN_ID"
echo "out_dir=$OUT_DIR"
echo "combos=$COMBOS"
echo "cpython_median=${CPYTHON_MEDIAN:-N/A}"
echo "arm_runtime_skip_tests=${ARM_RUNTIME_SKIP_TESTS:-<none>}"

refresh_update_tar() {
  local stage
  stage="$(mktemp -d /tmp/cinderx-matrix-src.XXXXXX)"
  mkdir -p "$stage/cinderx-src"
  rsync -a --delete --exclude .git --exclude scratch --exclude dist --exclude artifacts \
    "$WORKDIR/" "$stage/cinderx-src/"
  tar -cf "$UPDATE_TAR" -C "$stage" cinderx-src
  rm -rf "$stage"
}

for combo in $COMBOS; do
  if [[ "$combo" != *,* ]]; then
    echo "ERROR: invalid combo '$combo' (expected A,B)"
    exit 1
  fi
  adaptive="${combo%,*}"
  lightweight="${combo#*,}"
  if ! [[ "$adaptive" =~ ^[01]$ && "$lightweight" =~ ^[01]$ ]]; then
    echo "ERROR: combo '$combo' must be 0/1 pair"
    exit 1
  fi

  tag="asp${adaptive}_lwf${lightweight}"
  build_stdout="$OUT_DIR/${tag}.build.stdout"
  build_stderr="$OUT_DIR/${tag}.build.stderr"
  bench_stdout="$OUT_DIR/${tag}.bench.stdout"
  bench_stderr="$OUT_DIR/${tag}.bench.stderr"
  json="$OUT_DIR/${tag}.json"
  feature_json="$OUT_DIR/${tag}.features.json"
  runtime_adaptive=""
  runtime_lightweight=""
  median=""
  minv=""
  checkv=""
  rel=""

  echo
  echo ">> combo=$combo ($tag)"

  if [[ "$REFRESH_TAR_FROM_WORKDIR" == "1" ]]; then
    refresh_update_tar
  fi

  set +e
  env \
    INCOMING_DIR="$INCOMING_DIR" \
    WORKDIR="$WORKDIR" \
    PYTHON="$PY" \
    DRIVER_VENV="$DRIVER_VENV" \
    BENCH="$BENCH" \
    AUTOJIT="$AUTOJIT" \
    PARALLEL="$PARALLEL" \
    SKIP_PYPERF=1 \
    RECREATE_PYPERF_VENV=0 \
    ENABLE_ADAPTIVE_STATIC_PYTHON="$adaptive" \
    ENABLE_LIGHTWEIGHT_FRAMES="$lightweight" \
    ARM_RUNTIME_SKIP_TESTS="$ARM_RUNTIME_SKIP_TESTS" \
    "$REMOTE_ENTRY" >"$build_stdout" 2>"$build_stderr"
  build_rc=$?
  set -e

  if [[ "$build_rc" -ne 0 ]]; then
    status="build_fail"
    printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
      "$combo" "$status" "$build_rc" "" "$adaptive" "$lightweight" \
      "" "" "" "" "" "" "" "$build_stdout" "$build_stderr" "" "" "" >>"$RESULTS_TSV"
    echo "status=$status build_rc=$build_rc"
    continue
  fi

  set +e
  env PYTHONJITDISABLE=1 "$DRIVER_PY" - <<'PY' >"$feature_json" 2>"$bench_stderr"
import json
import cinderx

print(
    json.dumps(
        {
            "adaptive_static_python": bool(
                cinderx.is_adaptive_static_python_enabled()
            ),
            "lightweight_frames": bool(cinderx.is_lightweight_frames_enabled()),
        },
        ensure_ascii=False,
    )
)
PY
  feat_rc=$?
  set -e
  if [[ "$feat_rc" -eq 0 ]]; then
    runtime_adaptive="$("$DRIVER_PY" - <<'PY' "$feature_json"
import json, sys
d = json.load(open(sys.argv[1], "r", encoding="utf-8"))
print("1" if d.get("adaptive_static_python") else "0")
PY
)"
    runtime_lightweight="$("$DRIVER_PY" - <<'PY' "$feature_json"
import json, sys
d = json.load(open(sys.argv[1], "r", encoding="utf-8"))
print("1" if d.get("lightweight_frames") else "0")
PY
)"
  fi

  set +e
  env \
    PYTHONJITDISABLE=1 \
    ENABLE_ADAPTIVE_STATIC_PYTHON="$adaptive" \
    ENABLE_LIGHTWEIGHT_FRAMES="$lightweight" \
    "$DRIVER_PY" "$WORKDIR/scripts/arm/bench_compare_modes.py" \
      --runtime cinderx --mode interp --n "$N" --warmup "$WARMUP" \
      --calls "$CALLS" --repeats "$REPEATS" --output "$json" \
      >"$bench_stdout" 2>>"$bench_stderr"
  bench_rc=$?
  set -e

  if [[ "$bench_rc" -ne 0 ]]; then
    status="bench_fail"
    printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
      "$combo" "$status" "$build_rc" "$bench_rc" "$adaptive" "$lightweight" \
      "$runtime_adaptive" "$runtime_lightweight" "" "" "" "" "$json" "$build_stdout" "$build_stderr" \
      "$bench_stdout" "$bench_stderr" "$feature_json" >>"$RESULTS_TSV"
    echo "status=$status bench_rc=$bench_rc"
    continue
  fi

  read -r median minv checkv <<EOF
$("$DRIVER_PY" - <<'PY' "$json"
import json, sys
d = json.load(open(sys.argv[1], "r", encoding="utf-8"))
print(d.get("median_sec", ""), d.get("min_sec", ""), d.get("check", ""))
PY
)
EOF

  if [[ -n "$CPYTHON_MEDIAN" && -n "$median" ]]; then
    rel="$("$DRIVER_PY" - <<'PY' "$median" "$CPYTHON_MEDIAN"
import sys
cur = float(sys.argv[1])
base = float(sys.argv[2])
print(cur / base if base else "")
PY
)"
  fi

  status="ok"
  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
    "$combo" "$status" "$build_rc" "$bench_rc" "$adaptive" "$lightweight" \
    "$runtime_adaptive" "$runtime_lightweight" "$median" "$minv" "$checkv" "$rel" \
    "$json" "$build_stdout" "$build_stderr" "$bench_stdout" "$bench_stderr" \
    "$feature_json" >>"$RESULTS_TSV"
  echo "status=$status median=${median}s cinderx_over_cpython=${rel:-N/A}"
done

SUMMARY_JSON="$OUT_DIR/summary.json"
"$DRIVER_PY" - <<'PY' "$RESULTS_TSV" "$SUMMARY_JSON" "$RUN_ID" "$CP_JSON" "$CPYTHON_MEDIAN"
import csv
import json
import pathlib
import sys

rows_path = pathlib.Path(sys.argv[1])
summary_path = pathlib.Path(sys.argv[2])
run_id = sys.argv[3]
cpython_json = sys.argv[4]
cpython_median = sys.argv[5]

rows = []
with rows_path.open("r", encoding="utf-8") as f:
    reader = csv.DictReader(f, delimiter="\t")
    for row in reader:
        row["build_rc"] = int(row["build_rc"]) if row["build_rc"] else None
        row["bench_rc"] = int(row["bench_rc"]) if row["bench_rc"] else None
        row["adaptive_static"] = int(row["adaptive_static"])
        row["lightweight_frames"] = int(row["lightweight_frames"])
        for key in (
            "runtime_adaptive",
            "runtime_lightweight",
            "median_sec",
            "min_sec",
            "check",
            "cinderx_over_cpython",
        ):
            if row[key] == "":
                row[key] = None
        if row["runtime_adaptive"] is not None:
            row["runtime_adaptive"] = int(row["runtime_adaptive"])
        if row["runtime_lightweight"] is not None:
            row["runtime_lightweight"] = int(row["runtime_lightweight"])
        if row["median_sec"] is not None:
            row["median_sec"] = float(row["median_sec"])
        if row["min_sec"] is not None:
            row["min_sec"] = float(row["min_sec"])
        if row["check"] is not None:
            row["check"] = int(row["check"])
        if row["cinderx_over_cpython"] is not None:
            row["cinderx_over_cpython"] = float(row["cinderx_over_cpython"])
        rows.append(row)

summary = {
    "run_id": run_id,
    "cpython_interp_json": cpython_json if pathlib.Path(cpython_json).exists() else None,
    "cpython_interp_median_sec": float(cpython_median) if cpython_median else None,
    "rows": rows,
    "ok_combos": [r["combo"] for r in rows if r["status"] == "ok"],
    "failed_combos": [r["combo"] for r in rows if r["status"] != "ok"],
}

summary_path.write_text(
    json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
print(json.dumps(summary, indent=2, ensure_ascii=False))
PY

echo
echo "summary_json=$SUMMARY_JSON"
echo "results_tsv=$RESULTS_TSV"
