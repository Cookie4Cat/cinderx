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
MAX_WORKERS = 64
DEFAULT_ADAPTIVE_AWARE_COMPILE_AFTER = 50

ADAPTIVE_AWARE_MODES = {"frame-eval-adaptive-aware"}
MODES_REQUIRING_FRAME_EVALUATOR = {
    "frame-eval-nojit",
    "frame-eval-jit-all",
    *ADAPTIVE_AWARE_MODES,
}
MODES_REQUIRING_JIT_ALL = {"frame-eval-jit-all"}
MODES_REQUIRING_JIT_ENABLED = MODES_REQUIRING_JIT_ALL | ADAPTIVE_AWARE_MODES
MODES_RECORDING_JIT_STATS = MODES_REQUIRING_JIT_ENABLED
NOJIT_MODES = {"frame-eval-nojit"}
SINGLE_PROCESS_TESTS = {
    "frame-eval-nojit": {
        "test.test_code",
    },
    "frame-eval-jit-all": {
        "test.test_code",
    },
    "frame-eval-adaptive-aware": {
        "test.test_code",
    },
}
EXIT_FAST_UNITTEST_TESTS = {
    "frame-eval-nojit": {
        "test.test_code",
    },
    "frame-eval-jit-all": {
        "test.test_code",
    },
    "frame-eval-adaptive-aware": {
        "test.test_code",
    },
}
MODE_XOPTIONS = {
    "frame-eval-jit-all": ["-X", "jit-all"],
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

    if mode in MODES_REQUIRING_JIT_ALL:
        names.append("cinder_jit_ignore_tests.txt")
        names.append(f"cinder_jit_ignore_tests_{version}.txt")
    elif mode not in NOJIT_MODES:
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


def read_test_file(path: Path) -> list[str]:
    tests = []
    with path.open(encoding="utf-8") as test_file:
        for raw_line in test_file:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            tests.append(line)
    return tests


def default_num_workers() -> int:
    return min(os.cpu_count() or 1, MAX_WORKERS)


def parse_num_workers(value: str | None) -> int:
    value = value or os.environ.get("CINDERX_TESTGATE_WORKERS", "auto")
    if value == "auto":
        return default_num_workers()
    workers = int(value)
    if workers <= 0:
        raise argparse.ArgumentTypeError("--num-workers must be positive or 'auto'")
    return workers


def write_startup_hook(
    path: Path,
    mode: str,
    *,
    jit_stats_dir: Path | None = None,
    adaptive_compile_after: int | None = None,
) -> None:
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
        "    or argv0.endswith('/jit_probe.py')\n",
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
        "    try:\n",
        "        import _testcapi\n",
        "        import types\n",
        "        original_get_code = _testcapi.gen_get_code\n",
        "        def gen_get_code(o):\n",
        "            if type(o) is not types.GeneratorType:\n",
        "                return o.gi_code\n",
        "            return original_get_code(o)\n",
        "        _testcapi.gen_get_code = gen_get_code\n",
        "        original_raise_sigint_then_send_none = getattr(\n",
        "            _testcapi, 'raise_SIGINT_then_send_None', None)\n",
        "        if original_raise_sigint_then_send_none is not None:\n",
        "            import cinderx.jit\n",
        "            def raise_SIGINT_then_send_None(o):\n",
        "                cinderx.jit._deopt_gen(o)\n",
        "                return original_raise_sigint_then_send_none(o)\n",
        "            _testcapi.raise_SIGINT_then_send_None = (\n",
        "                raise_SIGINT_then_send_None)\n",
        "    except (ImportError, AttributeError):\n",
        "        pass\n",
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
    if mode in MODES_REQUIRING_JIT_ENABLED:
        hook.extend(
            [
                "    import cinderx.jit\n",
                "    if not cinderx.jit.is_enabled():\n",
                "        raise RuntimeError('CinderX JIT is not enabled')\n",
            ]
        )
    if mode in MODES_REQUIRING_JIT_ALL:
        hook.extend(
            [
                "    if cinderx.jit.get_compile_after_n_calls() != 0:\n",
                "        raise RuntimeError('CinderX JIT is not in jit-all mode')\n",
            ]
        )
    if mode in ADAPTIVE_AWARE_MODES:
        hook.extend(
            [
                "    adaptive_compile_after = os.environ.get(\n",
                "        'CINDERX_TESTGATE_ADAPTIVE_COMPILE_AFTER')\n",
                "    if adaptive_compile_after is not None:\n",
                "        adaptive_compile_after = int(adaptive_compile_after)\n",
                "        cinderx.jit.compile_after_n_calls(adaptive_compile_after)\n",
                "        if cinderx.jit.get_compile_after_n_calls() != adaptive_compile_after:\n",
                "            raise RuntimeError('CinderX JIT adaptive-aware threshold mismatch')\n",
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
    if jit_stats_dir is not None and mode in MODES_RECORDING_JIT_STATS:
        hook.extend(
            [
                "    jit_stats_dir = os.environ.get('CINDERX_TESTGATE_JIT_STATS_DIR')\n",
                "    if jit_stats_dir:\n",
                "        import atexit\n",
                "        import json\n",
                "        from pathlib import Path\n",
                "        def _jit_func_record(func):\n",
                "            module = getattr(func, '__module__', None)\n",
                "            qualname = getattr(func, '__qualname__', None)\n",
                "            return {\n",
                "                'module': module,\n",
                "                'qualname': qualname,\n",
                "                'name': f'{module}.{qualname}' if module and qualname else repr(func),\n",
                "            }\n",
                "        _jit_before_records = [\n",
                "            _jit_func_record(func)\n",
                "            for func in cinderx.jit.get_compiled_functions()\n",
                "        ]\n",
                "        _jit_before_names = {\n",
                "            record['name'] for record in _jit_before_records\n",
                "        }\n",
                "        def _dump_jit_stats():\n",
                "            after_records = [\n",
                "                _jit_func_record(func)\n",
                "                for func in cinderx.jit.get_compiled_functions()\n",
                "            ]\n",
                "            new_records = [\n",
                "                record for record in after_records\n",
                "                if record['name'] not in _jit_before_names\n",
                "            ]\n",
                "            out_dir = Path(jit_stats_dir)\n",
                "            out_dir.mkdir(parents=True, exist_ok=True)\n",
                "            out_file = out_dir / f'jit_stats_{os.getpid()}.json'\n",
                "            payload = {\n",
                "                'pid': os.getpid(),\n",
                "                'argv': sys.argv,\n",
                "                'orig_argv': list(orig_argv),\n",
                "                'argv0': argv0,\n",
                "                'module_name': module_name,\n",
                "                'compiled_before': len(_jit_before_records),\n",
                "                'compiled_after': len(after_records),\n",
                "                'compiled_delta': len(after_records) - len(_jit_before_records),\n",
                "                'new_function_count': len(new_records),\n",
                "                'new_functions': new_records,\n",
                "            }\n",
                "            out_file.write_text(json.dumps(payload, indent=2) + '\\n', encoding='utf-8')\n",
                "        atexit.register(_dump_jit_stats)\n",
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
    else:
        env.pop("CINDERX_JIT_DISABLE", None)
        env.pop("PYTHONJITDISABLE", None)

    return env


def adaptive_compile_after_for_mode(mode: str, value: int | None) -> int | None:
    if mode not in ADAPTIVE_AWARE_MODES:
        return None
    if value is None:
        value = DEFAULT_ADAPTIVE_AWARE_COMPILE_AFTER
    if value <= 0:
        raise argparse.ArgumentTypeError(
            "--adaptive-compile-after must be positive"
        )
    return value


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


def defer_tests(tests: list[str], patterns: list[str]) -> list[str]:
    if not patterns:
        return tests
    deferred = []
    kept = []
    for test in tests:
        if any(test.startswith(pattern) for pattern in patterns):
            deferred.append(test)
        else:
            kept.append(test)
    return kept + deferred


def write_jit_probe(path: Path) -> None:
    script = r'''
import json
import sys

import cinderx
import cinderx.jit


def foo(x):
    return x + 1


compiled_before = len(cinderx.jit.get_compiled_functions())
for i in range(10):
    foo(i)
compiled_after = len(cinderx.jit.get_compiled_functions())

result = {
    "jit_enabled": cinderx.jit.is_enabled(),
    "compile_after_n_calls": cinderx.jit.get_compile_after_n_calls(),
    "foo_compiled": cinderx.jit.is_jit_compiled(foo),
    "compiled_before": compiled_before,
    "compiled_after": compiled_after,
    "foo_compiled_size": cinderx.jit.get_compiled_size(foo),
}

with open(sys.argv[1], "w", encoding="utf-8") as output:
    json.dump(result, output, indent=2)
    output.write("\n")

if (
    not result["jit_enabled"]
    or result["compile_after_n_calls"] != 0
    or not result["foo_compiled"]
    or result["foo_compiled_size"] <= 0
):
    raise SystemExit(1)
'''.lstrip()
    path.write_text(script, encoding="utf-8")


def run_jit_probe(
    *, startup_dir: Path, env: dict[str, str], xoptions: list[str], output_file: Path
) -> dict[str, object]:
    probe_script = startup_dir / "jit_probe.py"
    probe_log = output_file.with_suffix(".log")
    write_jit_probe(probe_script)

    command = [sys.executable, *xoptions, str(probe_script), str(output_file)]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    probe_log.write_text(completed.stdout, encoding="utf-8")

    result: dict[str, object] = {
        "returncode": completed.returncode,
        "command": command,
        "log": str(probe_log),
    }
    if output_file.exists():
        with output_file.open(encoding="utf-8") as output:
            result.update(json.load(output))
    return result


def regrtest_command(
    *,
    tests: list[str],
    ignore_file: Path,
    num_workers: int,
    worker_timeout: int,
    single_process: bool = False,
    xoptions: list[str] | None = None,
) -> list[str]:
    command = [
        sys.executable,
        *(xoptions or []),
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


def filtered_unittest_command(
    *, test: str, ignore_file: Path, xoptions: list[str] | None = None
) -> list[str]:
    command = [
        sys.executable,
        *(xoptions or []),
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
        choices=[
            "frame-eval-nojit",
            "frame-eval-jit-all",
            "frame-eval-adaptive-aware",
        ],
        default="frame-eval-nojit",
        help="Lib/test execution mode",
    )
    parser.add_argument("--json-summary-file", required=True)
    parser.add_argument("--test-list-file", required=True)
    parser.add_argument(
        "--test-from-file",
        help="read tests from this file instead of discovering Lib/test",
    )
    parser.add_argument("--num-workers", default=None)
    parser.add_argument("--worker-timeout", type=int, default=20 * 60)
    parser.add_argument(
        "--adaptive-compile-after",
        type=int,
        default=DEFAULT_ADAPTIVE_AWARE_COMPILE_AFTER,
        help=(
            "AutoJIT threshold for frame-eval-adaptive-aware "
            f"(default: {DEFAULT_ADAPTIVE_AWARE_COMPILE_AFTER})"
        ),
    )
    parser.add_argument(
        "--jit-stats-dir",
        help="write per-process JIT compilation stats under this directory",
    )
    parser.add_argument(
        "--skip-jit-probe",
        action="store_true",
        help="skip the small jit-all sanity probe",
    )
    parser.add_argument(
        "--defer-pattern",
        action="append",
        default=[],
        help="move tests whose normalized name starts with this prefix to the end",
    )
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

    try:
        num_workers = parse_num_workers(args.num_workers)
    except (argparse.ArgumentTypeError, ValueError) as exc:
        parser.error(f"invalid --num-workers value: {exc}")
    try:
        adaptive_compile_after = adaptive_compile_after_for_mode(
            args.mode, args.adaptive_compile_after
        )
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))

    skip_files, skip_modules, skip_patterns = load_skip_metadata(mode=args.mode)
    gate_skip_files, gate_skip_modules, gate_skip_patterns = load_gate_skip_metadata(
        args.mode
    )
    skip_files.extend(gate_skip_files)
    skip_modules.update(gate_skip_modules)
    skip_patterns.update(gate_skip_patterns)
    tests = normalize_tests(args.test)
    if tests is None and args.test_from_file:
        tests = normalize_tests(read_test_file(Path(args.test_from_file)))
    if tests is None:
        tests = discover_lib_tests(skip_modules)
    tests = defer_tests(tests, args.defer_pattern)

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
    jit_stats_dir = Path(args.jit_stats_dir) if args.jit_stats_dir else None
    write_startup_hook(
        startup_dir,
        args.mode,
        jit_stats_dir=jit_stats_dir,
        adaptive_compile_after=adaptive_compile_after,
    )
    marker_file = startup_dir / "frame_eval_startups.txt"

    env = env_for_mode(args.mode, startup_dir, marker_file)
    if jit_stats_dir is not None:
        env["CINDERX_TESTGATE_JIT_STATS_DIR"] = str(jit_stats_dir)
    if adaptive_compile_after is not None:
        env["CINDERX_TESTGATE_ADAPTIVE_COMPILE_AFTER"] = str(
            adaptive_compile_after
        )
    xoptions = MODE_XOPTIONS.get(args.mode, [])
    jit_probe = None
    if args.mode in MODES_REQUIRING_JIT_ALL and not args.skip_jit_probe:
        jit_probe_path = test_list_path.with_name(
            f"{test_list_path.stem}_jit_probe.json"
        )
        jit_probe = run_jit_probe(
            startup_dir=startup_dir,
            env=env,
            xoptions=xoptions,
            output_file=jit_probe_path,
        )
    commands: list[list[str]] = []
    if jit_probe is None or jit_probe["returncode"] == 0:
        if parallel_tests:
            commands.append(
                regrtest_command(
                    tests=["--fromfile", str(parallel_test_list_path)],
                    ignore_file=ignore_file,
                    num_workers=num_workers,
                    worker_timeout=args.worker_timeout,
                    xoptions=xoptions,
                )
            )
    exit_fast_unittest_tests = EXIT_FAST_UNITTEST_TESTS.get(args.mode, set())
    if jit_probe is None or jit_probe["returncode"] == 0:
        for test in single_process_tests:
            if test in exit_fast_unittest_tests:
                commands.append(
                    filtered_unittest_command(
                        test=test, ignore_file=ignore_file, xoptions=xoptions
                    )
                )
            else:
                commands.append(
                    regrtest_command(
                        tests=[test],
                        ignore_file=ignore_file,
                        num_workers=num_workers,
                        worker_timeout=args.worker_timeout,
                        single_process=True,
                        xoptions=xoptions,
                    )
                )

    returncode = 0
    if jit_probe is not None and jit_probe["returncode"] != 0:
        returncode = int(jit_probe["returncode"])
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
        "requires_jit_enabled": args.mode in MODES_REQUIRING_JIT_ENABLED,
        "requires_jit_all": args.mode in MODES_REQUIRING_JIT_ALL,
        "requires_adaptive_aware": args.mode in ADAPTIVE_AWARE_MODES,
        "adaptive_compile_after": adaptive_compile_after,
        "xoptions": xoptions,
        "num_workers": num_workers,
        "jit_probe": jit_probe,
        "jit_stats_dir": str(jit_stats_dir) if jit_stats_dir is not None else None,
        "defer_patterns": args.defer_pattern,
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
