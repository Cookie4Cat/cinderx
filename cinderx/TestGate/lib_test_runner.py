#!/usr/bin/env python3
"""Run CPython Lib/test for the local CinderX gate."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import site
import subprocess
import sys
from typing import Iterable


def find_repo_root() -> Path:
    path = Path(__file__).resolve()
    for parent in path.parents:
        if (parent / "CMakeLists.txt").exists() and (parent / "cinderx").is_dir():
            return parent
    raise RuntimeError("could not find repository root")


REPO_ROOT = find_repo_root()
TESTGATE_DIR = REPO_ROOT / "cinderx" / "TestGate"
TEST_SCRIPTS_DIR = REPO_ROOT / "cinderx" / "TestScripts"
TESTGATE_SKIPLIST_DIR = TESTGATE_DIR / "skiplists"

MODES_REQUIRING_FRAME_EVALUATOR = {"frame-eval-nojit"}
NOJIT_MODES = {"frame-eval-nojit"}
SINGLE_PROCESS_TESTS = {
    "frame-eval-nojit": {
        "test.test_code",
    },
}
EXIT_FAST_UNITTEST_TESTS = {
    "frame-eval-nojit": {
        "test.test_code",
    },
}


def read_skip_file(path: Path) -> tuple[set[str], set[str]]:
    modules: set[str] = set()
    patterns: set[str] = set()
    with path.open(encoding="utf-8") as skip_file:
        for raw_line in skip_file:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "." in line or "*" in line:
                patterns.add(line)
            else:
                modules.add(line)
    return modules, patterns


def is_asan_build() -> bool:
    try:
        from test import support
    except ImportError:
        return False
    return bool(support.check_sanitizer(address=True))


def skip_file_names(*, mode: str, huntrleaks: bool, use_rr: bool) -> list[str]:
    names = ["devserver_skip_tests.txt", "cinder_skip_test.txt"]

    version = "".join(str(v) for v in sys.version_info[:2])
    versioned_name = f"cinder_skip_test_{version}.txt"
    if (TEST_SCRIPTS_DIR / versioned_name).exists():
        names.append(versioned_name)

    if is_asan_build():
        names.append("asan_skip_tests.txt")

    if use_rr:
        names.append("rr_skip_tests.txt")

    if mode not in NOJIT_MODES:
        try:
            import cinderjit  # noqa: F401
        except ImportError:
            pass
        else:
            names.append("cinder_jit_ignore_tests.txt")
            names.append(f"cinder_jit_ignore_tests_{version}.txt")

    if huntrleaks:
        names.append("refleak_skip_tests.txt")

    if platform.processor() != "" and platform.processor() != platform.machine():
        names.append("cross_platform_skip_tests.txt")

    return names


def load_skip_metadata(
    *, mode: str, huntrleaks: bool = False, use_rr: bool = False
) -> tuple[list[str], set[str], set[str]]:
    names = skip_file_names(mode=mode, huntrleaks=huntrleaks, use_rr=use_rr)
    modules: set[str] = set()
    patterns: set[str] = set()
    existing_names: list[str] = []
    for name in names:
        path = TEST_SCRIPTS_DIR / name
        if not path.exists():
            continue
        existing_names.append(name)
        file_modules, file_patterns = read_skip_file(path)
        modules.update(file_modules)
        patterns.update(file_patterns)
    return existing_names, modules, patterns


def load_gate_skip_metadata(mode: str) -> tuple[list[str], set[str], set[str]]:
    path = TESTGATE_SKIPLIST_DIR / f"lib_test_{mode.replace('-', '_')}.txt"
    if not path.exists():
        return [], set(), set()
    modules, patterns = read_skip_file(path)
    return [str(path.relative_to(REPO_ROOT))], modules, patterns


def discover_lib_tests(exclude: set[str]) -> list[str]:
    from test.libregrtest import findtests as libregrtest_findtests

    tests = libregrtest_findtests.findtests(
        exclude=exclude,
        base_mod="test",
        split_test_dirs={"test." + d for d in libregrtest_findtests.SPLITTESTDIRS},
    )
    return sorted(test for test in tests if test.startswith("test."))


def write_lines(path: Path, lines: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def write_startup_hook(path: Path, mode: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    hook = [
        "import sys\n",
        "\n",
        "# CPython's regression tests spawn child interpreters to validate clean\n",
        "# startup behavior. Keep this hook on `python -m test` regrtest processes,\n",
        "# but do not alter temporary subprocesses used by those startup tests.\n",
        "argv0 = sys.argv[0].replace('\\\\', '/') if sys.argv else ''\n",
        "orig_argv = tuple(getattr(sys, 'orig_argv', ()))\n",
        "module_name = None\n",
        "if '-m' in orig_argv:\n",
        "    module_index = orig_argv.index('-m') + 1\n",
        "    if module_index < len(orig_argv):\n",
        "        module_name = orig_argv[module_index]\n",
        "if (\n",
        "    module_name in {'test', 'test.libregrtest.worker'}\n",
        "    or argv0.endswith('/test/__main__.py')\n",
        "    or argv0.endswith('/test/regrtest.py')\n",
        "    or argv0.endswith('/cinderx/TestGate/filtered_unittest.py')\n",
        "):\n",
        "    import os\n",
    ]
    if mode in NOJIT_MODES:
        hook.extend(
            [
                "    os.environ.setdefault('CINDERX_JIT_DISABLE', '1')\n",
                "    os.environ.setdefault('PYTHONJITDISABLE', '1')\n",
            ]
        )
    hook.extend(
        [
        "    import cinderx\n",
        "    cinderx.init()\n",
        "    if not cinderx.is_initialized():\n",
        "        raise RuntimeError('CinderX failed to initialize')\n",
        ]
    )
    if mode in MODES_REQUIRING_FRAME_EVALUATOR:
        hook.extend(
            [
                "    if not cinderx.is_frame_evaluator_installed():\n",
                "        cinderx.install_frame_evaluator()\n",
                "    if not cinderx.is_frame_evaluator_installed():\n",
                "        raise RuntimeError('CinderX frame evaluator is not installed')\n",
            ]
        )
    if mode in NOJIT_MODES:
        hook.extend(
            [
                "    import cinderx.jit\n",
                "    if cinderx.jit.is_enabled():\n",
                "        raise RuntimeError('CinderX JIT is enabled in nojit mode')\n",
            ]
        )
    hook.extend(
        [
            "    marker = os.environ.get('CINDERX_TESTGATE_FRAME_EVAL_MARKER')\n",
            "    if marker:\n",
            "        with open(marker, 'a', encoding='utf-8') as marker_file:\n",
            "            marker_file.write(f'{os.getpid()} {argv0}\\n')\n",
        ]
    )
    (path / "sitecustomize.py").write_text("".join(hook), encoding="utf-8")


def env_for_mode(mode: str, startup_dir: Path, marker_file: Path) -> dict[str, str]:
    env = os.environ.copy()
    site_packages = site.getsitepackages()[0]
    pythonpath_entries = [str(startup_dir), site_packages]
    if pythonpath := env.get("PYTHONPATH"):
        pythonpath_entries.append(pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    env["CINDERX_TESTGATE_FRAME_EVAL_MARKER"] = str(marker_file)

    openssl_lib = env.get("CINDERX_TEST_OPENSSL_LIB")
    if not openssl_lib:
        candidate = Path("/opt/openssl-1.1.1w-vanilla/lib")
        if (candidate / "libssl.so.1.1").exists() and (
            candidate / "libcrypto.so.1.1"
        ).exists():
            openssl_lib = str(candidate)
    if openssl_lib:
        ld_library_path = env.get("LD_LIBRARY_PATH")
        env["LD_LIBRARY_PATH"] = (
            openssl_lib
            if not ld_library_path
            else f"{openssl_lib}{os.pathsep}{ld_library_path}"
        )

    if mode in NOJIT_MODES:
        env["CINDERX_JIT_DISABLE"] = "1"
        env["PYTHONJITDISABLE"] = "1"

    return env


def normalize_tests(tests: list[str] | None) -> list[str] | None:
    if tests is None:
        return None
    normalized = []
    for test in tests:
        if test.startswith("test_"):
            normalized.append(f"test.{test}")
        else:
            normalized.append(test)
    return normalized


def regrtest_command(
    *,
    tests: list[str],
    ignore_file: Path,
    num_workers: int,
    worker_timeout: int,
    single_process: bool = False,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "test",
        "-q",
        "--timeout",
        str(worker_timeout),
        "--fail-env-changed",
        "--fail-rerun",
        "-w",
    ]
    if single_process:
        command.append("--single-process")
    else:
        command.extend(["-j", str(num_workers)])
    command.extend(tests)
    if ignore_file.exists() and ignore_file.stat().st_size:
        command.extend(["--ignorefile", str(ignore_file)])
    return command


def filtered_unittest_command(*, test: str, ignore_file: Path) -> list[str]:
    command = [
        sys.executable,
        str(TESTGATE_DIR / "filtered_unittest.py"),
        "--ignorefile",
        str(ignore_file),
        test,
    ]
    return command


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=["frame-eval-nojit"],
        default="frame-eval-nojit",
        help="Lib/test execution mode",
    )
    parser.add_argument("--json-summary-file", required=True)
    parser.add_argument("--test-list-file", required=True)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--worker-timeout", type=int, default=20 * 60)
    parser.add_argument(
        "--disable-jit",
        action="store_true",
        help="deprecated alias for --mode nojit",
    )
    parser.add_argument(
        "-t",
        "--test",
        action="append",
        help="run only these tests instead of the official Lib/test list",
    )
    args = parser.parse_args(argv)

    if args.disable_jit:
        args.mode = "frame-eval-nojit"

    skip_files, skip_modules, skip_patterns = load_skip_metadata(mode=args.mode)
    gate_skip_files, gate_skip_modules, gate_skip_patterns = load_gate_skip_metadata(
        args.mode
    )
    skip_files.extend(gate_skip_files)
    skip_modules.update(gate_skip_modules)
    skip_patterns.update(gate_skip_patterns)
    tests = normalize_tests(args.test) or discover_lib_tests(skip_modules)

    test_list_path = Path(args.test_list_file)
    write_lines(test_list_path, tests)

    ignore_file = test_list_path.with_name(f"{test_list_path.stem}_ignore_patterns.txt")
    write_lines(ignore_file, sorted(skip_patterns))

    single_process_tests = [
        test for test in tests if test in SINGLE_PROCESS_TESTS.get(args.mode, set())
    ]
    parallel_tests = [test for test in tests if test not in set(single_process_tests)]
    parallel_test_list_path = test_list_path.with_name(
        f"{test_list_path.stem}_parallel.txt"
    )
    write_lines(parallel_test_list_path, parallel_tests)

    startup_dir = test_list_path.with_name(f"{test_list_path.stem}_startup")
    write_startup_hook(startup_dir, args.mode)
    marker_file = startup_dir / "frame_eval_startups.txt"

    env = env_for_mode(args.mode, startup_dir, marker_file)
    commands: list[list[str]] = []
    if parallel_tests:
        commands.append(
            regrtest_command(
                tests=["--fromfile", str(parallel_test_list_path)],
                ignore_file=ignore_file,
                num_workers=args.num_workers,
                worker_timeout=args.worker_timeout,
            )
        )
    exit_fast_unittest_tests = EXIT_FAST_UNITTEST_TESTS.get(args.mode, set())
    for test in single_process_tests:
        if test in exit_fast_unittest_tests:
            commands.append(
                filtered_unittest_command(test=test, ignore_file=ignore_file)
            )
        else:
            commands.append(
                regrtest_command(
                    tests=[test],
                    ignore_file=ignore_file,
                    num_workers=args.num_workers,
                    worker_timeout=args.worker_timeout,
                    single_process=True,
                )
            )

    returncode = 0
    for command in commands:
        completed = subprocess.run(command, cwd=REPO_ROOT, env=env)
        if completed.returncode != 0:
            returncode = completed.returncode
            break

    if args.mode in MODES_REQUIRING_FRAME_EVALUATOR and not marker_file.exists():
        print("CinderX frame evaluator startup hook did not run", file=sys.stderr)
        returncode = 1

    summary = {
        "mode": args.mode,
        "returncode": returncode,
        "requires_cinderx_frame_evaluator": (
            args.mode in MODES_REQUIRING_FRAME_EVALUATOR
        ),
        "requires_jit_disabled": args.mode in NOJIT_MODES,
        "startup_hook": str(startup_dir / "sitecustomize.py"),
        "startup_marker": str(marker_file),
        "test_count": len(tests),
        "tests": tests,
        "parallel_test_count": len(parallel_tests),
        "parallel_test_list_file": str(parallel_test_list_path),
        "single_process_tests": single_process_tests,
        "exit_fast_unittest_tests": sorted(exit_fast_unittest_tests),
        "skip_files": skip_files,
        "skip_modules": sorted(skip_modules),
        "skip_patterns": sorted(skip_patterns),
        "ignore_patterns_file": str(ignore_file),
        "commands": commands,
    }
    Path(args.json_summary_file).write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )

    return returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
