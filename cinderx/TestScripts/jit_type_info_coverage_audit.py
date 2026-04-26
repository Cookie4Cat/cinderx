#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

"""Audit CPython 3.14 specialized opcode type-info coverage in CinderX.

The script joins three sources of truth:

* CPython's runtime opcode metadata (`opcode._specializations`,
  `_inline_cache_entries`, `_cache_format`).
* CinderX's static handling of specialized opcodes in bytecode intake and HIR.
* Dynamic specialized opcodes observed after warming representative workloads.

It writes JSON, CSV, and Markdown artifacts that can be used to pick the next
CPython 3.14 + CinderX JIT optimization target.
"""

from __future__ import annotations

import argparse
import csv
import dis
import importlib.util
import json
import opcode
from pathlib import Path
import re
import sys
import tempfile
import types
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable


HIGH_VALUE_CACHE_FIELDS = {
    "descr",
    "func_version",
    "index",
    "keys_version",
    "module_keys_version",
    "builtin_keys_version",
    "version",
}


@dataclass
class HIRUse:
    status: str
    actions: list[str] = field(default_factory=list)
    source_symbols: list[str] = field(default_factory=list)
    snippets: list[str] = field(default_factory=list)


def find_repo_root(start: Path) -> Path:
    cur = start.resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / "cinderx" / "Jit" / "bytecode.cpp").exists():
            return candidate
    raise RuntimeError(f"Unable to locate repo root from {start}")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def brace_block(text: str, open_brace: int) -> tuple[str, int]:
    depth = 0
    for idx in range(open_brace, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace + 1 : idx], idx + 1
    raise ValueError("unclosed brace block")


def cinderx_symbol_aliases(opname: str) -> set[str]:
    aliases = {opname}
    if opname.startswith("BINARY_OP_SUBSCR_"):
        aliases.add(opname.replace("BINARY_OP_SUBSCR_", "BINARY_SUBSCR_", 1))
    return aliases


def normalize_case_symbols(symbols: set[str]) -> set[str]:
    out = set(symbols)
    for symbol in list(symbols):
        out.update(cinderx_symbol_aliases(symbol))
    return out


def extract_preserved_from_text(text: str) -> set[str]:
    marker = "int BytecodeInstruction::specializedOpcode() const"
    start = text.find(marker)
    if start == -1:
        raise RuntimeError("specializedOpcode() not found")
    end = text.find("int BytecodeInstruction::oparg() const", start)
    if end == -1:
        end = len(text)
    body = text[start:end]
    return {
        match.group(1)
        for match in re.finditer(r"\bcase\s+([A-Z][A-Z0-9_]+)\s*:", body)
    }


def parse_bytecode_intake(repo_root: Path) -> dict[str, Any]:
    bytecode = read_text(repo_root / "cinderx" / "Jit" / "bytecode.cpp")
    preserved = sorted(extract_preserved_from_text(bytecode))
    return {
        "source": "cinderx/Jit/bytecode.cpp",
        "preserved_symbols": preserved,
        "preserved_symbols_with_aliases": sorted(normalize_case_symbols(set(preserved))),
    }


def switch_blocks_for_specialized_opcode(text: str) -> list[str]:
    blocks: list[str] = []
    needle = "switch (bc_instr.specializedOpcode())"
    pos = 0
    while True:
        idx = text.find(needle, pos)
        if idx == -1:
            return blocks
        open_brace = text.find("{", idx)
        block, end = brace_block(text, open_brace)
        blocks.append(block)
        pos = end


def classify_case_block(block: str) -> HIRUse:
    actions: list[str] = []
    if "GuardType" in block:
        actions.append("GuardType")
    if "GuardIs" in block:
        actions.append("GuardIs")
    if "JITRT_" in block or re.search(r"\bJITRT[A-Za-z0-9_]*", block):
        actions.append("JIT runtime helper")
    if "CallStatic" in block or "CallCFunc" in block or "CallInd" in block:
        actions.append("helper call")
    for emit in re.findall(r"tc\.emit(?:Checked)?<([A-Za-z0-9_]+)>", block):
        if emit not in {"GuardType", "GuardIs"}:
            actions.append(f"HIR:{emit}")
    actions = sorted(set(actions))

    if any(a in actions for a in ["JIT runtime helper", "helper call"]):
        status = "helper_lowering"
    elif any(a.startswith("HIR:") for a in actions):
        status = "dedicated_hir"
    elif "GuardType" in actions or "GuardIs" in actions:
        status = "guard_only"
    else:
        status = "ignored"
    snippet = " ".join(line.strip() for line in block.strip().splitlines()[:8])
    return HIRUse(status=status, actions=actions, snippets=[snippet])


def parse_hir_builder_consumption(repo_root: Path) -> dict[str, HIRUse]:
    builder = read_text(repo_root / "cinderx" / "Jit" / "hir" / "builder.cpp")
    uses: dict[str, HIRUse] = {}

    def merge_use(symbol: str, use: HIRUse) -> None:
        existing = uses.get(symbol)
        if existing is None:
            cloned = HIRUse(
                status=use.status,
                actions=list(use.actions),
                source_symbols=[symbol],
                snippets=list(use.snippets),
            )
            uses[symbol] = cloned
            return
        existing.actions = sorted(set(existing.actions + use.actions))
        existing.snippets.extend(use.snippets)
        rank = {
            "ignored": 0,
            "guard_only": 1,
            "dedicated_hir": 2,
            "helper_lowering": 3,
        }
        if rank[use.status] > rank[existing.status]:
            existing.status = use.status

    for switch in switch_blocks_for_specialized_opcode(builder):
        labels = list(
            re.finditer(
                r"(case\s+([A-Z][A-Z0-9_]+)\s*:|default\s*:)", switch
            )
        )
        pending_symbols: list[str] = []
        for idx, label in enumerate(labels):
            symbol = label.group(2)
            if symbol is not None:
                pending_symbols.append(symbol)
            start = label.end()
            end = labels[idx + 1].start() if idx + 1 < len(labels) else len(switch)
            block = switch[start:end]
            if not block.strip():
                continue
            use = classify_case_block(block)
            for pending_symbol in pending_symbols:
                merge_use(pending_symbol, use)
            pending_symbols = []

    comparison_re = re.compile(
        r"bc_instr\.specializedOpcode\(\)\s*==\s*([A-Z][A-Z0-9_]+)"
    )
    for match in comparison_re.finditer(builder):
        symbol = match.group(1)
        open_brace = builder.find("{", match.end(), match.end() + 300)
        next_semicolon = builder.find(";", match.end(), match.end() + 300)
        if open_brace != -1 and (next_semicolon == -1 or open_brace < next_semicolon):
            block, _ = brace_block(builder, open_brace)
        else:
            end = next_semicolon if next_semicolon != -1 else match.end() + 300
            block = builder[match.end() : end]
        merge_use(symbol, classify_case_block(block))
    return uses


def cache_format_for(base: str, spec: str) -> dict[str, int]:
    cache_format = getattr(opcode, "_cache_format", {})
    if hasattr(cache_format, "get"):
        fmt = cache_format.get(spec) or cache_format.get(base) or {}
    else:
        fmt = {}
    if isinstance(fmt, dict):
        return {str(k): int(v) for k, v in fmt.items()}
    return {}


def cache_entries_for(base: str, spec: str) -> int:
    entries = getattr(opcode, "_inline_cache_entries", {})
    if hasattr(entries, "get"):
        return int(entries.get(spec, entries.get(base, 0)) or 0)
    if isinstance(entries, (list, tuple)):
        opmap = getattr(opcode, "opmap", {})
        specialized_opmap = getattr(opcode, "_specialized_opmap", {})
        opnum = specialized_opmap.get(spec, opmap.get(base))
        if isinstance(opnum, int) and 0 <= opnum < len(entries):
            return int(entries[opnum] or 0)
    return 0


def infer_info_categories(name: str, base: str, fields: list[str]) -> list[str]:
    cats: set[str] = set()
    text = f"{base} {name}"
    if "LOAD_ATTR" in text or "STORE_ATTR" in text:
        cats.add("attr/layout")
    if "METHOD" in text or "descr" in fields:
        cats.add("descriptor/method")
    if "LOAD_GLOBAL" in text or "module_keys_version" in fields:
        cats.add("module/builtin dict")
    if "CALL" in text or "func_version" in fields:
        cats.add("call target")
    if "SUBSCR" in text:
        cats.add("container/index")
    if "BINARY_OP" in text and "SUBSCR" not in text:
        cats.add("numeric/string operand types")
    if "COMPARE_OP" in text:
        cats.add("comparison operand types")
    if "TO_BOOL" in text:
        cats.add("truthiness")
    if "FOR_ITER" in text:
        cats.add("iterator shape")
    if "UNPACK_SEQUENCE" in text:
        cats.add("sequence shape")
    if "CONTAINS_OP" in text:
        cats.add("membership container")
    if "LOAD_CONST" in text:
        cats.add("const lifetime")
    if not cats:
        cats.add("control/runtime")
    return sorted(cats)


def cpython_static_inventory() -> dict[str, Any]:
    specializations: dict[str, list[str]] = getattr(opcode, "_specializations", {})
    specialized_opmap: dict[str, int] = getattr(opcode, "_specialized_opmap", {})
    opmap: dict[str, int] = getattr(opcode, "opmap", {})
    entries: dict[str, Any] = {}
    for base, specs in sorted(specializations.items()):
        for spec in specs:
            fmt = cache_format_for(base, spec)
            fields = sorted(fmt)
            entries[spec] = {
                "opcode": spec,
                "base_opcode": base,
                "opcode_number": specialized_opmap.get(spec),
                "base_opcode_number": opmap.get(base),
                "cache_entries": cache_entries_for(base, spec),
                "cache_format": fmt,
                "cache_fields": fields,
                "info_categories": infer_info_categories(spec, base, fields),
            }
    return {
        "python": sys.version,
        "specialization_family_count": len(specializations),
        "specialized_opcode_count": len(entries),
        "families": {k: list(v) for k, v in sorted(specializations.items())},
        "entries": entries,
    }


def merge_static_coverage(repo_root: Path, cpython_inv: dict[str, Any]) -> dict[str, Any]:
    intake = parse_bytecode_intake(repo_root)
    hir_uses = parse_hir_builder_consumption(repo_root)
    preserved = set(intake["preserved_symbols_with_aliases"])
    coverage: dict[str, Any] = {}
    for spec, entry in cpython_inv["entries"].items():
        aliases = cinderx_symbol_aliases(spec)
        matched_intake = sorted(aliases & preserved)
        matched_hir = sorted(aliases & set(hir_uses))
        intake_status = "preserved" if matched_intake else "lost_at_intake"
        if matched_hir:
            hir_use = hir_uses[matched_hir[0]]
            hir_status = hir_use.status
            actions = hir_use.actions
        elif intake_status == "preserved":
            hir_status = "ignored"
            actions = []
        else:
            hir_status = "not_reached"
            actions = []

        fields = entry["cache_fields"]
        if intake_status == "lost_at_intake":
            payload = "none"
            lost_stage = "intake"
        elif hir_status in {"ignored", "not_reached"}:
            payload = "none"
            lost_stage = "HIR"
        elif hir_status == "guard_only":
            payload = "partial" if fields else "none"
            lost_stage = "HIR" if fields else "none"
        else:
            payload = "full" if fields else "partial"
            lost_stage = "none"

        coverage[spec] = {
            **entry,
            "cinderx_aliases": sorted(aliases),
            "matched_intake_symbols": matched_intake,
            "matched_hir_symbols": matched_hir,
            "intake_status": intake_status,
            "hir_consume_status": hir_status,
            "hir_actions": actions,
            "cache_payload_used": payload,
            "lost_stage": lost_stage,
        }
    return {
        "repo_root": str(repo_root),
        "bytecode_intake": intake,
        "hir_consumed_symbols": {
            key: {
                "status": value.status,
                "actions": value.actions,
                "snippets": value.snippets[:2],
            }
            for key, value in sorted(hir_uses.items())
        },
        "coverage": coverage,
    }


def collect_code_objects(fn: Callable[[], None], profiled_runs: int, warmup_runs: int):
    seen: dict[Any, dict[str, Any]] = {}

    def profiler(frame, event, arg):
        if event == "call":
            code = frame.f_code
            seen.setdefault(
                code,
                {
                    "filename": code.co_filename,
                    "name": code.co_name,
                    "qualname": getattr(code, "co_qualname", code.co_name),
                    "firstlineno": code.co_firstlineno,
                    "calls": 0,
                },
            )["calls"] += 1
        return profiler

    sys.setprofile(profiler)
    try:
        for _ in range(profiled_runs):
            fn()
    finally:
        sys.setprofile(None)

    for _ in range(warmup_runs):
        fn()
    return seen


def specialized_in_code(code, spec_names: set[str]) -> list[dict[str, Any]]:
    instrs = list(dis.get_instructions(code, adaptive=True, show_caches=True))
    out: list[dict[str, Any]] = []
    for idx, instr in enumerate(instrs):
        if instr.opname not in spec_names:
            continue
        caches: list[str] = []
        j = idx + 1
        while j < len(instrs) and instrs[j].opname == "CACHE":
            if instrs[j].argrepr:
                caches.append(instrs[j].argrepr)
            j += 1
        out.append(
            {
                "offset": instr.offset,
                "opname": instr.opname,
                "argrepr": instr.argrepr,
                "cache_argrepr": caches,
            }
        )
    return out


class MicroWorkloads:
    class AttrC:
        def __init__(self):
            self.x = 1

        def m(self):
            return self.x

    GLOBAL_VALUE = 42

    @staticmethod
    def attr_load_store():
        obj = MicroWorkloads.AttrC()

        def load(o):
            return o.x

        def store(o, value):
            o.x = value

        for i in range(2000):
            store(obj, i)
            load(obj)

    @staticmethod
    def method_call():
        obj = MicroWorkloads.AttrC()
        for _ in range(2000):
            obj.m()

    @staticmethod
    def global_load_call():
        def f():
            return MicroWorkloads.GLOBAL_VALUE + len([1, 2, 3])

        for _ in range(2000):
            f()

    @staticmethod
    def subscr():
        lst = [1, 2, 3]
        tup = (1, 2, 3)
        dct = {"x": 1}
        text = "abc"

        def f(i):
            return lst[i] + tup[i] + dct["x"] + (ord(text[i]) & 1)

        for i in range(2000):
            f(i % 3)

    @staticmethod
    def store_subscr():
        lst = [0, 0, 0]
        dct = {"x": 0}
        for i in range(2000):
            lst[i % 3] = i
            dct["x"] = i

    @staticmethod
    def binary_compare_bool():
        values = [1, 2, 3]

        def f(i, x, y):
            if values and i < x:
                return (x + y) * (x - y)
            return 0

        for i in range(2000):
            f(i % 3, i, i + 1)

    @staticmethod
    def for_iter_contains():
        total = 0
        data = [1, 2, 3, 4]
        lookup = {2, 4}
        for _ in range(1000):
            for item in data:
                if item in lookup:
                    total += item
        if total < 0:
            raise AssertionError(total)

    @staticmethod
    def call_shapes():
        def py_exact(a, b):
            return a + b

        class CallableObj:
            def __call__(self, x):
                return x

        obj = CallableObj()
        for i in range(2000):
            py_exact(i, i + 1)
            str(i)
            tuple([i])
            obj(i)


def ensure_cinderx_stub() -> None:
    try:
        import cinderx.jit  # noqa: F401
        return
    except Exception:
        pass
    cinderx_mod = types.ModuleType("cinderx")
    jit_mod = types.ModuleType("cinderx.jit")
    jit_mod.auto = lambda *args, **kwargs: None
    cinderx_mod.jit = jit_mod
    sys.modules.setdefault("cinderx", cinderx_mod)
    sys.modules.setdefault("cinderx.jit", jit_mod)


def load_module_from_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def repo_benchmark_workloads(repo_root: Path) -> dict[str, Callable[[], None]]:
    ensure_cinderx_stub()
    bench_dir = repo_root / "cinderx" / "benchmarks"
    workloads: dict[str, Callable[[], None]] = {}

    try:
        richards = load_module_from_path("audit_richards", bench_dir / "richards.py")
        workloads["repo_richards"] = lambda: richards.Richards().run(1)
    except Exception as exc:
        workloads["repo_richards_unavailable"] = lambda exc=exc: (_ for _ in ()).throw(exc)

    try:
        nbody = load_module_from_path("audit_nbody", bench_dir / "nbody.py")

        def run_nbody():
            bodies = [
                nbody.make_sun(),
                nbody.make_jupiter(),
                nbody.make_saturn(),
                nbody.make_uranus(),
                nbody.make_neptune(),
            ]
            nbody.offset_momentum(bodies)
            for _ in range(200):
                nbody.advance(bodies, 0.01, len(bodies))
            nbody.energy(bodies, len(bodies))

        workloads["repo_nbody_small"] = run_nbody
    except Exception as exc:
        workloads["repo_nbody_small_unavailable"] = lambda exc=exc: (_ for _ in ()).throw(exc)

    try:
        spectral = load_module_from_path(
            "audit_spectral_norm", bench_dir / "spectral_norm.py"
        )
        workloads["repo_spectral_norm_small"] = lambda: spectral.spectral_norm(60)
    except Exception as exc:
        workloads["repo_spectral_norm_small_unavailable"] = (
            lambda exc=exc: (_ for _ in ()).throw(exc)
        )

    try:
        fannkuch = load_module_from_path("audit_fannkuch", bench_dir / "fannkuch.py")
        workloads["repo_fannkuch_small"] = lambda: fannkuch.fannkuch(7)
    except Exception as exc:
        workloads["repo_fannkuch_small_unavailable"] = (
            lambda exc=exc: (_ for _ in ()).throw(exc)
        )

    return workloads


def pyperformance_style_workloads() -> dict[str, Callable[[], None]]:
    import json
    import pathlib
    import re

    payload = json.dumps(
        {
            "items": [
                {"name": "alpha", "value": i, "enabled": i % 2 == 0}
                for i in range(20)
            ]
        }
    )
    patterns = [r"([a-z]+)(\d*)", r"^/tmp/.+\.py$", r"\w+@\w+\.\w+"]

    def pathlib_probe():
        p = pathlib.PurePosixPath("/tmp/cinderx/a/b/c.py")
        for _ in range(1000):
            str(p.parent / "d.py")
            p.suffix
            p.name

    def json_loads_probe():
        for _ in range(1000):
            json.loads(payload)

    def regex_compile_probe():
        for _ in range(1000):
            for pattern in patterns:
                re.compile(pattern)

    return {
        "pyperf_style_pathlib": pathlib_probe,
        "pyperf_style_json_loads": json_loads_probe,
        "pyperf_style_regex_compile": regex_compile_probe,
        # pyperformance's deltablue is not imported directly in this first audit
        # because it lives inside pyperformance data-files and is runner-shaped.
    }


def workload_registry(repo_root: Path) -> dict[str, Callable[[], None]]:
    workloads: dict[str, Callable[[], None]] = {
        f"micro_{name}": getattr(MicroWorkloads, name)
        for name in [
            "attr_load_store",
            "method_call",
            "global_load_call",
            "subscr",
            "store_subscr",
            "binary_compare_bool",
            "for_iter_contains",
            "call_shapes",
        ]
    }
    workloads.update(repo_benchmark_workloads(repo_root))
    workloads.update(pyperformance_style_workloads())
    return workloads


def run_dynamic_inventory(
    repo_root: Path,
    selected: list[str] | None,
    profiled_runs: int,
    warmup_runs: int,
) -> dict[str, Any]:
    inv = cpython_static_inventory()
    spec_names = set(inv["entries"])
    spec_to_base = {
        spec: entry["base_opcode"] for spec, entry in inv["entries"].items()
    }
    registry = workload_registry(repo_root)
    if selected:
        missing = sorted(set(selected) - set(registry))
        if missing:
            raise RuntimeError(f"Unknown workloads: {', '.join(missing)}")
        names = selected
    else:
        names = sorted(registry)

    totals: Counter[str] = Counter()
    weighted_totals: Counter[str] = Counter()
    workload_results: dict[str, Any] = {}
    for name in names:
        fn = registry[name]
        try:
            seen = collect_code_objects(fn, profiled_runs, warmup_runs)
            opcode_counts: Counter[str] = Counter()
            weighted_opcode_counts: Counter[str] = Counter()
            functions: list[dict[str, Any]] = []
            for code, meta in seen.items():
                specs = specialized_in_code(code, spec_names)
                if not specs:
                    continue
                counter = Counter(item["opname"] for item in specs)
                calls = int(meta.get("calls", 0))
                weighted_counter = Counter(
                    {opname: count * calls for opname, count in counter.items()}
                )
                opcode_counts.update(counter)
                weighted_opcode_counts.update(weighted_counter)
                functions.append(
                    {
                        **meta,
                        "specialized_count": sum(counter.values()),
                        "weighted_specialized_count": sum(weighted_counter.values()),
                        "opcodes": dict(sorted(counter.items())),
                        "weighted_opcodes": dict(sorted(weighted_counter.items())),
                        "examples": specs[:8],
                    }
                )
            totals.update(opcode_counts)
            weighted_totals.update(weighted_opcode_counts)
            workload_results[name] = {
                "status": "ok",
                "opcode_counts": dict(sorted(opcode_counts.items())),
                "weighted_opcode_counts": dict(sorted(weighted_opcode_counts.items())),
                "top_functions": sorted(
                    functions,
                    key=lambda item: (
                        -item["weighted_specialized_count"],
                        -item["specialized_count"],
                        item["filename"],
                    ),
                )[:25],
            }
        except Exception as exc:
            workload_results[name] = {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "opcode_counts": {},
                "weighted_opcode_counts": {},
                "top_functions": [],
            }

    by_opcode: dict[str, Any] = {}
    for spec, count in sorted(totals.items()):
        by_opcode[spec] = {
            "count": count,
            "weighted_count": int(weighted_totals.get(spec, 0)),
            "base_opcode": spec_to_base.get(spec),
            "workloads": {
                name: result["opcode_counts"].get(spec, 0)
                for name, result in workload_results.items()
                if result["opcode_counts"].get(spec, 0)
            },
            "weighted_workloads": {
                name: result["weighted_opcode_counts"].get(spec, 0)
                for name, result in workload_results.items()
                if result["weighted_opcode_counts"].get(spec, 0)
            },
        }

    return {
        "python": sys.version,
        "profiled_runs": profiled_runs,
        "warmup_runs": warmup_runs,
        "workloads": workload_results,
        "by_opcode": by_opcode,
        "notes": [
            "deltablue pyperformance data-file integration is left as follow-up",
        ],
    }


def priority_for(row: dict[str, Any], dynamic_count: int) -> tuple[str, str]:
    fields = set(row["cache_fields"])
    high_value = bool(fields & HIGH_VALUE_CACHE_FIELDS) or any(
        cat in row["info_categories"]
        for cat in ["attr/layout", "descriptor/method", "call target", "module/builtin dict"]
    )
    hot = dynamic_count > 0
    intake = row["intake_status"]
    hir = row["hir_consume_status"]
    payload = row["cache_payload_used"]

    if hot and intake == "lost_at_intake" and high_value:
        return "P0", "hot specialized opcode is erased before HIR and carries high-value cache payload"
    if hot and intake == "lost_at_intake":
        return "P1", "hot specialized opcode is erased before HIR"
    if hot and hir in {"ignored", "not_reached"} and high_value:
        return "P1", "hot specialized opcode reaches CinderX weakly or not at all"
    if hot and hir == "guard_only" and payload != "full" and high_value:
        return "P1", "hot opcode is only used for guards while cache payload is richer"
    if not hot and intake == "lost_at_intake" and high_value:
        return "P2", "high-value specialization exists but was not observed hot in this audit"
    if hot:
        return "P2", "hot specialization already has partial coverage or lower-value payload"
    return "P3", "not observed hot in selected workloads"


def join_rows(
    cpython_inv: dict[str, Any],
    static_cov: dict[str, Any],
    dynamic_inv: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    dynamic_by_opcode = (dynamic_inv or {}).get("by_opcode", {})
    for spec, row in static_cov["coverage"].items():
        dyn = dynamic_by_opcode.get(spec, {})
        count = int(dyn.get("count", 0))
        weighted_count = int(dyn.get("weighted_count", 0))
        priority, reason = priority_for(row, count)
        rows.append(
            {
                **row,
                "dynamic_count": count,
                "dynamic_weighted_count": weighted_count,
                "dynamic_workloads": sorted((dyn.get("workloads") or {}).keys()),
                "priority": priority,
                "priority_reason": reason,
            }
        )
    priority_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    return sorted(
        rows,
        key=lambda item: (
            priority_rank[item["priority"]],
            -item["dynamic_weighted_count"],
            -item["dynamic_count"],
            item["base_opcode"],
            item["opcode"],
        ),
    )


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "priority",
        "opcode",
        "base_opcode",
        "dynamic_count",
        "dynamic_weighted_count",
        "dynamic_workloads",
        "cache_entries",
        "cache_fields",
        "info_categories",
        "intake_status",
        "hir_consume_status",
        "cache_payload_used",
        "lost_stage",
        "hir_actions",
        "priority_reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            out = {}
            for col in columns:
                val = row.get(col)
                if isinstance(val, list):
                    val = ";".join(str(x) for x in val)
                elif isinstance(val, dict):
                    val = json.dumps(val, sort_keys=True)
                out[col] = val
            writer.writerow(out)


def md_escape(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(x) for x in value) if value else "-"
    return str(value) if value not in (None, "") else "-"


def write_prioritized_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    actionable = [
        row
        for row in rows
        if row["priority"] in {"P0", "P1", "P2"}
        and row["cache_payload_used"] != "full"
    ]
    lines = [
        "# CinderX CPython 3.14 Type-Info Coverage Gaps",
        "",
        "Generated by `cinderx/TestScripts/jit_type_info_coverage_audit.py`.",
        "",
        "## Top Gaps",
        "",
    ]
    for idx, row in enumerate(actionable[:20], 1):
        lines.extend(
            [
                f"### {idx}. {row['opcode']} ({row['priority']})",
                "",
                f"- Opcode / family: `{row['opcode']}` / `{row['base_opcode']}`",
                f"- CPython 3.14 cache 信息: entries={row['cache_entries']}, fields={md_escape(row['cache_fields'])}",
                f"- 当前 CinderX 状态: intake={row['intake_status']}, HIR={row['hir_consume_status']}, payload={row['cache_payload_used']}",
                f"- Hot workloads 和频次: sites={row['dynamic_count']}, weighted={row['dynamic_weighted_count']}, workloads={md_escape(row['dynamic_workloads'])}",
                f"- 为什么可能有收益: {row['priority_reason']}",
                "- correctness fallback 边界: 保留 CPython generic runtime fallback；新增 fast path 必须 guard cache version / exact type / descriptor validity before use.",
                f"- 建议实现入口: `BytecodeInstruction::specializedOpcode()` + HIR builder `{row['base_opcode']}` lowering path.",
                "- 建议测试入口: Python semantic test + RuntimeTests HIR golden/runtime helper test + dynamic audit micro workload.",
                f"- 是否适合 ARM64 先验收益: {'yes' if row['dynamic_count'] and row['priority'] in {'P0', 'P1'} else 'maybe'}",
                "",
            ]
        )
    lines.extend(
        [
            "## Coverage Summary",
            "",
            "| priority | count |",
            "| --- | ---: |",
        ]
    )
    counts = Counter(row["priority"] for row in rows)
    for priority in ["P0", "P1", "P2", "P3"]:
        lines.append(f"| {priority} | {counts.get(priority, 0)} |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run_audit(args: argparse.Namespace) -> None:
    repo_root = find_repo_root(Path(args.repo_root))
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    cpython_inv = cpython_static_inventory()
    static_cov = merge_static_coverage(repo_root, cpython_inv)
    dynamic_inv = None
    if not args.skip_dynamic:
        selected = args.workloads.split(",") if args.workloads else None
        dynamic_inv = run_dynamic_inventory(
            repo_root,
            selected=selected,
            profiled_runs=args.profiled_runs,
            warmup_runs=args.warmup_runs,
        )

    rows = join_rows(cpython_inv, static_cov, dynamic_inv)

    write_json(output_dir / "cpython314-specializations.json", cpython_inv)
    write_json(output_dir / "cinderx-static-coverage.json", static_cov)
    if dynamic_inv is not None:
        write_json(output_dir / "dynamic-hot-specializations.json", dynamic_inv)
    write_csv(output_dir / "type-info-coverage.csv", rows)
    write_prioritized_markdown(output_dir / "prioritized-gaps.md", rows)

    print(f"wrote audit artifacts to {output_dir}")
    for priority, count in sorted(Counter(row["priority"] for row in rows).items()):
        print(f"{priority}: {count}")


def self_test() -> None:
    preserved = extract_preserved_from_text(
        """
        int BytecodeInstruction::specializedOpcode() const {
          switch (opcode) {
            case LOAD_ATTR_MODULE:
            case BINARY_OP_ADD_INT:
              return opcode;
            default:
              return unspecialize(opcode);
          }
        }
        int BytecodeInstruction::oparg() const { return 0; }
        """
    )
    assert preserved == {"LOAD_ATTR_MODULE", "BINARY_OP_ADD_INT"}, preserved

    builder = """
      switch (bc_instr.specializedOpcode()) {
        case LOAD_ATTR_INSTANCE_VALUE: {
          tc.emit<CallStatic>(1, out, JITRT_LoadAttrInstanceValue, TObject);
          break;
        }
        case BINARY_OP_MULTIPLY_INT:
        case BINARY_OP_ADD_INT:
          tc.emit<GuardType>(left, TLongExact, left, tc.frame);
          break;
        default:
          break;
      }
      if (bc_instr.specializedOpcode() == STORE_SUBSCR_DICT) {
        tc.emit<GuardType>(container, TDictExact, container, tc.frame);
      }
    """
    blocks = switch_blocks_for_specialized_opcode(builder)
    assert len(blocks) == 1
    cases = {}
    labels = list(re.finditer(r"(case\s+([A-Z][A-Z0-9_]+)\s*:|default\s*:)", blocks[0]))
    pending = []
    for idx, label in enumerate(labels):
        if label.group(2):
            pending.append(label.group(2))
        end = labels[idx + 1].start() if idx + 1 < len(labels) else len(blocks[0])
        block = blocks[0][label.end() : end]
        if block.strip():
            status = classify_case_block(block).status
            for symbol in pending:
                cases[symbol] = status
            pending = []
    assert cases["LOAD_ATTR_INSTANCE_VALUE"] == "helper_lowering", cases
    assert cases["BINARY_OP_ADD_INT"] == "guard_only", cases
    assert cases["BINARY_OP_MULTIPLY_INT"] == "guard_only", cases
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        repo = tmp / "jit_type_info_audit_selftest_repo"
        builder_path = repo / "cinderx" / "Jit" / "hir"
        bytecode_path = repo / "cinderx" / "Jit"
        builder_path.mkdir(parents=True, exist_ok=True)
        bytecode_path.mkdir(parents=True, exist_ok=True)
        (builder_path / "builder.cpp").write_text(builder, encoding="utf-8")
        (bytecode_path / "bytecode.cpp").write_text(
            "int BytecodeInstruction::specializedOpcode() const {"
            "switch (opcode) { case STORE_SUBSCR_DICT: return opcode; default: return unspecialize(opcode); }}"
            "int BytecodeInstruction::oparg() const { return 0; }",
            encoding="utf-8",
        )
        parsed = parse_hir_builder_consumption(repo)
        assert parsed["STORE_SUBSCR_DICT"].status == "guard_only", parsed
    print("self-test passed")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[2]),
        help="CinderX repository root to inspect",
    )
    parser.add_argument(
        "--output-dir",
        default="type-info-audit-results",
        help="Directory for JSON/CSV/Markdown artifacts",
    )
    parser.add_argument(
        "--workloads",
        default="",
        help="Comma-separated workload names. Defaults to all built-in workloads.",
    )
    parser.add_argument("--profiled-runs", type=int, default=1)
    parser.add_argument("--warmup-runs", type=int, default=20)
    parser.add_argument("--skip-dynamic", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    run_audit(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
