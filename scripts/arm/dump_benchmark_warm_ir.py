#!/usr/bin/env python3
"""Warm up a benchmark, probe hot targets, then dump HIR/LIR/ASM."""

import argparse
import importlib.util
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_PYTHON = "/opt/python-3.14/bin/python3.14"
DEFAULT_BENCH_BASE = Path(
    "/opt/python-3.14/lib/python3.14/site-packages/pyperformance/data-files/benchmarks"
)

BENCH_PROFILES = {
    "nbody": {
        "warmup_func": "bench_nbody",
        "warmup_args_json": "[1, \"sun\", 20000]",
        "probe_targets_csv": "bench_nbody,advance,report_energy",
        "extract_targets_csv": "bench_nbody,advance",
    },
    "float": {
        "warmup_func": "benchmark",
        "warmup_args_json": "[100000]",
        "probe_targets_csv": "benchmark,maximize,Point.normalize,Point.maximize",
        "extract_targets_csv": "benchmark",
    },
    "raytrace": {
        "warmup_func": "bench_raytrace",
        "warmup_args_json": "[1, 100, 100, null]",
        "probe_targets_csv": "bench_raytrace,Scene.render,Scene.rayColour,SimpleSurface.colourAt",
        "extract_targets_csv": "bench_raytrace",
    },
    "go": {
        "warmup_func": "versus_cpu",
        "warmup_args_json": "[]",
        "probe_targets_csv": "versus_cpu,computer_move,UCTNode.play,Board.useful",
        "extract_targets_csv": "computer_move",
    },
    "fannkuch": {
        "warmup_func": "fannkuch",
        "warmup_args_json": "[9]",
        "probe_targets_csv": "fannkuch",
        "extract_targets_csv": "fannkuch",
    },
    "nqueens": {
        "warmup_func": "bench_n_queens",
        "warmup_args_json": "[8]",
        "probe_targets_csv": "bench_n_queens,n_queens,permutations",
        "extract_targets_csv": "bench_n_queens,n_queens",
    },
    "deltablue": {
        "warmup_func": "delta_blue",
        "warmup_args_json": "[100]",
        "probe_targets_csv": "delta_blue,chain_test,projection_test",
        "extract_targets_csv": "delta_blue",
    },
}


def load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module spec: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def iter_module_callables(module):
    seen = set()
    for value in module.__dict__.values():
        if inspect.isfunction(value) and getattr(value, "__module__", None) == module.__name__:
            ident = id(value)
            if ident not in seen:
                seen.add(ident)
                yield value
        elif inspect.isclass(value) and getattr(value, "__module__", None) == module.__name__:
            for member in value.__dict__.values():
                if inspect.isfunction(member) and getattr(member, "__module__", None) == module.__name__:
                    ident = id(member)
                    if ident not in seen:
                        seen.add(ident)
                        yield member


def resolve_callable(module, name: str):
    if not name:
        raise ValueError("empty callable name")

    # Fast path: direct attribute chain lookup such as "Board.useful".
    obj = module
    try:
        for part in name.split("."):
            obj = getattr(obj, part)
        if callable(obj):
            return obj
    except AttributeError:
        pass

    # Fallback: match by __qualname__ or __name__.
    for fn in iter_module_callables(module):
        if fn.__qualname__ == name or fn.__name__ == name:
            return fn

    raise AttributeError(f"callable not found: {name}")


def parse_csv(text: str):
    return [item.strip() for item in text.split(",") if item.strip()]


def find_and_slice(lines, start_re: re.Pattern, end_re: re.Pattern):
    start_idx = -1
    for i, line in enumerate(lines):
        if start_re.search(line):
            start_idx = i
            break
    if start_idx < 0:
        return []

    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        if end_re.search(lines[i]) and not start_re.search(lines[i]):
            end_idx = i
            break
    return lines[start_idx:end_idx]


def write_lines(path: Path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(lines)
    path.write_text(text, encoding="utf-8")


def extract_hir(module_name: str, target: str, hir_log: Path, out_path: Path):
    lines = hir_log.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    base = re.escape(f"Optimized HIR for {module_name}:")
    start = re.compile(rf"Optimized HIR for {re.escape(module_name)}:{re.escape(target)}:")
    end = re.compile(rf"{base}")
    slice_lines = find_and_slice(lines, start, end)
    write_lines(out_path, slice_lines)
    return len(slice_lines)


def extract_lir(module_name: str, target: str, lir_log: Path, out_path: Path):
    lines = lir_log.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    base = re.escape(f"LIR for {module_name}:")
    start = re.compile(rf"LIR for {re.escape(module_name)}:{re.escape(target)}\b")
    end = re.compile(rf"{base}")
    slice_lines = find_and_slice(lines, start, end)
    write_lines(out_path, slice_lines)
    return len(slice_lines)


def extract_asm(module_name: str, target: str, asm_txt: Path, out_path: Path):
    lines = asm_txt.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    start = re.compile(rf"^[0-9a-fA-F]+\s+<{re.escape(module_name)}:{re.escape(target)}>:\s*$")
    end = re.compile(r"^[0-9a-fA-F]+\s+<[^>]+>:\s*$")
    slice_lines = find_and_slice(lines, start, end)
    write_lines(out_path, slice_lines)
    return len(slice_lines)


def run_worker(args):
    if not args.warmup_func:
        raise ValueError("--warmup-func is required in worker mode")
    if not args.warmup_args_json:
        args.warmup_args_json = "[]"

    import cinderx  # noqa: F401
    import cinderjit as cj

    cj.enable()
    if hasattr(cj, "enable_specialized_opcodes"):
        cj.enable_specialized_opcodes()

    module = load_module(Path(args.module_path), args.module_name)
    warmup_fn = resolve_callable(module, args.warmup_func)
    warmup_args = json.loads(args.warmup_args_json)

    for _ in range(args.warmup_rounds):
        warmup_fn(*warmup_args)

    target_names = parse_csv(args.probe_targets_csv) or [args.warmup_func]
    target_status = []
    unresolved_targets = []
    for name in target_names:
        try:
            fn = resolve_callable(module, name)
            compiled = None
            if hasattr(cj, "is_jit_compiled"):
                compiled = bool(cj.is_jit_compiled(fn))
            target_status.append(
                {
                    "name": name,
                    "is_jit_compiled": compiled,
                }
            )
        except Exception as exc:
            unresolved_targets.append({"name": name, "reason": repr(exc)})

    if args.dump_elf:
        cj.dump_elf(args.dump_elf)

    payload = {
        "module_path": args.module_path,
        "module_name": args.module_name,
        "warmup_func": args.warmup_func,
        "warmup_args": warmup_args,
        "warmup_rounds": args.warmup_rounds,
        "autojit": args.autojit,
        "probe_targets": target_names,
        "target_status": target_status,
        "unresolved_targets": unresolved_targets,
        "dump_elf": args.dump_elf,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def run_phase(cmd, env, stdout_path: Path, stderr_path: Path):
    proc = subprocess.run(cmd, env=env, check=False, capture_output=True, text=True)
    stdout_path.write_text(proc.stdout, encoding="utf-8")
    stderr_path.write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"phase failed rc={proc.returncode}: {' '.join(cmd)}")
    payload = None
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            payload = json.loads(line)
            break
    if payload is None:
        raise RuntimeError("worker did not return JSON payload")
    return payload


def disassemble_elf(elf_path: Path, out_path: Path):
    llvm_objdump = shutil.which("llvm-objdump")
    objdump = shutil.which("objdump")
    tool = llvm_objdump or objdump
    if tool is None:
        raise RuntimeError("neither llvm-objdump nor objdump is available")
    proc = subprocess.run([tool, "-d", str(elf_path)], check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"disassemble failed rc={proc.returncode}: {tool}")
    out_path.write_text(proc.stdout, encoding="utf-8")
    return tool


def resolve_module_path(benchmark: str, module_path: str):
    if module_path:
        return Path(module_path)
    if not benchmark:
        raise ValueError("either --benchmark or --module-path is required")
    return DEFAULT_BENCH_BASE / f"bm_{benchmark}" / "run_benchmark.py"


def apply_profile_defaults(args):
    if not args.benchmark:
        return
    profile = BENCH_PROFILES.get(args.benchmark)
    if profile is None:
        return

    if not args.warmup_func:
        args.warmup_func = profile["warmup_func"]
    if not args.warmup_args_json:
        args.warmup_args_json = profile["warmup_args_json"]
    if not args.probe_targets_csv:
        args.probe_targets_csv = profile["probe_targets_csv"]
    if not args.extract_targets_csv:
        args.extract_targets_csv = profile["extract_targets_csv"]


def orchestrate(args):
    apply_profile_defaults(args)
    if not args.warmup_func:
        raise ValueError("--warmup-func is required unless --benchmark has a built-in profile")
    if not args.warmup_args_json:
        args.warmup_args_json = "[]"

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    module_path = resolve_module_path(args.benchmark, args.module_path)
    module_name = args.module_name or (
        f"bm_{args.benchmark}_run_benchmark" if args.benchmark else "bench_module"
    )
    probe_targets = args.probe_targets_csv or args.warmup_func
    extract_targets = parse_csv(args.extract_targets_csv) or parse_csv(probe_targets)

    this_file = Path(__file__).resolve()
    base_cmd = [
        args.python,
        str(this_file),
        "--worker",
        "--module-path",
        str(module_path),
        "--module-name",
        module_name,
        "--warmup-func",
        args.warmup_func,
        "--warmup-args-json",
        args.warmup_args_json,
        "--warmup-rounds",
        str(args.warmup_rounds),
        "--autojit",
        str(args.autojit),
        "--probe-targets-csv",
        probe_targets,
    ]

    summary = {
        "benchmark": args.benchmark,
        "module_path": str(module_path),
        "module_name": module_name,
        "warmup_func": args.warmup_func,
        "warmup_args_json": args.warmup_args_json,
        "warmup_rounds": args.warmup_rounds,
        "autojit": args.autojit,
        "probe_targets_csv": probe_targets,
        "extract_targets": extract_targets,
        "phases": {},
    }

    env_base = os.environ.copy()
    env_base["PYTHONJITAUTO"] = str(args.autojit)

    env_hir = env_base.copy()
    env_hir["PYTHONJITDUMPFINALHIR"] = "1"
    env_hir["PYTHONJITLOGFILE"] = str(outdir / "hir.log")
    summary["phases"]["hir"] = run_phase(
        base_cmd,
        env_hir,
        outdir / "hir.stdout.txt",
        outdir / "hir.stderr.txt",
    )

    env_lir = env_base.copy()
    env_lir["PYTHONJITDUMPLIR"] = "1"
    env_lir["PYTHONJITLOGFILE"] = str(outdir / "lir.log")
    summary["phases"]["lir"] = run_phase(
        base_cmd,
        env_lir,
        outdir / "lir.stdout.txt",
        outdir / "lir.stderr.txt",
    )

    elf_path = outdir / "jit.elf"
    asm_cmd = [*base_cmd, "--dump-elf", str(elf_path)]
    summary["phases"]["asm"] = run_phase(
        asm_cmd,
        env_base.copy(),
        outdir / "elf.stdout.txt",
        outdir / "elf.stderr.txt",
    )

    asm_path = outdir / "asm.from_elf.txt"
    tool = disassemble_elf(elf_path, asm_path)
    summary["asm_disassembler"] = tool

    extracted = {}
    for target in extract_targets:
        target_key = target.replace(".", "_")
        hir_path = outdir / f"{target_key}.hir.txt"
        lir_path = outdir / f"{target_key}.lir.txt"
        asm_slice_path = outdir / f"{target_key}.asm.txt"
        extracted[target] = {
            "hir_lines": extract_hir(module_name, target, outdir / "hir.log", hir_path),
            "lir_lines": extract_lir(module_name, target, outdir / "lir.log", lir_path),
            "asm_lines": extract_asm(module_name, target, asm_path, asm_slice_path),
            "hir_file": str(hir_path),
            "lir_file": str(lir_path),
            "asm_file": str(asm_slice_path),
        }
    summary["extracted"] = extracted

    summary_path = outdir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--worker", action="store_true")
    p.add_argument("--python", default=DEFAULT_PYTHON)
    p.add_argument("--benchmark", default="")
    p.add_argument("--module-path", default="")
    p.add_argument("--module-name", default="")
    p.add_argument("--warmup-func", default="")
    p.add_argument("--warmup-args-json", default="")
    p.add_argument("--warmup-rounds", type=int, default=8)
    p.add_argument("--autojit", type=int, default=50)
    p.add_argument("--probe-targets-csv", default="")
    p.add_argument("--extract-targets-csv", default="")
    p.add_argument("--dump-elf", default="")
    p.add_argument("--outdir", default="/root/work/jit_dump_generic")
    return p.parse_args()


def main():
    args = parse_args()
    if args.worker:
        return run_worker(args)
    return orchestrate(args)


if __name__ == "__main__":
    raise SystemExit(main())
