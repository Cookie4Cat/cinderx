#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

"""Collect evidence for CPython 3.14 CALL_PY_EXACT_ARGS specialization.

This script is intentionally small: it gives us a stable micro workload that
must specialize to CALL_PY_EXACT_ARGS before we try to consume that information
in CinderX's JIT.
"""

from __future__ import annotations

import argparse
import dis
import json
import sys
from collections import Counter
from types import CodeType, FunctionType
from typing import Any


def callee(a: int, b: int) -> int:
    return a + b


def call_arg(func: FunctionType, n: int) -> int:
    total = 0
    for i in range(n):
        total += func(i, i + 1)
    return total


def warmup(iterations: int) -> None:
    for _ in range(iterations):
        call_arg(callee, 32)


def code_objects(func: FunctionType) -> list[CodeType]:
    seen: set[CodeType] = set()
    todo = [func.__code__]
    out: list[CodeType] = []
    while todo:
        code = todo.pop()
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
        todo.extend(const for const in code.co_consts if isinstance(const, CodeType))
    return out


def instructions(code: CodeType) -> list[dict[str, Any]]:
    return [
        {
            "offset": instr.offset,
            "opname": instr.opname,
            "argrepr": instr.argrepr,
        }
        for instr in dis.get_instructions(
            code,
            adaptive=True,
            show_caches=True,
        )
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--warmup", type=int, default=2000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    warmup(args.warmup)

    records = []
    counts: Counter[str] = Counter()
    for code in code_objects(call_arg):
        instrs = instructions(code)
        for instr in instrs:
            if instr["opname"] != "CACHE":
                counts[instr["opname"]] += 1
        records.append(
            {
                "qualname": code.co_qualname,
                "instructions": instrs,
            }
        )

    payload = {
        "python": sys.version,
        "warmup": args.warmup,
        "counts": dict(counts),
        "has_call_py_exact_args": counts["CALL_PY_EXACT_ARGS"] > 0,
        "records": records,
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Python: {sys.version.split()[0]}")
        print(f"CALL_PY_EXACT_ARGS: {counts['CALL_PY_EXACT_ARGS']}")
        for record in records:
            print(f"\n{record['qualname']}:")
            for instr in record["instructions"]:
                if instr["opname"] == "CACHE":
                    continue
                print(
                    f"  {instr['offset']:>3} {instr['opname']:<32} "
                    f"{instr['argrepr']}"
                )

    return 0 if payload["has_call_py_exact_args"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
