#!/usr/bin/env python3
import argparse
import importlib.util
import json
import statistics
import sys
import time
from pathlib import Path


BASE = Path(
    "/opt/python-3.14/lib/python3.14/site-packages/pyperformance/data-files/benchmarks"
)

BENCH_CONFIG = {
    "nbody": {
        "module": BASE / "bm_nbody" / "run_benchmark.py",
        "entry": "bench_nbody",
        "args": [1, "sun", 20000],
        "repeat": 1,
    },
    "float": {
        "module": BASE / "bm_float" / "run_benchmark.py",
        "entry": "benchmark",
        "args": [100000],
        "repeat": 3,
    },
    "raytrace": {
        "module": BASE / "bm_raytrace" / "run_benchmark.py",
        "entry": "bench_raytrace",
        "args": [1, 100, 100, None],
        "repeat": 1,
    },
    "go": {
        "module": BASE / "bm_go" / "run_benchmark.py",
        "entry": "versus_cpu",
        "args": [],
        "repeat": 2,
    },
    "fannkuch": {
        "module": BASE / "bm_fannkuch" / "run_benchmark.py",
        "entry": "fannkuch",
        "args": [9],
        "repeat": 1,
    },
    "nqueens": {
        "module": BASE / "bm_nqueens" / "run_benchmark.py",
        "entry": "bench_n_queens",
        "args": [8],
        "repeat": 3,
    },
    "deltablue": {
        "module": BASE / "bm_deltablue" / "run_benchmark.py",
        "entry": "delta_blue",
        "args": [100],
        "repeat": 100,
    },
}


def load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module spec: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_bench_once(bench_fn, args, repeat: int):
    for _ in range(repeat):
        bench_fn(*args)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--bench", choices=sorted(BENCH_CONFIG.keys()), required=True)
    p.add_argument("--mode", choices=["cpython", "cinderx"], required=True)
    p.add_argument("--warmup-rounds", type=int, default=20)
    p.add_argument("--rounds", type=int, default=35)
    p.add_argument("--repeat", type=int, default=-1)
    p.add_argument("--autojit", type=int, default=1)
    p.add_argument("--args-json", default="")
    p.add_argument("--wait-after-warmup", action="store_true")
    p.add_argument("--ready-marker", default="READY_FOR_PERF")
    p.add_argument("--gate-file", default="")
    p.add_argument("--gate-timeout-sec", type=int, default=0)
    args = p.parse_args()

    cfg = BENCH_CONFIG[args.bench]
    mod = load_module(cfg["module"], f"bm_{args.bench}_run_benchmark")
    bench_fn = getattr(mod, cfg["entry"])

    bench_args = json.loads(args.args_json) if args.args_json else list(cfg["args"])
    repeat = cfg["repeat"] if args.repeat < 0 else args.repeat

    if args.mode == "cinderx":
        import cinderx  # noqa: F401
        import cinderjit as cj

        cj.enable()
        if hasattr(cj, "compile_after_n_calls"):
            cj.compile_after_n_calls(args.autojit)
        if hasattr(cj, "enable_specialized_opcodes"):
            cj.enable_specialized_opcodes()

    for _ in range(args.warmup_rounds):
        run_bench_once(bench_fn, bench_args, repeat)

    if args.wait_after_warmup:
        print(args.ready_marker, flush=True)
        if args.gate_file:
            gate_path = Path(args.gate_file)
            deadline = None
            if args.gate_timeout_sec > 0:
                deadline = time.monotonic() + args.gate_timeout_sec
            while not gate_path.exists():
                if deadline is not None and time.monotonic() > deadline:
                    raise TimeoutError(f"timed out waiting gate file: {gate_path}")
                time.sleep(0.05)
        else:
            gate = sys.stdin.readline()
            if gate == "":
                raise RuntimeError("stdin closed before measurement phase gate")

    vals = []
    for _ in range(args.rounds):
        t0 = time.perf_counter()
        run_bench_once(bench_fn, bench_args, repeat)
        vals.append(time.perf_counter() - t0)

    out = {
        "bench": args.bench,
        "mode": args.mode,
        "warmup_rounds": args.warmup_rounds,
        "rounds": args.rounds,
        "autojit": args.autojit,
        "repeat": repeat,
        "bench_args": bench_args,
        "samples_s": vals,
        "mean_s": statistics.mean(vals),
        "min_s": min(vals),
        "max_s": max(vals),
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
