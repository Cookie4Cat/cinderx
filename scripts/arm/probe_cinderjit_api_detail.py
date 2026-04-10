#!/usr/bin/env python3
"""Detailed CinderJIT API probe for ARM validation and report generation."""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import cinderx.jit as jit
import cinderjit


def payload(n: int) -> int:
    s = 0
    for i in range(n):
        s += (i * 3) ^ (i >> 2)
    return s


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    out: dict[str, Any] = {
        "api_presence": {
            "get_compiled_size": hasattr(cinderjit, "get_compiled_size"),
            "disassemble": hasattr(cinderjit, "disassemble"),
            "get_compiled_function": hasattr(cinderjit, "get_compiled_function"),
            "get_compiled_functions": hasattr(cinderjit, "get_compiled_functions"),
            "dump_elf": hasattr(cinderjit, "dump_elf"),
        }
    }

    jit.enable()
    jit.compile_after_n_calls(1000000)
    for _ in range(20000):
        payload(250)
    out["force_compile"] = bool(jit.force_compile(payload))
    out["is_jit_compiled"] = bool(jit.is_jit_compiled(payload))

    if out["api_presence"]["get_compiled_size"]:
        out["compiled_size"] = int(cinderjit.get_compiled_size(payload))
    if hasattr(cinderjit, "get_compiled_stack_size"):
        out["stack_size"] = int(cinderjit.get_compiled_stack_size(payload))
    if hasattr(cinderjit, "get_compiled_spill_stack_size"):
        out["spill_stack_size"] = int(cinderjit.get_compiled_spill_stack_size(payload))

    if out["api_presence"]["get_compiled_functions"]:
        funcs = cinderjit.get_compiled_functions()
        out["compiled_functions_count"] = len(funcs)
        out["payload_in_compiled_functions"] = any(
            getattr(f, "__code__", None) is payload.__code__ for f in funcs
        )

    if out["api_presence"]["disassemble"]:
        try:
            ret = cinderjit.disassemble(payload)
            out["disassemble_return_type"] = type(ret).__name__
        except Exception as exc:
            out["disassemble_error"] = f"{type(exc).__name__}:{exc}"

    if out["api_presence"]["dump_elf"]:
        with tempfile.TemporaryDirectory() as td:
            elf = Path(td) / "cinderjit_dump.elf"
            cinderjit.dump_elf(str(elf))
            hdr = elf.read_bytes()[:64]
            out["dump_elf"] = {
                "path": str(elf),
                "size": elf.stat().st_size,
                "elf_magic": hdr[:4].hex(),
                "elf_e_machine": int.from_bytes(hdr[18:20], "little"),
            }
            readelf = subprocess.run(
                ["readelf", "-h", str(elf)], capture_output=True, text=True
            )
            out["dump_elf"]["readelf_machine_line"] = next(
                (line.strip() for line in readelf.stdout.splitlines() if "Machine:" in line),
                "",
            )

    text = json.dumps(out, ensure_ascii=False, indent=2)
    print(text)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
