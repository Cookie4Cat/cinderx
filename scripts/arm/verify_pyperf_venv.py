#!/usr/bin/env python3
"""Validate a pyperformance benchmark venv and optionally probe worker startup."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def parse_pyvenv_cfg(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def parse_env_overrides(entries: list[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for entry in entries:
        key, sep, value = entry.partition("=")
        key = key.strip()
        if not key or not sep:
            raise ValueError(f"invalid worker env override: {entry!r}")
        env[key] = value
    return env


def worker_probe(
    python_exe: Path,
    argv_tokens: list[str],
    env_overrides: dict[str, str] | None = None,
) -> dict[str, object]:
    code = r"""
import json
import os
import site
import sys

payload = {
    "executable": sys.executable,
    "prefix": sys.prefix,
    "base_prefix": getattr(sys, "base_prefix", ""),
    "site_packages": site.getsitepackages(),
    "sitecustomize_loaded": "sitecustomize" in sys.modules,
    "sitecustomize_path": (
        getattr(sys.modules.get("sitecustomize"), "__file__", None)
        if "sitecustomize" in sys.modules
        else None
    ),
    "argv": sys.argv,
    "orig_argv": getattr(sys, "orig_argv", []),
    "PYPERFORMANCE_RUNID": os.environ.get("PYPERFORMANCE_RUNID"),
    "PYTHONJITAUTO": os.environ.get("PYTHONJITAUTO"),
    "PYTHONJITDISABLE": os.environ.get("PYTHONJITDISABLE"),
    "CINDERX_JITLIST_ENTRIES": os.environ.get("CINDERX_JITLIST_ENTRIES"),
    "CINDERX_ENABLE_SPECIALIZED_OPCODES": os.environ.get(
        "CINDERX_ENABLE_SPECIALIZED_OPCODES"
    ),
}

try:
    import cinderx
    import cinderx.jit as jit

    payload["cinderx_initialized"] = bool(cinderx.is_initialized())
    payload["jit_enabled"] = bool(jit.is_enabled())
except Exception as exc:
    payload["probe_error"] = f"{type(exc).__name__}:{exc}"

print(json.dumps(payload, ensure_ascii=False))
"""
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    proc = subprocess.run(
        [str(python_exe), "-c", code, *argv_tokens],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    result: dict[str, object] = {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    if proc.returncode == 0:
        try:
            result["summary"] = json.loads(proc.stdout.strip() or "{}")
        except json.JSONDecodeError as exc:
            result["decode_error"] = f"{type(exc).__name__}:{exc}"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--venv", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--probe-worker", action="store_true")
    parser.add_argument("--worker-argv-token", action="append", default=[])
    parser.add_argument("--worker-env", action="append", default=[])
    parser.add_argument("--require-system-site-packages", action="store_true")
    parser.add_argument("--require-sitecustomize", action="store_true")
    parser.add_argument("--require-sitecustomize-prefix", default="")
    parser.add_argument("--require-cinderx-initialized", action="store_true")
    parser.add_argument("--require-jit-enabled", action="store_true")
    args = parser.parse_args()

    venv = Path(args.venv).resolve()
    pyvenv_cfg = venv / "pyvenv.cfg"
    python_exe = venv / "bin" / "python"

    result: dict[str, object] = {
        "venv": str(venv),
        "pyvenv_cfg": str(pyvenv_cfg),
        "python": str(python_exe),
        "exists": venv.is_dir(),
        "pyvenv_cfg_exists": pyvenv_cfg.is_file(),
        "python_exists": python_exe.is_file(),
    }
    errors: list[str] = []

    cfg: dict[str, str] = {}
    include_system_site_packages = ""
    if pyvenv_cfg.is_file():
        cfg = parse_pyvenv_cfg(pyvenv_cfg)
        include_system_site_packages = cfg.get("include-system-site-packages", "")
    result["pyvenv_cfg_values"] = cfg
    result["include_system_site_packages"] = include_system_site_packages

    if not venv.is_dir():
        errors.append(f"venv missing: {venv}")
    if not pyvenv_cfg.is_file():
        errors.append(f"pyvenv.cfg missing: {pyvenv_cfg}")
    if not python_exe.is_file():
        errors.append(f"venv python missing: {python_exe}")
    if (
        args.require_system_site_packages
        and include_system_site_packages.lower() != "true"
    ):
        errors.append(
            "pyperformance venv must set include-system-site-packages = true"
        )

    worker_env_overrides: dict[str, str] = {}
    try:
        worker_env_overrides = parse_env_overrides(list(args.worker_env))
    except ValueError as exc:
        errors.append(str(exc))

    if args.probe_worker and python_exe.is_file():
        probe = worker_probe(
            python_exe,
            list(args.worker_argv_token),
            env_overrides=worker_env_overrides,
        )
        result["worker_probe"] = probe
        summary = probe.get("summary")
        if probe.get("returncode") != 0:
            errors.append(
                f"worker probe failed with return code {probe.get('returncode')}"
            )
        elif not isinstance(summary, dict):
            errors.append("worker probe did not produce a JSON summary")
        else:
            sitecustomize_path = summary.get("sitecustomize_path")
            if args.require_sitecustomize:
                if not summary.get("sitecustomize_loaded"):
                    errors.append("sitecustomize was not loaded in the worker")
                elif not isinstance(sitecustomize_path, str):
                    errors.append("sitecustomize path missing from worker probe")
                elif not args.require_sitecustomize_prefix:
                    try:
                        resolved = str(Path(sitecustomize_path).resolve())
                    except OSError:
                        resolved = str(sitecustomize_path)
                    if not resolved.startswith(str(venv)):
                        errors.append(
                            "sitecustomize did not load from the pyperformance venv"
                        )
            if args.require_sitecustomize_prefix:
                if not isinstance(sitecustomize_path, str):
                    errors.append("sitecustomize path missing from worker probe")
                else:
                    try:
                        resolved = str(Path(sitecustomize_path).resolve())
                    except OSError:
                        resolved = str(sitecustomize_path)
                    expected = str(
                        Path(args.require_sitecustomize_prefix).resolve()
                    )
                    if not resolved.startswith(expected):
                        errors.append(
                            "sitecustomize did not load from the expected prefix"
                        )
            if args.require_cinderx_initialized and not summary.get(
                "cinderx_initialized"
            ):
                errors.append("cinderx was not initialized in the worker")
            if args.require_jit_enabled and not summary.get("jit_enabled"):
                errors.append("jit was not enabled in the worker")

    result["ok"] = not errors
    result["errors"] = errors

    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
