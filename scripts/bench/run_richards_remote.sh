#!/usr/bin/env bash
set -euo pipefail

DRIVER_VENV="${DRIVER_VENV:-/root/venv-cinderx314}"
OUT="${OUT:-/tmp/richards_samples.json}"
BENCH="${BENCH:-richards}"
SAMPLES="${SAMPLES:-5}"
AUTOJIT="${AUTOJIT:-50}"

PY="$DRIVER_VENV/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "ERROR: missing python at $PY"
  exit 2
fi

if [[ "$BENCH" != "richards" ]]; then
  echo "ERROR: this runner currently supports BENCH=richards only"
  exit 2
fi

cat >/tmp/jitlist_gate.txt <<'EOF'
__main__:*
EOF

PY="$PY" BENCH="$BENCH" SAMPLES="$SAMPLES" AUTOJIT="$AUTOJIT" OUT="$OUT" "$PY" - <<'PY'
import json
import os
import socket
import subprocess
import tempfile

py = os.environ["PY"]
bench = os.environ["BENCH"]
samples = int(os.environ["SAMPLES"])
autojit = os.environ["AUTOJIT"]
out = os.environ["OUT"]


def run_single(mode: str) -> float:
    env = os.environ.copy()
    inherit = []
    if mode == "nojit":
        env["PYTHONJITDISABLE"] = "1"
        env.pop("PYTHONJITAUTO", None)
        env.pop("PYTHONJITLISTFILE", None)
        env.pop("PYTHONJITENABLEJITLISTWILDCARDS", None)
        inherit = ["PYTHONJITDISABLE"]
    elif mode == "jitlist":
        env.pop("PYTHONJITDISABLE", None)
        env["PYTHONJITLISTFILE"] = "/tmp/jitlist_gate.txt"
        env["PYTHONJITENABLEJITLISTWILDCARDS"] = "1"
        env.pop("PYTHONJITAUTO", None)
        inherit = ["PYTHONJITLISTFILE", "PYTHONJITENABLEJITLISTWILDCARDS"]
    elif mode == "autojit50":
        env.pop("PYTHONJITDISABLE", None)
        env["PYTHONJITAUTO"] = str(autojit)
        env.pop("PYTHONJITLISTFILE", None)
        env.pop("PYTHONJITENABLEJITLISTWILDCARDS", None)
        inherit = ["PYTHONJITAUTO"]
    else:
        raise ValueError(f"unsupported mode: {mode}")

    tmp_json = tempfile.mktemp(prefix=f"richards_{mode}_", suffix=".json")
    cmd = [
        py,
        "-m",
        "pyperformance",
        "run",
        "--debug-single-value",
        "-b",
        bench,
        "--inherit-environ",
        ",".join(inherit),
        "-o",
        tmp_json,
    ]
    subprocess.check_call(cmd, env=env)
    with open(tmp_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    os.remove(tmp_json)
    return float(data["benchmarks"][0]["runs"][0]["values"][0])


payload = {
    "host": socket.gethostname(),
    "benchmark": bench,
    "samples_per_mode": samples,
    "autojit": int(autojit),
    "mode_samples": {"nojit": [], "jitlist": [], "autojit50": []},
}

for mode in ("nojit", "jitlist", "autojit50"):
    for _ in range(samples):
        payload["mode_samples"][mode].append(run_single(mode))

with open(out, "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2)
print(out)
PY
