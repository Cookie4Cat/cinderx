#!/usr/bin/env python3
"""Direct-run a pyperformance benchmark module under selectable JIT strategies."""

import argparse
import dis
import importlib.util
import inspect
import json
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


def collect_functions(module):
    funcs = []
    seen = set()

    def add(fn):
        ident = id(fn)
        if ident not in seen:
            seen.add(ident)
            funcs.append(fn)

    for value in module.__dict__.values():
        if inspect.isfunction(value) and getattr(value, "__module__", None) == module.__name__:
            add(value)
        elif inspect.isclass(value) and getattr(value, "__module__", None) == module.__name__:
            for member in value.__dict__.values():
                if inspect.isfunction(member) and getattr(member, "__module__", None) == module.__name__:
                    add(member)
    return funcs


def has_backedge(fn) -> bool:
    return any(ins.opname == "JUMP_BACKWARD" for ins in dis.get_instructions(fn))


def aggregate_deopts(events):
    grouped = {}
    for event in events:
        key = (
            event["normal"].get("func_qualname"),
            event["int"].get("lineno"),
            event["normal"].get("description"),
            event["normal"].get("reason"),
        )
        grouped[key] = grouped.get(key, 0) + int(event["int"].get("count", 0))

    rows = []
    for (qualname, lineno, description, reason), count in grouped.items():
        rows.append(
            {
                "qualname": qualname,
                "lineno": lineno,
                "description": description,
                "reason": reason,
                "count": count,
            }
        )
    rows.sort(key=lambda row: row["count"], reverse=True)
    return rows


def choose_candidates(functions, strategy: str, explicit_names: set[str]):
    if strategy == "none":
        return []
    if strategy == "all":
        return functions
    if strategy == "backedge":
        return [fn for fn in functions if has_backedge(fn)]
    if strategy == "names":
        return [fn for fn in functions if fn.__qualname__ in explicit_names]
    raise ValueError(f"unsupported strategy: {strategy}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module-path", required=True)
    parser.add_argument("--module-name", default="bench_module")
    parser.add_argument("--bench-func", required=True)
    parser.add_argument("--bench-args-json", default="[]")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--prewarm-runs", type=int, default=0)
    parser.add_argument(
        "--compile-strategy",
        choices=["none", "all", "backedge", "names"],
        default="none",
    )
    parser.add_argument(
        "--compile-names",
        default="",
        help="Comma-separated qualnames when --compile-strategy=names",
    )
    parser.add_argument("--specialized-opcodes", action="store_true")
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
    jit.compile_after_n_calls(1000000)

    functions = collect_functions(module)
    explicit_names = {
        name.strip() for name in args.compile_names.split(",") if name.strip()
    }
    candidates = choose_candidates(functions, args.compile_strategy, explicit_names)

    for _ in range(args.prewarm_runs):
        bench(*bench_args)

    compiled = []
    for fn in candidates:
        try:
            ok = bool(jit.force_compile(fn))
        except Exception:
            ok = False
        if ok:
            compiled.append(fn.__qualname__)

    samples = []
    all_deopts = []
    for _ in range(args.samples):
        jit.get_and_clear_runtime_stats()
        t0 = time.perf_counter()
        bench_return = bench(*bench_args)
        wall = time.perf_counter() - t0
        stats = jit.get_and_clear_runtime_stats()
        samples.append({"bench_return_sec": bench_return, "wall_sec": wall})
        all_deopts.extend(stats.get("deopt", []))

    payload = {
        "module_path": str(module_path),
        "bench_func": args.bench_func,
        "bench_args": bench_args,
        "compile_strategy": args.compile_strategy,
        "specialized_opcodes": args.specialized_opcodes,
        "prewarm_runs": args.prewarm_runs,
        "candidate_count": len(functions),
        "selected_compile_count": len(candidates),
        "compiled_count": len(compiled),
        "compiled_qualnames": compiled,
        "samples": samples,
        "median_wall_sec": statistics.median(sample["wall_sec"] for sample in samples),
        "min_wall_sec": min(sample["wall_sec"] for sample in samples),
        "total_deopt_count": sum(int(event["int"].get("count", 0)) for event in all_deopts),
        "top_deopts": aggregate_deopts(all_deopts)[:12],
    }

    text = json.dumps(payload, indent=2, ensure_ascii=False)
    print(text)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
