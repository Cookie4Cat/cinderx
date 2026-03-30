import os
import sys
import site
import importlib.util
import sysconfig


def _spec_summary(name: str) -> str:
    try:
        spec = importlib.util.find_spec(name)
    except Exception as err:
        return f"<error {err!r}>"
    if spec is None:
        return "<missing>"
    return (
        f"name={spec.name!r} "
        f"origin={getattr(spec, 'origin', None)!r} "
        f"loader={type(getattr(spec, 'loader', None)).__name__!r}"
    )


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


def _debug(msg: str) -> None:
    path = os.environ.get("CINDERX_HOOK_DEBUGFILE")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _candidate_site_packages() -> list[str]:
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    base_prefix = getattr(sys, "base_prefix", None) or sys.prefix
    prefixes = [base_prefix]
    if sys.prefix not in prefixes:
        prefixes.append(sys.prefix)

    candidates: list[str] = []
    for prefix in prefixes:
        libdir = os.path.join(prefix, "lib", f"python{version}", "site-packages")
        platstdlib = os.path.join(
            prefix, "lib", f"python{version}", "lib-dynload", "site-packages"
        )
        for path in (libdir, platstdlib):
            if path not in candidates:
                candidates.append(path)

    for key in ("purelib", "platlib"):
        try:
            path = sysconfig.get_path(
                key,
                vars={
                    "base": base_prefix,
                    "platbase": base_prefix,
                    "installed_base": base_prefix,
                    "installed_platbase": base_prefix,
                },
            )
        except Exception:
            path = None
        if path and path not in candidates:
            candidates.append(path)

    return [path for path in candidates if path and os.path.isdir(path)]


def _ensure_cinderx_import_path() -> None:
    if importlib.util.find_spec("cinderx") is not None:
        return

    added = []
    for path in _candidate_site_packages():
        before = set(sys.path)
        site.addsitedir(path)
        if path not in before or set(sys.path) != before:
            added.append(path)

    _debug(
        "path_fixup"
        f" pid={os.getpid()}"
        f" added={added!r}"
        f" cinderx_spec={_spec_summary('cinderx')}"
    )


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
) or _has_suffix("run_benchmark.py") or _contains("/pyperformance/data-files/benchmarks/")

_debug(
    "pre"
    f" pid={os.getpid()}"
    f" worker={worker}"
    f" skip={skip}"
    f" runid={os.environ.get('PYPERFORMANCE_RUNID')!r}"
    f" pyjitdisable={os.environ.get('PYTHONJITDISABLE')!r}"
    f" pythonautojit={os.environ.get('PYTHONJITAUTO')!r}"
    f" worker_autojit={os.environ.get('CINDERX_WORKER_PYTHONJITAUTO')!r}"
    f" pythonpath={os.environ.get('PYTHONPATH')!r}"
    f" ld_library_path={os.environ.get('LD_LIBRARY_PATH')!r}"
    f" executable={sys.executable!r}"
    f" prefix={getattr(sys, 'prefix', None)!r}"
    f" base_prefix={getattr(sys, 'base_prefix', None)!r}"
    f" path0_4={list(getattr(sys, 'path', [])[:4])!r}"
    f" _cinderx_spec={_spec_summary('_cinderx')}"
    f" cinderjit_spec={_spec_summary('cinderjit')}"
    f" has__cinderx={'_cinderx' in sys.modules}"
    f" has_cinderjit={'cinderjit' in sys.modules}"
    f" argv0={argv0!r}"
)

if worker and not skip and os.environ.get("CINDERX_DISABLE") in (None, "", "0"):
    if os.environ.get("PYPERFORMANCE_RUNID"):
        # pyperf metadata collection can trip over os._Environ methods after
        # JIT-enabled startup. A plain dict avoids that worker-only bug.
        os.environ = dict(os.environ)

    # Worker 进程无条件移除 PYTHONJITDISABLE，避免 driver 的禁用状态泄漏
    # 到 benchmark worker。
    os.environ.pop("PYTHONJITDISABLE", None)
    os.unsetenv("PYTHONJITDISABLE")

    # 优先使用 worker 专用阈值，回退到通用 PYTHONJITAUTO。
    worker_autojit = os.environ.get("CINDERX_WORKER_PYTHONJITAUTO")
    if worker_autojit not in (None, ""):
        os.environ["PYTHONJITAUTO"] = worker_autojit
        os.putenv("PYTHONJITAUTO", worker_autojit)

    try:
        _ensure_cinderx_import_path()
        if os.environ.get("PYPERFORMANCE_RUNID"):
            import platform

            platform.architecture = (
                lambda executable=None, bits="", linkage="": ("64bit", "ELF")
            )

        import cinderx
        _debug(
            "cinderx_state"
            f" pid={os.getpid()}"
            f" module={getattr(cinderx, '__file__', '<none>')!r}"
            f" initialized={getattr(cinderx, 'is_initialized', lambda: None)()!r}"
            f" import_error={getattr(cinderx, 'get_import_error', lambda: None)()!r}"
            f" _cinderx_spec={_spec_summary('_cinderx')}"
            f" cinderjit_spec={_spec_summary('cinderjit')}"
            f" has__cinderx={'_cinderx' in sys.modules}"
            f" has_cinderjit={'cinderjit' in sys.modules}"
        )
        try:
            import _cinderx  # noqa: F401

            _debug(
                f"_cinderx_import_ok pid={os.getpid()}"
                f" has__cinderx={'_cinderx' in sys.modules}"
            )
        except Exception as import_err:
            _debug(
                f"_cinderx_import_fail pid={os.getpid()}"
                f" err={import_err!r}"
                f" spec={_spec_summary('_cinderx')}"
            )

        import cinderx.jit as jit
        _debug(
            "jit_module"
            f" pid={os.getpid()}"
            f" module={getattr(jit, '__file__', '<builtin>')}"
        )
        try:
            import cinderjit  # noqa: F401

            _debug(
                f"cinderjit_import_ok pid={os.getpid()}"
                f" has_cinderjit={'cinderjit' in sys.modules}"
            )
        except Exception as import_err:
            _debug(
                f"cinderjit_import_fail pid={os.getpid()}"
                f" err={import_err!r}"
                f" spec={_spec_summary('cinderjit')}"
                f" has_cinderjit={'cinderjit' in sys.modules}"
            )

        _debug(
            "before_enable"
            f" pid={os.getpid()}"
            f" enabled={getattr(jit, 'is_enabled', lambda: None)()!r}"
            f" threshold={getattr(jit, 'get_compile_after_n_calls', lambda: None)()!r}"
            f" pythonpath={os.environ.get('PYTHONPATH')!r}"
            f" ld_library_path={os.environ.get('LD_LIBRARY_PATH')!r}"
        )
        jit.enable()
        autojit_env = os.environ.get("CINDERX_WORKER_PYTHONJITAUTO") or os.environ.get(
            "PYTHONJITAUTO"
        )
        if autojit_env not in (None, ""):
            jit.auto()
            try:
                jit.compile_after_n_calls(int(autojit_env))
            except Exception:
                pass
        _debug(
            "after_enable"
            f" pid={os.getpid()}"
            f" enabled={getattr(jit, 'is_enabled', lambda: None)()!r}"
            f" threshold={getattr(jit, 'get_compile_after_n_calls', lambda: None)()!r}"
            f" autojit_env={autojit_env!r}"
        )
        if _is_truthy(os.environ.get("CINDERX_ENABLE_SPECIALIZED_OPCODES")):
            jit.enable_specialized_opcodes()
        entries = os.environ.get("CINDERX_JITLIST_ENTRIES", "")
        if entries:
            for entry in entries.split(","):
                entry = entry.strip()
                if entry:
                    jit.append_jit_list(entry)
        _debug(
            "done"
            f" pid={os.getpid()}"
            f" entries={bool(entries)}"
            f" specialized={_is_truthy(os.environ.get('CINDERX_ENABLE_SPECIALIZED_OPCODES'))}"
        )
    except Exception as err:
        _debug(f"exception pid={os.getpid()} err={err!r}")
        pass
