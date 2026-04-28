#!/usr/bin/env python3

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

def find_repo_root() -> Path:
    path = Path(__file__).resolve()
    for parent in path.parents:
        if (parent / "CMakeLists.txt").exists() and (parent / "cinderx").is_dir():
            return parent
    raise RuntimeError("could not find repository root")

REPO_ROOT = find_repo_root()
TEST_CINDERX_DIR = REPO_ROOT / "cinderx" / "PythonLib" / "test_cinderx"
ALL_TEST_CINDERX = [
    str(path.relative_to(REPO_ROOT)) for path in sorted(TEST_CINDERX_DIR.glob("test*.py"))
]

INSTRUMENTATION_FILTER = (
    "JitMonitoringIntegrationTest or JitSetProfileIntegrationTest or "
    "(JitSetTraceIntegrationTest and not "
    "test_looping_thread_deopted_on_instrumentation) or "
    "JitCombinedTracingIntegrationTest or "
    "test_suspended_generator_deopted_on_instrumentation_attach or "
    "test_multiple_suspended_generators_all_deopted"
)

SUITES = [
    {
        "name": "all_test_cinderx",
        "args": ["-m", "pytest", *ALL_TEST_CINDERX],
    },
    {
        "name": "test_cinderjit",
        "args": [
            "-m",
            "pytest",
            "-vv",
            "-rs",
            "--import-mode=importlib",
            "cinderx/PythonLib/test_cinderx/test_cinderjit.py",
        ],
        "allow_oss": True,
    },
]

for test_name in [
    "test_coro_extensions.py",
    "test_jit_coroutines.py",
    "test_jit_attr_cache.py",
    "test_parallel_gc.py",
    "test_perf_profiler_precompile.py",
    "test_type_cache.py",
]:
    SUITES.append(
        {
            "name": test_name.removesuffix(".py"),
            "args": [
                "-m",
                "pytest",
                "-vv",
                "-rs",
                "--import-mode=importlib",
                f"cinderx/PythonLib/test_cinderx/{test_name}",
            ],
            "allow_oss": True,
        }
    )

SUITES.extend(
    [
        {
            "name": "test_jit_support_instrumentation",
            "args": [
                "-m",
                "pytest",
                "-vv",
                "-rs",
                "--import-mode=importlib",
                "cinderx/PythonLib/test_cinderx/test_jit_support_instrumentation.py",
                "-k",
                INSTRUMENTATION_FILTER,
            ],
            "allow_oss": True,
            "env": {"CINDERX_JIT_SUPPORT_INSTRUMENTATION": "1"},
        },
        {
            "name": "test_frame_evaluator_clean_slate",
            "args": [
                "-m",
                "pytest",
                "-vv",
                "-rs",
                "--import-mode=importlib",
                "cinderx/PythonLib/test_cinderx/test_frame_evaluator.py",
            ],
        },
    ]
)

def log_name(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def run_suite(suite: dict, python: str, log_dir: Path) -> dict:
    name = suite["name"]
    log_path = log_dir / f"{name}.log"
    env = os.environ.copy()
    if suite.get("allow_oss"):
        env["CINDERX_TEST_ALLOW_OSS_IMPORTS"] = "1"
    env.update(suite.get("env", {}))
    command = [python, *suite["args"]]
    print(f"[ RUN      ] {name}", flush=True)
    with log_path.open("w", encoding="utf-8") as log_file:
        log_file.write("$ " + " ".join(command) + "\n\n")
        log_file.flush()
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
    marker = "       OK" if completed.returncode == 0 else "  FAILED"
    print(f"[{marker} ] {name} ({log_path})", flush=True)
    return {
        "name": name,
        "status": "passed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "command": command,
        "log": log_name(log_path),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--log-dir", required=True)
    parser.add_argument("--json-summary-file", required=True)
    args = parser.parse_args(argv)

    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for suite in SUITES:
        result = run_suite(suite, args.python, log_dir)
        results.append(result)
        if result["returncode"] != 0:
            break

    failed = [result for result in results if result["returncode"] != 0]
    summary = {
        "status": "failed" if failed else "passed",
        "results": results,
    }
    Path(args.json_summary_file).write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return 1 if failed else 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
