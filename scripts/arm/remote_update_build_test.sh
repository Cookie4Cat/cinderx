#!/usr/bin/env bash
set -euo pipefail

# This script runs on the ARM host. It expects:
# - ${INCOMING_DIR}/cinderx-update.tar uploaded from Windows (git archive output)
# - It will rsync the extracted sources into $WORKDIR (preserving scratch/, dist/)
# - It will build a wheel, install it into the driver venv, set up pyperformance venv
# - It will run smoke tests + pyperformance gates to catch crashes early

INCOMING_DIR="${INCOMING_DIR:-/root/work/incoming}"
WORKDIR="${WORKDIR:-/root/work/cinderx-main}"
PY="${PYTHON:-/opt/python-3.14/bin/python3.14}"
DRIVER_VENV="${DRIVER_VENV:-/root/venv-cinderx314}"
BENCH="${BENCH:-richards}"
AUTOJIT="${AUTOJIT:-50}"
SMOKE_AUTOJIT="${SMOKE_AUTOJIT:-10}"
PARALLEL="${PARALLEL:-1}"
SKIP_PYPERF="${SKIP_PYPERF:-0}"
SKIP_DEFAULT_PYPERF_GATES="${SKIP_DEFAULT_PYPERF_GATES:-0}"
RECREATE_PYPERF_VENV="${RECREATE_PYPERF_VENV:-0}"
AUTOJIT_GATE="${AUTOJIT_GATE:-$AUTOJIT}"
AUTOJIT_USE_JITLIST_FILTER="${AUTOJIT_USE_JITLIST_FILTER:-1}"
AUTOJIT_EXTRA_JITLIST="${AUTOJIT_EXTRA_JITLIST:-}"
ARM_RUNTIME_SKIP_TESTS="${ARM_RUNTIME_SKIP_TESTS:-}"
EXTRA_TEST_CMD="${EXTRA_TEST_CMD:-}"
EXTRA_VERIFY_CMD="${EXTRA_VERIFY_CMD:-}"
POST_PYPERF_CMD="${POST_PYPERF_CMD:-}"
PYPERF_REQUIRE_SYSTEM_SITE_PACKAGES="${PYPERF_REQUIRE_SYSTEM_SITE_PACKAGES:-1}"
CINDERX_ENABLE_SPECIALIZED_OPCODES="${CINDERX_ENABLE_SPECIALIZED_OPCODES:-0}"
CINDERX_JITLIST_ENTRIES="${CINDERX_JITLIST_ENTRIES:-}"

if ! [[ "$AUTOJIT_GATE" =~ ^[0-9]+$ ]]; then
  echo "ERROR: AUTOJIT_GATE must be a non-negative integer, got '$AUTOJIT_GATE'"
  exit 1
fi
if [[ "$AUTOJIT_USE_JITLIST_FILTER" != "0" && "$AUTOJIT_USE_JITLIST_FILTER" != "1" ]]; then
  echo "ERROR: AUTOJIT_USE_JITLIST_FILTER must be 0 or 1, got '$AUTOJIT_USE_JITLIST_FILTER'"
  exit 1
fi
if [[ "$PYPERF_REQUIRE_SYSTEM_SITE_PACKAGES" != "0" && "$PYPERF_REQUIRE_SYSTEM_SITE_PACKAGES" != "1" ]]; then
  echo "ERROR: PYPERF_REQUIRE_SYSTEM_SITE_PACKAGES must be 0 or 1, got '$PYPERF_REQUIRE_SYSTEM_SITE_PACKAGES'"
  exit 1
fi
if [[ "$CINDERX_ENABLE_SPECIALIZED_OPCODES" != "0" && "$CINDERX_ENABLE_SPECIALIZED_OPCODES" != "1" ]]; then
  echo "ERROR: CINDERX_ENABLE_SPECIALIZED_OPCODES must be 0 or 1, got '$CINDERX_ENABLE_SPECIALIZED_OPCODES'"
  exit 1
fi
if [[ "$SKIP_DEFAULT_PYPERF_GATES" != "0" && "$SKIP_DEFAULT_PYPERF_GATES" != "1" ]]; then
  echo "ERROR: SKIP_DEFAULT_PYPERF_GATES must be 0 or 1, got '$SKIP_DEFAULT_PYPERF_GATES'"
  exit 1
fi

mkdir -p "$WORKDIR" "$INCOMING_DIR" /root/work/arm-sync

RUN_ID="$(date +%Y%m%d_%H%M%S)"

run_extra_cmd() {
  local label="$1"
  local cmd="$2"
  if [[ -z "$cmd" ]]; then
    return 0
  fi
  echo ">> $label"
  env WORKDIR="$WORKDIR" DRIVER_VENV="$DRIVER_VENV" PYTHON="$DRIVER_VENV/bin/python" \
    bash -lc "cd '$WORKDIR' && $cmd"
}

echo ">> staging extract"
stage="$(mktemp -d /root/work/cinderx-stage.XXXXXX)"
tar -xf "$INCOMING_DIR/cinderx-update.tar" -C "$stage"

echo ">> rsync sources into $WORKDIR (preserve scratch/, dist/)"
rsync -a --delete --exclude scratch --exclude dist "$stage/cinderx-src/" "$WORKDIR/"
rm -rf "$stage" "$INCOMING_DIR/cinderx-update.tar"

cd "$WORKDIR"
export CMAKE_BUILD_PARALLEL_LEVEL="$PARALLEL"

echo ">> build wheel (CMAKE_BUILD_PARALLEL_LEVEL=$CMAKE_BUILD_PARALLEL_LEVEL)"
"$PY" -m build --wheel
WHEEL="$(ls -1t dist/cinderx-*.whl | head -n 1)"
echo "wheel=$WHEEL"

if [[ ! -d "$DRIVER_VENV" ]]; then
  echo ">> create driver venv $DRIVER_VENV"
  "$PY" -m venv "$DRIVER_VENV"
fi

echo ">> install wheel + pyperformance into driver venv"
. "$DRIVER_VENV/bin/activate"
PYTHONJIT=0 python -m pip install -q -U pip
PYTHONJIT=0 python -m pip install -q --force-reinstall "$WHEEL"
PYTHONJIT=0 python -m pip install -q -U pyperformance

echo ">> unittest: ARM runtime checks"
if [[ -z "$ARM_RUNTIME_SKIP_TESTS" ]]; then
  python cinderx/PythonLib/test_cinderx/test_arm_runtime.py
else
  env ARM_RUNTIME_SKIP_TESTS="$ARM_RUNTIME_SKIP_TESTS" python - <<'PY'
import importlib.util
import os
import pathlib
import sys
import unittest

skip_tokens = [
    token.strip()
    for token in os.environ.get("ARM_RUNTIME_SKIP_TESTS", "").split(",")
    if token.strip()
]
if not skip_tokens:
    raise SystemExit("ARM_RUNTIME_SKIP_TESTS is empty")

test_path = pathlib.Path("cinderx/PythonLib/test_cinderx/test_arm_runtime.py")
spec = importlib.util.spec_from_file_location("test_arm_runtime", test_path)
if spec is None or spec.loader is None:
    raise SystemExit(f"failed to load {test_path}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

suite = unittest.defaultTestLoader.loadTestsFromModule(module)
filtered = unittest.TestSuite()
skipped = []


def iter_tests(s):
    for t in s:
        if isinstance(t, unittest.TestSuite):
            yield from iter_tests(t)
        else:
            yield t


for test in iter_tests(suite):
    test_id = test.id()
    if any(token in test_id for token in skip_tokens):
        skipped.append(test_id)
        continue
    filtered.addTest(test)

print("arm_runtime_skip_tokens=", skip_tokens)
print("arm_runtime_skipped_count=", len(skipped))
for test_id in skipped:
    print("skipped:", test_id)

runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(filtered)
if not result.wasSuccessful():
    raise SystemExit(1)
PY
fi

run_extra_cmd "extra test command" "$EXTRA_TEST_CMD"

echo ">> smoke: JIT is effective (compiled code executes, not just 'enabled')"
# We verify effectiveness by:
# 1) Run a function in interpreted mode and observe interpreted call count increases.
# 2) Force-compile it and observe the interpreted call count stops increasing while the function still runs.
env PYTHONJITAUTO=1000000 python - <<'PY'
import cinderx
import cinderx.jit as jit

assert cinderx.is_initialized()
jit.enable()

# Ensure our first calls are interpreted (avoid auto-jit during the interpreted phase).
jit.compile_after_n_calls(1000000)


def f(n: int) -> int:
    s = 0
    for i in range(n):
        s += i
    return s


_ = jit.force_uncompile(f)
assert not jit.is_jit_compiled(f), "expected f() to start interpreted"

before = jit.count_interpreted_calls(f)
for _ in range(10):
    assert f(10) == 45
after = jit.count_interpreted_calls(f)
assert after > before, (before, after)

assert jit.force_compile(f), "force_compile failed"
assert jit.is_jit_compiled(f), "expected f() to be JIT compiled"
code_size = jit.get_compiled_size(f)
assert code_size > 0, code_size

interp0 = jit.count_interpreted_calls(f)
for _ in range(2000):
    assert f(10) == 45
interp1 = jit.count_interpreted_calls(f)
assert interp1 == interp0, (interp0, interp1)

print("jit-effective-ok", "compiled_size", code_size, "interp_calls", interp1)
PY
deactivate

run_extra_cmd "extra verification command" "$EXTRA_VERIFY_CMD"

echo ">> ensure pyperformance venv exists"
. "$DRIVER_VENV/bin/activate"
ensure_pyperf_venv() {
  local action="$1"
  local cmd=()
  if [[ "$action" == "recreate" ]]; then
    cmd=(python -m pyperformance venv recreate)
  else
    cmd=(python -m pyperformance venv create)
  fi

  set +e
  PYTHONJIT=0 "${cmd[@]}"
  local rc=$?
  set -e
  if [[ $rc -eq 0 ]]; then
    return 0
  fi

  echo "WARN: pyperformance venv ${action} failed (rc=$rc), cleanup '$WORKDIR/venv' and retry once"
  rm -rf "$WORKDIR/venv"
  PYTHONJIT=0 "${cmd[@]}"
}

set +e
PYVENV_PATH="$(
  PYTHONJIT=0 python -m pyperformance venv show 2>/dev/null | \
    sed -n 's/^Virtual environment path: \([^ ]*\).*$/\1/p'
)"
set -e
if [[ "$RECREATE_PYPERF_VENV" == "1" ]]; then
  ensure_pyperf_venv recreate
elif [[ -z "$PYVENV_PATH" || ! -x "$PYVENV_PATH/bin/python" ]]; then
  ensure_pyperf_venv create
fi
PYVENV_PATH="$(
  PYTHONJIT=0 python -m pyperformance venv show | \
    sed -n 's/^Virtual environment path: \([^ ]*\).*$/\1/p'
)"
echo "pyperf_venv=$PYVENV_PATH"
if [[ -z "$PYVENV_PATH" || ! -d "$PYVENV_PATH" ]]; then
  echo "ERROR: failed to determine pyperformance venv path"
  python -m pyperformance venv show || true
  exit 1
fi
if [[ "$PYPERF_REQUIRE_SYSTEM_SITE_PACKAGES" == "1" ]]; then
  echo ">> normalize pyperformance venv to include system site-packages"
  python - <<'PY' "$PYVENV_PATH/pyvenv.cfg"
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
lines = text.splitlines()
updated = False
for idx, line in enumerate(lines):
    if line.startswith("include-system-site-packages"):
        lines[idx] = "include-system-site-packages = true"
        updated = True
        break
if not updated:
    lines.append("include-system-site-packages = true")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
fi
PYPERF_VENV_CHECK_ARGS=()
if [[ "$PYPERF_REQUIRE_SYSTEM_SITE_PACKAGES" == "1" ]]; then
  PYPERF_VENV_CHECK_ARGS+=(--require-system-site-packages)
fi
python scripts/arm/verify_pyperf_venv.py \
  --venv "$PYVENV_PATH" \
  "${PYPERF_VENV_CHECK_ARGS[@]}" \
  --output "/root/work/arm-sync/pyperf_venv_${RUN_ID}_cfg.json"
deactivate

echo ">> install wheel into pyperformance venv"
. "$PYVENV_PATH/bin/activate"
PYTHONJIT=0 python -m pip install -q --force-reinstall "$WHEEL"
deactivate
HOOK_DIR="$WORKDIR/scripts/arm/pyperf_env_hook"
if [[ ! -f "$HOOK_DIR/sitecustomize.py" ]]; then
  echo "ERROR: missing pyperformance startup hook: $HOOK_DIR/sitecustomize.py"
  exit 1
fi

echo ">> verify pyperformance venv worker startup"
env CINDERX_WORKER_PYTHONJITAUTO="$SMOKE_AUTOJIT" \
  PYTHONPATH="$HOOK_DIR${PYTHONPATH:+:$PYTHONPATH}" \
  CINDERX_ENABLE_SPECIALIZED_OPCODES="$CINDERX_ENABLE_SPECIALIZED_OPCODES" \
  "$DRIVER_VENV/bin/python" scripts/arm/verify_pyperf_venv.py \
    --venv "$PYVENV_PATH" \
    --probe-worker \
    --worker-argv-token=--debug-single-value \
    --worker-env=PYPERFORMANCE_RUNID=pyperf-probe \
    --require-sitecustomize \
    --require-sitecustomize-prefix "$HOOK_DIR" \
    --require-cinderx-initialized \
    --require-jit-enabled \
    "${PYPERF_VENV_CHECK_ARGS[@]}" \
    --output "/root/work/arm-sync/pyperf_venv_${RUN_ID}_worker.json"

echo ">> smoke: JIT init + generator + regex compile"
# Keep startup smoke below known crash-prone aggressive thresholds while still
# exercising JIT-enabled initialization in the benchmark venv.
env PYTHONJITAUTO="$SMOKE_AUTOJIT" PYTHONPATH="$HOOK_DIR${PYTHONPATH:+:$PYTHONPATH}" CINDERX_ENABLE_SPECIALIZED_OPCODES="$CINDERX_ENABLE_SPECIALIZED_OPCODES" "$PYVENV_PATH/bin/python" -c 'g=(i for i in [1]); next(g, None); import re; re.compile("a+"); print("smoke-ok")'

run_extra_cmd "post pyperformance command" "$POST_PYPERF_CMD"

if [[ "$SKIP_DEFAULT_PYPERF_GATES" == "1" ]]; then
  echo "SKIP_DEFAULT_PYPERF_GATES=1 set; done after post-pyperf command."
  exit 0
fi

if [[ "$SKIP_PYPERF" == "1" ]]; then
  echo "SKIP_PYPERF=1 set; done after smoke."
  exit 0
fi

echo ">> pyperformance gate (jitlist, debug-single-value)"
. "$DRIVER_VENV/bin/activate"
JITLIST_ENTRIES="${CINDERX_JITLIST_ENTRIES:-__main__:*}"
env PYTHONPATH="$HOOK_DIR${PYTHONPATH:+:$PYTHONPATH}" CINDERX_JITLIST_ENTRIES="$JITLIST_ENTRIES" PYTHONJITENABLEJITLISTWILDCARDS=1 \
  python -m pyperformance run --debug-single-value -b "$BENCH" \
    --inherit-environ PYTHONPATH,CINDERX_JITLIST_ENTRIES,PYTHONJITENABLEJITLISTWILDCARDS,CINDERX_ENABLE_SPECIALIZED_OPCODES \
    -o "/root/work/arm-sync/${BENCH}_jitlist_${RUN_ID}.json"
deactivate

echo ">> pyperformance gate (auto-jit, debug-single-value)"
. "$DRIVER_VENV/bin/activate"
LOG="/tmp/jit_${BENCH}_autojit${AUTOJIT_GATE}_${RUN_ID}.log"
if [[ "$AUTOJIT_USE_JITLIST_FILTER" == "1" ]]; then
  AUTOJIT_JITLIST_ENTRIES="__main__:*"
  if [[ -n "$AUTOJIT_EXTRA_JITLIST" ]]; then
    AUTOJIT_JITLIST_ENTRIES="$AUTOJIT_JITLIST_ENTRIES,$AUTOJIT_EXTRA_JITLIST"
  fi
  echo "autojit_jitlist_entries=$AUTOJIT_JITLIST_ENTRIES"
  env PYTHONJITDISABLE=1 CINDERX_WORKER_PYTHONJITAUTO="$AUTOJIT_GATE" PYTHONPATH="$HOOK_DIR${PYTHONPATH:+:$PYTHONPATH}" PYTHONJITDEBUG=1 PYTHONJITLOGFILE="$LOG" \
    CINDERX_JITLIST_ENTRIES="$AUTOJIT_JITLIST_ENTRIES" PYTHONJITENABLEJITLISTWILDCARDS=1 \
    python -m pyperformance run --debug-single-value -b "$BENCH" \
      --inherit-environ PYTHONPATH,CINDERX_WORKER_PYTHONJITAUTO,PYTHONJITDEBUG,PYTHONJITLOGFILE,CINDERX_JITLIST_ENTRIES,PYTHONJITENABLEJITLISTWILDCARDS,CINDERX_ENABLE_SPECIALIZED_OPCODES \
      -o "/root/work/arm-sync/${BENCH}_autojit${AUTOJIT_GATE}_${RUN_ID}.json"
else
  env PYTHONJITDISABLE=1 CINDERX_WORKER_PYTHONJITAUTO="$AUTOJIT_GATE" PYTHONPATH="$HOOK_DIR${PYTHONPATH:+:$PYTHONPATH}" PYTHONJITDEBUG=1 PYTHONJITLOGFILE="$LOG" \
    python -m pyperformance run --debug-single-value -b "$BENCH" \
      --inherit-environ PYTHONPATH,CINDERX_WORKER_PYTHONJITAUTO,PYTHONJITDEBUG,PYTHONJITLOGFILE,CINDERX_ENABLE_SPECIALIZED_OPCODES \
      -o "/root/work/arm-sync/${BENCH}_autojit${AUTOJIT_GATE}_${RUN_ID}.json"
fi
deactivate

if [[ ! -s "$LOG" ]]; then
  echo "ERROR: missing/empty JIT log: $LOG"
  exit 1
fi
# Ensure the benchmark actually hit JIT compilation of benchmark code (not just stdlib imports).
MAIN_COMPILE_COUNT="$(grep -c "Finished compiling __main__:" "$LOG" || true)"
TOTAL_COMPILE_COUNT="$(grep -c "Finished compiling " "$LOG" || true)"
OTHER_COMPILE_COUNT=$((TOTAL_COMPILE_COUNT - MAIN_COMPILE_COUNT))
COMPILE_SUMMARY_JSON="/root/work/arm-sync/${BENCH}_autojit${AUTOJIT_GATE}_${RUN_ID}_compile_summary.json"
python - <<'PY' "$COMPILE_SUMMARY_JSON" "$BENCH" "$AUTOJIT_GATE" "$AUTOJIT_USE_JITLIST_FILTER" \
  "$MAIN_COMPILE_COUNT" "$TOTAL_COMPILE_COUNT" "$OTHER_COMPILE_COUNT" "$LOG"
import json
import sys

path = sys.argv[1]
payload = {
    "benchmark": sys.argv[2],
    "autojit_gate": int(sys.argv[3]),
    "use_jitlist_filter": bool(int(sys.argv[4])),
    "main_compile_count": int(sys.argv[5]),
    "total_compile_count": int(sys.argv[6]),
    "other_compile_count": int(sys.argv[7]),
    "jit_log_path": sys.argv[8],
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
    f.write("\n")
print(f"autojit_compile_summary={path}")
print(
    "autojit_compile_counts",
    f"total={payload['total_compile_count']}",
    f"main={payload['main_compile_count']}",
    f"other={payload['other_compile_count']}",
)
PY
if [[ "$MAIN_COMPILE_COUNT" -eq 0 ]]; then
  echo "ERROR: JIT did not compile any __main__ functions during '$BENCH' (JIT may not be active in benchmark workers)"
  echo "--- jit log tail ---"
  tail -n 120 "$LOG" || true
  exit 1
fi

echo "--- jit log tail ---"
tail -n 50 "$LOG" || true
