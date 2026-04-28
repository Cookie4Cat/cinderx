#!/usr/bin/env python3
"""Run local CinderX merge gates."""

from __future__ import annotations

import argparse
import datetime as _datetime
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tomllib
from typing import Any


def find_repo_root() -> Path:
    path = Path(__file__).resolve()
    for parent in path.parents:
        if (parent / "CMakeLists.txt").exists() and (parent / "cinderx").is_dir():
            return parent
    raise RuntimeError("could not find repository root")


REPO_ROOT = find_repo_root()
TESTGATE_DIR = REPO_ROOT / "cinderx" / "TestGate"
SUITES_DIR = TESTGATE_DIR / "suites"
ARTIFACT_ROOT = REPO_ROOT / "build" / "testgate"


def load_suite(name: str) -> dict[str, Any]:
    suite_path = SUITES_DIR / f"{name}.toml"
    if not suite_path.exists():
        raise FileNotFoundError(f"suite not found: {suite_path}")
    with suite_path.open("rb") as suite_file:
        data = tomllib.load(suite_file)
    jobs = data.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError(f"suite {suite_path} must define at least one [[jobs]] entry")
    return data


def check_target(expected: dict[str, Any]) -> list[str]:
    warnings: list[str] = []

    expected_python = str(expected.get("python", ""))
    if expected_python:
        actual_python = f"{sys.version_info.major}.{sys.version_info.minor}"
        if actual_python != expected_python:
            warnings.append(
                f"Python version is {actual_python}, expected {expected_python}"
            )

    expected_arch = str(expected.get("arch", "")).lower()
    if expected_arch:
        actual_arch = platform.machine().lower()
        aliases = {
            "arm64": {"arm64", "aarch64"},
            "aarch64": {"arm64", "aarch64"},
        }
        accepted = aliases.get(expected_arch, {expected_arch})
        if actual_arch not in accepted:
            warnings.append(f"machine is {actual_arch}, expected {expected_arch}")

    expected_system = str(expected.get("system", "")).lower()
    if expected_system:
        actual_system = platform.system().lower()
        if actual_system != expected_system:
            warnings.append(f"system is {actual_system}, expected {expected_system}")

    return warnings


def timestamp() -> str:
    return _datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def make_run_dir(suite_name: str) -> Path:
    run_dir = ARTIFACT_ROOT / f"{suite_name}-{timestamp()}"
    (run_dir / "logs").mkdir(parents=True, exist_ok=False)
    return run_dir


def first_executable(candidates: list[str], extra_globs: list[str]) -> str | None:
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return path
    for pattern in extra_globs:
        for path in sorted(Path("/").glob(pattern), reverse=True):
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
    return None


def configure_toolchain(env: dict[str, str]) -> None:
    env.setdefault("CINDERX_TEST_PYTHON", sys.executable)

    if "CC" not in env:
        cc = first_executable(
            ["gcc-14", "gcc", "clang-19", "clang"],
            [
                "opt/gcc-*/bin/gcc",
                "opt/clang-*/bin/clang",
            ],
        )
        if cc:
            env["CC"] = cc

    if "CXX" not in env:
        cxx = first_executable(
            ["g++-14", "g++", "clang++-19", "clang++"],
            [
                "opt/gcc-*/bin/g++",
                "opt/clang-*/bin/clang++",
            ],
        )
        if cxx:
            env["CXX"] = cxx


def merged_env(job: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    configure_toolchain(env)
    for key, value in job.get("env", {}).items():
        env[str(key)] = str(value)
    return env


def command_for_job(job: dict[str, Any], run_dir: Path, prelude: str) -> str:
    command = str(job["command"]).format(
        repo=REPO_ROOT,
        run_dir=run_dir,
    )
    if not prelude:
        return command
    return f"set -euo pipefail; {prelude}; {command}"


def run_job(job: dict[str, Any], run_dir: Path, prelude: str) -> dict[str, Any]:
    name = str(job["name"])
    command = command_for_job(job, run_dir, prelude)
    log_path = run_dir / "logs" / f"{name}.log"

    started = _datetime.datetime.now().isoformat(timespec="seconds")
    print(f"[ RUN      ] {name}", flush=True)
    with log_path.open("w", encoding="utf-8") as log_file:
        log_file.write(f"$ {command}\n\n")
        log_file.flush()
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=merged_env(job),
            executable="/bin/bash" if os.name != "nt" else None,
            shell=True,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )

    finished = _datetime.datetime.now().isoformat(timespec="seconds")
    status = "passed" if completed.returncode == 0 else "failed"
    marker = "       OK" if completed.returncode == 0 else "  FAILED"
    print(f"[{marker} ] {name} ({log_path})", flush=True)

    return {
        "name": name,
        "status": status,
        "returncode": completed.returncode,
        "command": command,
        "log": str(log_path.relative_to(REPO_ROOT)),
        "started": started,
        "finished": finished,
    }


def write_summary(run_dir: Path, suite_name: str, results: list[dict[str, Any]]) -> Path:
    failed = [result for result in results if result["returncode"] != 0]
    summary = {
        "suite": suite_name,
        "status": "failed" if failed else "passed",
        "repo": str(REPO_ROOT),
        "head": git_head(),
        "results": results,
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary_path


def git_head() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", help="suite name, for example: pr")
    parser.add_argument(
        "--prelude",
        help=(
            "shell snippet to run before each job; overrides the suite prelude. "
            "Use an empty string to disable it."
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list jobs without running them",
    )
    args = parser.parse_args(argv)

    suite = load_suite(args.suite)
    target_warnings = check_target(suite.get("target", {}))
    for warning in target_warnings:
        print(f"warning: {warning}", file=sys.stderr)

    jobs = suite["jobs"]
    if args.list:
        for job in jobs:
            print(job["name"])
        return 0

    run_dir = make_run_dir(args.suite)
    print(f"artifact directory: {run_dir}", flush=True)

    results = []
    prelude = str(suite.get("prelude", ""))
    if "CINDERX_TESTGATE_PRELUDE" in os.environ:
        prelude = os.environ["CINDERX_TESTGATE_PRELUDE"]
    if args.prelude is not None:
        prelude = args.prelude
    fail_fast = bool(suite.get("fail_fast", True))
    for job in jobs:
        result = run_job(job, run_dir, prelude)
        results.append(result)
        if fail_fast and result["returncode"] != 0:
            break

    summary_path = write_summary(run_dir, args.suite, results)
    print(f"summary: {summary_path}", flush=True)

    failed = [result for result in results if result["returncode"] != 0]
    if failed:
        print("failed jobs:", flush=True)
        for result in failed:
            print(f"  - {result['name']} ({result['log']})", flush=True)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
