#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _record_error(dst: dict[str, Any], key: str, exc: BaseException) -> None:
    dst[key] = {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": traceback.format_exc(),
    }


def _safe_find_spec(name: str) -> tuple[bool, str | None]:
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None, None
    except Exception as exc:  # pragma: no cover - debug probe
        # Some CinderX setups register cinderjit into sys.modules with
        # __spec__ = None during initialization.
        if name in sys.modules:
            return True, f"{type(exc).__name__}: {exc}"
        return False, f"{type(exc).__name__}: {exc}"


def _probe_sys_jit() -> dict[str, Any]:
    out: dict[str, Any] = {"present": hasattr(sys, "_jit")}
    if not out["present"]:
        return out

    jit = sys._jit  # type: ignore[attr-defined]
    for name in ("is_available", "is_enabled", "is_active"):
        if not hasattr(jit, name):
            out[name] = None
            continue
        fn = getattr(jit, name)
        try:
            out[name] = bool(fn())
        except Exception as exc:  # pragma: no cover - debug probe
            _record_error(out, f"{name}_error", exc)

    # Try to observe runtime "active" state while running a hot function.
    if hasattr(jit, "is_active"):
        def active_marker() -> int:
            return 1 if jit.is_active() else 0

        # Warm up for possible tier-up.
        for _ in range(50000):
            active_marker()

        active_hits = 0
        for _ in range(5000):
            active_hits += active_marker()
        out["active_hits_after_warmup"] = active_hits

    return out


def _payload(n: int = 1500) -> int:
    x = 0
    for i in range(n):
        x += (i * 3) ^ (i >> 2)
    return x


def _ensure_cinderx_initialized(out: dict[str, Any]) -> None:
    import cinderx  # noqa: F401

    out["cinderx_module"] = str(cinderx.__file__)
    init_fn = getattr(cinderx, "init", None)
    is_initialized_fn = getattr(cinderx, "is_initialized", None)
    if callable(is_initialized_fn):
        out["cinderx_initialized_before"] = bool(is_initialized_fn())
    if callable(init_fn):
        try:
            init_fn()
            out["cinderx_init_called"] = True
        except Exception as exc:  # pragma: no cover - debug probe
            _record_error(out, "cinderx_init_error", exc)
    if callable(is_initialized_fn):
        out["cinderx_initialized_after"] = bool(is_initialized_fn())


def _probe_cinderjit() -> dict[str, Any]:
    out: dict[str, Any] = {
        "pre_find_spec_cinderjit": False,
        "post_find_spec_cinderjit": False,
        "import_cinderjit_ok": False,
        "apis": {},
    }

    pre_found, pre_find_err = _safe_find_spec("cinderjit")
    out["pre_find_spec_cinderjit"] = pre_found
    if pre_find_err:
        out["pre_find_spec_cinderjit_note"] = pre_find_err

    try:
        _ensure_cinderx_initialized(out)
        import cinderx.jit as cinderx_jit
        out["cinderx_jit_module"] = str(getattr(cinderx_jit, "__file__", ""))
        out["import_cinderx_jit_ok"] = True
    except Exception as exc:  # pragma: no cover - debug probe
        _record_error(out, "import_cinderx_jit_error", exc)

    post_found, post_find_err = _safe_find_spec("cinderjit")
    out["post_find_spec_cinderjit"] = post_found
    if post_find_err:
        out["post_find_spec_cinderjit_note"] = post_find_err

    try:
        import cinderjit
        out["import_cinderjit_ok"] = True
        out["cinderjit_module"] = str(getattr(cinderjit, "__file__", "<builtin>"))
    except Exception as exc:  # pragma: no cover - debug probe
        _record_error(out, "import_cinderjit_error", exc)
        return out

    # API shape
    api_names = (
        "enable",
        "disable",
        "compile_after_n_calls",
        "force_compile",
        "is_jit_compiled",
        "get_compiled_size",
        "get_compiled_functions",
        "disassemble",
        "dump_elf",
    )
    for name in api_names:
        out["apis"][name] = hasattr(cinderjit, name)

    # Prepare runtime
    try:
        if hasattr(cinderjit, "enable"):
            cinderjit.enable()
            out["enable_called"] = True
        if hasattr(cinderjit, "compile_after_n_calls"):
            cinderjit.compile_after_n_calls(1)
            out["compile_after_n_calls_set"] = 1
    except Exception as exc:  # pragma: no cover - debug probe
        _record_error(out, "jit_config_error", exc)

    fn = _payload
    out["payload_name"] = fn.__qualname__

    # Warmup to allow auto JIT + runtime counting.
    for _ in range(10000):
        fn(500)

    # Force compile if available.
    if hasattr(cinderjit, "force_compile"):
        try:
            out["force_compile_result"] = bool(cinderjit.force_compile(fn))
        except Exception as exc:  # pragma: no cover - debug probe
            _record_error(out, "force_compile_error", exc)

    if hasattr(cinderjit, "is_jit_compiled"):
        try:
            out["is_jit_compiled"] = bool(cinderjit.is_jit_compiled(fn))
        except Exception as exc:  # pragma: no cover - debug probe
            _record_error(out, "is_jit_compiled_error", exc)

    if hasattr(cinderjit, "get_compiled_size"):
        try:
            out["get_compiled_size"] = int(cinderjit.get_compiled_size(fn))
        except Exception as exc:  # pragma: no cover - debug probe
            _record_error(out, "get_compiled_size_error", exc)

    if hasattr(cinderjit, "get_compiled_functions"):
        try:
            funcs = cinderjit.get_compiled_functions()
            out["get_compiled_functions_count"] = len(funcs)
            out["payload_in_compiled_functions"] = any(
                getattr(f, "__code__", None) is fn.__code__ for f in funcs
            )
        except Exception as exc:  # pragma: no cover - debug probe
            _record_error(out, "get_compiled_functions_error", exc)

    if hasattr(cinderjit, "disassemble"):
        try:
            cinderjit.disassemble(fn)
            out["disassemble_called"] = True
        except Exception as exc:  # pragma: no cover - debug probe
            _record_error(out, "disassemble_error", exc)

    if hasattr(cinderjit, "dump_elf"):
        elf_path = Path(f"/tmp/cinderjit_probe_{os.getpid()}.elf")
        try:
            cinderjit.dump_elf(str(elf_path))
            out["dump_elf_path"] = str(elf_path)
            out["dump_elf_exists"] = elf_path.exists()
            out["dump_elf_size"] = elf_path.stat().st_size if elf_path.exists() else -1
        except Exception as exc:  # pragma: no cover - debug probe
            _record_error(out, "dump_elf_error", exc)

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe CinderX/CPython JIT features")
    parser.add_argument("--label", default="", help="Result label for grouping runs")
    parser.add_argument("--output", default="", help="Write JSON result to this path")
    args = parser.parse_args()

    result: dict[str, Any] = {
        "timestamp": _now_iso(),
        "label": args.label,
        "python": {
            "executable": sys.executable,
            "version": sys.version,
            "prefix": sys.prefix,
            "base_prefix": getattr(sys, "base_prefix", ""),
            "argv": sys.argv,
        },
        "env": {
            "PYTHONJIT": os.environ.get("PYTHONJIT"),
            "PYTHONJITAUTO": os.environ.get("PYTHONJITAUTO"),
            "PYTHON_JIT": os.environ.get("PYTHON_JIT"),
            "CINDERX_DISABLE": os.environ.get("CINDERX_DISABLE"),
        },
    }

    result["sys_jit"] = _probe_sys_jit()
    try:
        result["cinderjit_probe"] = _probe_cinderjit()
    except Exception as exc:  # pragma: no cover - debug probe
        probe_err: dict[str, Any] = {}
        _record_error(probe_err, "fatal_cinderjit_probe_error", exc)
        result["cinderjit_probe"] = probe_err

    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
