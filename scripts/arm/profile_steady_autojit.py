#!/usr/bin/env python3
"""Warm a benchmark under auto-JIT, then run a steady-state phase for profiling.

This is intended for perf sampling of compiled code only:
1) warm until the compiled-function set stabilizes,
2) optionally pause briefly to let an external profiler attach,
3) run the benchmark repeatedly for a fixed steady-state duration.
"""

import argparse
import importlib.util
import json
import os
import statistics
import time
from pathlib import Path


def load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect_compiled_qualnames(jit, module_path: Path) -> list[str]:
    names = []
    compiled = jit.get_compiled_functions()
    for fn in compiled:
        code = getattr(fn, "__code__", None)
        qualname = getattr(fn, "__qualname__", None)
        if code is None or qualname is None:
            continue
        if Path(code.co_filename) != module_path:
            continue
        names.append(qualname)
    return sorted(set(names))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module-path", required=True)
    parser.add_argument("--module-name", default="bench_module")
    parser.add_argument("--bench-func", required=True)
    parser.add_argument("--bench-args-json", default="[]")
    parser.add_argument("--autojit", type=int, default=50)
    parser.add_argument("--warmup-min-runs", type=int, default=30)
    parser.add_argument("--stabilize-rounds", type=int, default=8)
    parser.add_argument("--attach-wait-seconds", type=float, default=3.0)
    parser.add_argument("--steady-seconds", type=float, default=12.0)
    parser.add_argument("--specialized-opcodes", action="store_true")
    parser.add_argument("--ready-file", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    module_path = Path(args.module_path)
    module = load_module(module_path, args.module_name)
    bench = getattr(module, args.bench_func)
    bench_args = json.loads(args.bench_args_json)

    import cinderx.jit as jit

    jit.enable()
    if args.specialized_opcodes:
        jit.enable_specialized_opcodes()
    else:
        jit.disable_specialized_opcodes()
    jit.compile_after_n_calls(args.autojit)

    pid = os.getpid()
    stable_rounds = 0
    warmup_runs = 0
    prev_compiled = None
    warmup_samples = []

    while True:
        t0 = time.perf_counter()
        bench(*bench_args)
        warmup_samples.append(time.perf_counter() - t0)
        warmup_runs += 1

        compiled = collect_compiled_qualnames(jit, module_path)
        if compiled == prev_compiled:
            stable_rounds += 1
        else:
            stable_rounds = 0
            prev_compiled = compiled

        if warmup_runs >= args.warmup_min_runs and stable_rounds >= args.stabilize_rounds:
            break

    ready = {
        "pid": pid,
        "warmup_runs": warmup_runs,
        "stable_rounds": stable_rounds,
        "compiled_count": len(prev_compiled or []),
        "compiled_qualnames": prev_compiled or [],
        "median_warmup_sec": statistics.median(warmup_samples),
    }
    text = json.dumps(ready, ensure_ascii=False, indent=2)
    print(text, flush=True)

    if args.ready_file:
        ready_file = Path(args.ready_file)
        ready_file.parent.mkdir(parents=True, exist_ok=True)
        ready_file.write_text(text + "\n", encoding="utf-8")

    if args.attach_wait_seconds > 0:
        time.sleep(args.attach_wait_seconds)

    iterations = 0
    steady_samples = []
    all_deopts = []
    end = time.perf_counter() + args.steady_seconds
    while time.perf_counter() < end:
        jit.get_and_clear_runtime_stats()
        t0 = time.perf_counter()
        bench(*bench_args)
        wall = time.perf_counter() - t0
        stats = jit.get_and_clear_runtime_stats()
        steady_samples.append(wall)
        all_deopts.extend(stats.get("deopt", []))
        iterations += 1

    result = {
        "pid": pid,
        "autojit": args.autojit,
        "module_path": str(module_path),
        "bench_func": args.bench_func,
        "bench_args": bench_args,
        "warmup_runs": warmup_runs,
        "compiled_count": len(prev_compiled or []),
        "compiled_qualnames": prev_compiled or [],
        "steady_iterations": iterations,
        "steady_seconds": args.steady_seconds,
        "median_steady_sec": statistics.median(steady_samples) if steady_samples else None,
        "min_steady_sec": min(steady_samples) if steady_samples else None,
        "total_deopt_count": sum(int(event["int"].get("count", 0)) for event in all_deopts),
    }
    out_text = json.dumps(result, ensure_ascii=False, indent=2)
    print(out_text, flush=True)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out_text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
