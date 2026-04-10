import os
import sys


def _argv_tokens():
    toks = []
    orig = getattr(sys, "orig_argv", None)
    if orig:
        toks.extend([str(x) for x in orig])
    toks.extend([str(x) for x in getattr(sys, "argv", [])])
    return toks


def _is_truthy(value: str | None) -> bool:
    return value in {"1", "true", "TRUE", "yes", "YES", "on", "ON"}


tokens = _argv_tokens()
argv = getattr(sys, "argv", [])
argv0 = argv[0] if argv else ""


def _has_token(name: str) -> bool:
    return any(t == name for t in tokens)


def _has_suffix(suffix: str) -> bool:
    return any(t.endswith(suffix) for t in tokens)


def _contains(substr: str) -> bool:
    return any(substr in t for t in tokens)


skip = (
    _has_token("ensurepip")
    or _has_token("pip")
    or _has_suffix("get-pip.py")
    or argv0.endswith("get-pip.py")
    or _contains('run_module("pip"')
    or _contains("run_module('pip'")
)

# pyperformance 1.14 executes benchmark scripts directly and no longer passes
# the historical "--worker" argv token. Keep supporting the old shape, but
# also recognize the worker-specific run id environment.
worker = _has_token("--worker") or os.environ.get("PYPERFORMANCE_RUNID") not in (
    None,
    "",
)

if worker and not skip and os.environ.get("CINDERX_DISABLE") in (None, "", "0"):
    if os.environ.get("PYPERFORMANCE_RUNID"):
        # pyperf metadata collection can trip over os._Environ methods after
        # JIT-enabled startup. A plain dict avoids that worker-only bug.
        os.environ = dict(os.environ)

    # Keep the pyperformance driver process on the safe side by allowing it to
    # start with PYTHONJITDISABLE=1. Workers can still opt back into JIT by
    # inheriting a dedicated worker-only autojit setting.
    worker_autojit = os.environ.get("CINDERX_WORKER_PYTHONJITAUTO")
    if worker_autojit not in (None, ""):
        os.environ["PYTHONJITAUTO"] = worker_autojit
        os.environ.pop("PYTHONJITDISABLE", None)

    try:
        if os.environ.get("PYPERFORMANCE_RUNID"):
            import platform

            platform.architecture = (
                lambda executable=None, bits="", linkage="": ("64bit", "ELF")
            )

        import cinderx.jit as jit

        if os.environ.get("PYTHONJITDISABLE") in (None, "", "0"):
            jit.enable()
            if _is_truthy(os.environ.get("CINDERX_ENABLE_SPECIALIZED_OPCODES")):
                jit.enable_specialized_opcodes()
            entries = os.environ.get("CINDERX_JITLIST_ENTRIES", "")
            if entries:
                for entry in entries.split(","):
                    entry = entry.strip()
                    if entry:
                        jit.append_jit_list(entry)
    except Exception:
        pass
