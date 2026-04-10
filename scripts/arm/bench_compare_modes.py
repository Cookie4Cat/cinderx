#!/usr/bin/env python3
"""Compare CinderX and CPython JIT/interpreter modes on the same workload."""

import argparse
import dis
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path


def workload(n: int) -> int:
    s = 0
    for i in range(n):
        s += (i * 3) ^ (i >> 2)
    return s


def time_calls(fn, n: int, calls: int, repeats: int):
    times = []
    check = None
    for _ in range(repeats):
        t0 = time.perf_counter()
        x = 0
        for _ in range(calls):
            x ^= fn(n)
        t1 = time.perf_counter()
        times.append(t1 - t0)
        check = x
    return times, check


def cinderx_mode(mode: str, n: int, warmup: int, calls: int, repeats: int):
    import cinderx.jit as jit
    try:
        import cinderjit  # type: ignore[import-not-found]
    except Exception:
        cinderjit = None

    jit_disabled = str(os.environ.get("PYTHONJITDISABLE", "")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if mode == "jit" and jit_disabled:
        raise RuntimeError(
            "cinderx jit mode requested but PYTHONJITDISABLE is set"
        )

    # Keep interpreter measurements free of JIT metadata side effects.
    collect_jit_metadata = mode == "jit"

    if not jit_disabled:
        jit.enable()
        # Keep interpreter mode interpreted by default.
        jit.compile_after_n_calls(1000000)
        jit.force_uncompile(workload)

    api_flags = {
        "cinderjit_available": cinderjit is not None,
        "get_compiled_size": cinderjit is not None
        and hasattr(cinderjit, "get_compiled_size"),
        "get_compiled_function": cinderjit is not None
        and hasattr(cinderjit, "get_compiled_function"),
        "get_compiled_functions": cinderjit is not None
        and hasattr(cinderjit, "get_compiled_functions"),
        "disassemble": cinderjit is not None and hasattr(cinderjit, "disassemble"),
        "dump_elf": cinderjit is not None and hasattr(cinderjit, "dump_elf"),
    }

    for _ in range(warmup):
        workload(n)

    forced = False
    if mode == "jit":
        forced = bool(jit.force_compile(workload))

    compiled = bool(jit.is_jit_compiled(workload)) if collect_jit_metadata else False
    compiled_size = (
        int(jit.get_compiled_size(workload))
        if collect_jit_metadata and compiled
        else 0
    )
    stack_size = (
        int(cinderjit.get_compiled_stack_size(workload))
        if collect_jit_metadata
        and compiled
        and cinderjit is not None
        and hasattr(cinderjit, "get_compiled_stack_size")
        else 0
    )
    spill_stack_size = (
        int(cinderjit.get_compiled_spill_stack_size(workload))
        if collect_jit_metadata
        and compiled
        and cinderjit is not None
        and hasattr(cinderjit, "get_compiled_spill_stack_size")
        else 0
    )

    disassemble_ok = "skipped_interp_mode" if not collect_jit_metadata else None
    if collect_jit_metadata and api_flags["disassemble"] and cinderjit is not None:
        try:
            cinderjit.disassemble(workload)
            disassemble_ok = True
        except Exception as exc:
            disassemble_ok = f"error:{type(exc).__name__}:{exc}"

    dump_elf_info = (
        {"ok": False, "error": "skipped_interp_mode"}
        if not collect_jit_metadata
        else None
    )
    if collect_jit_metadata and api_flags["dump_elf"] and cinderjit is not None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "jit_dump.elf"
            try:
                cinderjit.dump_elf(str(path))
                hdr = path.read_bytes()[:64]
                ei_data = hdr[5] if len(hdr) > 6 else 0
                byteorder = (
                    "little" if ei_data == 1 else "big" if ei_data == 2 else "unknown"
                )
                e_machine = (
                    int.from_bytes(hdr[18:20], byteorder)
                    if len(hdr) >= 20 and byteorder != "unknown"
                    else -1
                )
                dump_elf_info = {
                    "ok": True,
                    "path_size": path.stat().st_size,
                    "elf_magic": hdr[:4].hex(),
                    "elf_e_machine": e_machine,
                }
            except Exception as exc:
                dump_elf_info = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}

    times, check = time_calls(workload, n=n, calls=calls, repeats=repeats)
    return {
        "runtime": "cinderx",
        "mode": mode,
        "python": sys.version,
        "env": {
            "PYTHONJIT": os.environ.get("PYTHONJIT"),
            "PYTHONJITAUTO": os.environ.get("PYTHONJITAUTO"),
            "PYTHONJITDISABLE": os.environ.get("PYTHONJITDISABLE"),
            "ENABLE_ADAPTIVE_STATIC_PYTHON": os.environ.get(
                "ENABLE_ADAPTIVE_STATIC_PYTHON"
            ),
            "ENABLE_LIGHTWEIGHT_FRAMES": os.environ.get("ENABLE_LIGHTWEIGHT_FRAMES"),
        },
        "warmup": warmup,
        "calls": calls,
        "n": n,
        "repeats": repeats,
        "jit_disabled": jit_disabled,
        "forced_compile": forced,
        "is_jit_compiled": compiled,
        "compiled_size": compiled_size,
        "stack_size": stack_size,
        "spill_stack_size": spill_stack_size,
        "times_sec": times,
        "median_sec": statistics.median(times),
        "min_sec": min(times),
        "check": check,
        "api_flags": api_flags,
        "disassemble_ok": disassemble_ok,
        "dump_elf": dump_elf_info,
    }


def _best_backedge_offset(fn):
    offsets = [ins.offset for ins in dis.get_instructions(fn) if ins.opname == "JUMP_BACKWARD"]
    if not offsets:
        return None
    return max(offsets)


def cpython_mode(mode: str, n: int, warmup: int, calls: int, repeats: int):
    import _opcode

    if mode == "jit":
        for _ in range(warmup):
            workload(n)

    # Keep interpreter measurements free of executor probing side effects.
    offset = None
    executor = None
    executor_error = "skipped_interp_mode"
    jit_code_len = 0
    if mode == "jit":
        offset = _best_backedge_offset(workload)
        executor_error = None
        if offset is not None:
            try:
                executor = _opcode.get_executor(workload.__code__, offset)
            except Exception as exc:
                executor_error = f"{type(exc).__name__}:{exc}"

        if executor is not None and hasattr(executor, "get_jit_code"):
            try:
                jit_code_len = len(executor.get_jit_code())
            except Exception:
                jit_code_len = 0

    exec_info = {
        "offset": offset,
        "exists": executor is not None,
        "is_valid": (
            bool(getattr(executor, "is_valid", lambda: False)())
            if executor is not None
            else False
        ),
        "jit_code_size": int(getattr(executor, "jit_code_size", 0))
        if executor is not None
        else 0,
        "jit_code_len": jit_code_len,
        "error": executor_error,
    }

    times, check = time_calls(workload, n=n, calls=calls, repeats=repeats)
    return {
        "runtime": "cpython",
        "mode": mode,
        "python": sys.version,
        "env": {"PYTHON_JIT": os.environ.get("PYTHON_JIT")},
        "warmup": warmup,
        "calls": calls,
        "n": n,
        "repeats": repeats,
        "executor": exec_info,
        "times_sec": times,
        "median_sec": statistics.median(times),
        "min_sec": min(times),
        "check": check,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", choices=["cinderx", "cpython"], required=True)
    parser.add_argument("--mode", choices=["interp", "jit"], required=True)
    parser.add_argument("--n", type=int, default=250)
    parser.add_argument("--warmup", type=int, default=20000)
    parser.add_argument("--calls", type=int, default=12000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    if args.runtime == "cinderx":
        result = cinderx_mode(args.mode, args.n, args.warmup, args.calls, args.repeats)
    else:
        result = cpython_mode(args.mode, args.n, args.warmup, args.calls, args.repeats)

    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
