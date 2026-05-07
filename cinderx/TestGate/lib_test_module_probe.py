#!/usr/bin/env python3
"""Run Lib/test modules one at a time and record JIT compilation activity."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import lib_test_runner


def resolve_num_workers(value: str) -> int:
    if value == "auto":
        return min(os.cpu_count() or 1, 64)
    try:
        workers = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "--num-workers must be an integer or 'auto'"
        ) from exc
    if workers < 1:
        raise argparse.ArgumentTypeError("--num-workers must be >= 1")
    return workers


def write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def classify_result(returncode: int, log_text: str) -> str:
    if returncode == 124:
        return "timeout"
    if "Result: NO TESTS RAN" in log_text and "resource_denied=" in log_text:
        return "resource_denied"
    if returncode == 0 and "Result: NO TESTS RAN" in log_text:
        return "no_tests"
    if returncode == 0:
        return "pass"
    if "ENV CHANGED" in log_text:
        return "env_changed"
    return "fail"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as json_file:
        return json.load(json_file)


def read_process_stats(stats_dir: Path) -> list[dict[str, Any]]:
    stats = []
    for path in sorted(stats_dir.glob("jit_stats_*.json")):
        data = read_json(path)
        data["path"] = str(path)
        stats.append(data)
    return stats


def cleanup_process_group(process: subprocess.Popen[Any]) -> None:
    if not hasattr(os, "killpg"):
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        pass


def child_pids(pid: int) -> list[int]:
    children = set()
    task_dir = Path(f"/proc/{pid}/task")
    try:
        tasks = list(task_dir.iterdir())
    except (FileNotFoundError, ProcessLookupError):
        return []
    for task in tasks:
        children_file = task / "children"
        try:
            children.update(int(child) for child in children_file.read_text().split())
        except (FileNotFoundError, ProcessLookupError, ValueError):
            pass
    return sorted(children)


def descendant_pids(pid: int) -> list[int]:
    descendants = []
    pending = child_pids(pid)
    while pending:
        child = pending.pop()
        descendants.append(child)
        pending.extend(child_pids(child))
    return descendants


def cleanup_process_tree(process: subprocess.Popen[Any]) -> None:
    for pid in reversed(descendant_pids(process.pid)):
        if hasattr(os, "killpg"):
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                pass
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass
    cleanup_process_group(process)


def process_has_marker(pid: int, marker: str) -> bool:
    try:
        environ = Path(f"/proc/{pid}/environ").read_bytes()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return False
    return marker.encode() in environ


def cleanup_marked_processes(marker: str) -> None:
    proc_dir = Path("/proc")
    for path in proc_dir.iterdir():
        if not path.name.isdigit():
            continue
        pid = int(path.name)
        if not process_has_marker(pid, marker):
            continue
        if hasattr(os, "killpg"):
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                pass
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass


def function_name(record: dict[str, Any]) -> str:
    name = record.get("name")
    return name if isinstance(name, str) else repr(record)


def module_function_names(
    process_stats: list[dict[str, Any]], test_module: str
) -> list[str]:
    names = set()
    for process in process_stats:
        for record in process.get("new_functions", []):
            if not isinstance(record, dict):
                continue
            module = record.get("module")
            if module == test_module or (
                isinstance(module, str) and module.startswith(f"{test_module}.")
            ):
                names.add(function_name(record))
    return sorted(names)


def new_function_names(process_stats: list[dict[str, Any]]) -> list[str]:
    names = set()
    for process in process_stats:
        for record in process.get("new_functions", []):
            if isinstance(record, dict):
                names.add(function_name(record))
    return sorted(names)


def run_module(
    *,
    test: str,
    index: int,
    total: int,
    args: argparse.Namespace,
    output_dir: Path,
) -> dict[str, Any]:
    slug = test.replace(".", "_").replace("/", "_").replace(":", "_")
    module_dir = output_dir / f"{index:04d}_{slug}"
    module_dir.mkdir(parents=True, exist_ok=True)

    input_file = module_dir / "input.txt"
    test_list_file = module_dir / "executed_tests.txt"
    json_summary_file = module_dir / "runner_summary.json"
    jit_stats_dir = module_dir / "jit_stats"
    log_file = module_dir / "runner.log"
    write_lines(input_file, [test])
    marker = f"CINDERX_TESTGATE_MODULE_PROBE={module_dir}"

    command = [
        sys.executable,
        str(lib_test_runner.TESTGATE_DIR / "lib_test_runner.py"),
        "--mode",
        args.mode,
        "--num-workers",
        "1",
        "--worker-timeout",
        str(args.worker_timeout),
        "--test-from-file",
        str(input_file),
        "--test-list-file",
        str(test_list_file),
        "--json-summary-file",
        str(json_summary_file),
        "--jit-stats-dir",
        str(jit_stats_dir),
        "--skip-jit-probe",
    ]
    if args.mode in lib_test_runner.ADAPTIVE_AWARE_MODES:
        command.extend(
            [
                "--adaptive-compile-after",
                str(args.adaptive_compile_after),
            ]
        )

    print(f"[{index:4d}/{total}] {test}", flush=True)
    started = time.monotonic()
    with log_file.open("w", encoding="utf-8") as log:
        log.write("$ " + " ".join(command) + "\n\n")
        log.flush()
        env = os.environ.copy()
        env["CINDERX_TESTGATE_MODULE_PROBE"] = str(module_dir)
        process = subprocess.Popen(
            command,
            cwd=lib_test_runner.REPO_ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=hasattr(os, "killpg"),
        )
        try:
            returncode = process.wait(timeout=args.per_module_timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            cleanup_process_tree(process)
            cleanup_marked_processes(marker)
            process.wait()
            returncode = 124
            timed_out = True
            log.write(f"\nTimed out after {args.per_module_timeout} seconds\n")
        else:
            cleanup_process_group(process)

    elapsed = round(time.monotonic() - started, 3)
    log_text = log_file.read_text(encoding="utf-8", errors="replace")
    status = classify_result(returncode, log_text)
    process_stats = read_process_stats(jit_stats_dir)
    all_new_functions = new_function_names(process_stats)
    module_new_functions = module_function_names(process_stats, test)
    compiled_delta = sum(
        int(process.get("compiled_delta", 0)) for process in process_stats
    )

    result = {
        "test": test,
        "index": index,
        "status": status,
        "returncode": returncode,
        "elapsed_seconds": elapsed,
        "timed_out": timed_out,
        "runner_summary": str(json_summary_file),
        "log": str(log_file),
        "jit_stats_dir": str(jit_stats_dir),
        "jit_process_count": len(process_stats),
        "compiled_delta": compiled_delta,
        "compiled_new_count": len(all_new_functions),
        "module_new_count": len(module_new_functions),
    }
    if args.include_jit_details:
        result.update(
            {
                "compiled_new_functions": all_new_functions,
                "module_new_functions": module_new_functions,
                "process_stats": process_stats,
            }
        )
    print(
        f"          {status} rc={returncode} "
        f"delta={compiled_delta} "
        f"new={len(all_new_functions)} module_new={len(module_new_functions)} "
        f"elapsed={elapsed}s",
        flush=True,
    )
    return result


def write_tsv(path: Path, results: list[dict[str, Any]]) -> None:
    lines = [
        "\t".join(
            [
                "index",
                "test",
                "status",
                "returncode",
                "elapsed_seconds",
                "compiled_new_count",
                "compiled_delta",
                "module_new_count",
                "jit_process_count",
                "log",
            ]
        )
    ]
    for result in results:
        lines.append(
            "\t".join(
                [
                    str(result["index"]),
                    str(result["test"]),
                    str(result["status"]),
                    str(result["returncode"]),
                    str(result["elapsed_seconds"]),
                    str(result["compiled_new_count"]),
                    str(result["compiled_delta"]),
                    str(result["module_new_count"]),
                    str(result["jit_process_count"]),
                    str(result["log"]),
                ]
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=["frame-eval-jit-all", "frame-eval-adaptive-aware"],
        default="frame-eval-jit-all",
    )
    parser.add_argument("--test-from-file")
    parser.add_argument("-t", "--test", action="append")
    parser.add_argument("--defer-pattern", action="append", default=[])
    parser.add_argument(
        "--num-workers",
        default="1",
        help="number of Lib/test modules to probe concurrently, or 'auto'",
    )
    parser.add_argument("--worker-timeout", type=int, default=20 * 60)
    parser.add_argument("--per-module-timeout", type=int, default=25 * 60)
    parser.add_argument(
        "--adaptive-compile-after",
        type=int,
        default=lib_test_runner.DEFAULT_ADAPTIVE_AWARE_COMPILE_AFTER,
        help="AutoJIT threshold for frame-eval-adaptive-aware",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--json-summary-file", required=True)
    parser.add_argument("--tsv-summary-file", required=True)
    parser.add_argument(
        "--no-fail-on-test-failure",
        action="store_true",
        help="always return 0 after writing summaries",
    )
    parser.add_argument(
        "--include-jit-details",
        action="store_true",
        help="embed per-function JIT details in the JSON summary",
    )
    args = parser.parse_args(argv)
    try:
        adaptive_compile_after = lib_test_runner.adaptive_compile_after_for_mode(
            args.mode, args.adaptive_compile_after
        )
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    try:
        num_workers = resolve_num_workers(args.num_workers)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))

    skip_files, skip_modules, _ = lib_test_runner.load_skip_metadata(mode=args.mode)
    gate_skip_files, gate_skip_modules, _ = lib_test_runner.load_gate_skip_metadata(
        args.mode
    )
    skip_modules.update(gate_skip_modules)

    tests = lib_test_runner.normalize_tests(args.test)
    if tests is None and args.test_from_file:
        tests = lib_test_runner.normalize_tests(
            lib_test_runner.read_test_file(Path(args.test_from_file))
        )
    if tests is None:
        tests = lib_test_runner.discover_lib_tests(skip_modules)
    tests = lib_test_runner.defer_tests(tests, args.defer_pattern)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_lines(output_dir / "modules.txt", tests)

    work_items = list(enumerate(tests, 1))
    if num_workers == 1:
        results = [
            run_module(
                test=test,
                index=index,
                total=len(tests),
                args=args,
                output_dir=output_dir,
            )
            for index, test in work_items
        ]
    else:
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [
                executor.submit(
                    run_module,
                    test=test,
                    index=index,
                    total=len(tests),
                    args=args,
                    output_dir=output_dir,
                )
                for index, test in work_items
            ]
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
        results.sort(key=lambda result: result["index"])

    status_counts: dict[str, int] = {}
    for result in results:
        status_counts[result["status"]] = status_counts.get(result["status"], 0) + 1

    summary = {
        "mode": args.mode,
        "returncode": 0,
        "adaptive_compile_after": adaptive_compile_after,
        "num_workers": num_workers,
        "test_count": len(tests),
        "status_counts": dict(sorted(status_counts.items())),
        "compiled_new_zero": [
            result["test"]
            for result in results
            if result["compiled_new_count"] == 0
        ],
        "compiled_delta_zero": [
            result["test"] for result in results if result["compiled_delta"] == 0
        ],
        "module_new_zero": [
            result["test"] for result in results if result["module_new_count"] == 0
        ],
        "skip_files": skip_files,
        "gate_skip_files": gate_skip_files,
        "results": results,
    }
    if args.no_fail_on_test_failure:
        returncode = 0
    else:
        unexpected_statuses = {"env_changed", "fail", "timeout"}
        returncode = 1 if any(
            result["status"] in unexpected_statuses for result in results
        ) else 0
    summary["returncode"] = returncode
    Path(args.json_summary_file).write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    write_tsv(Path(args.tsv_summary_file), results)
    return returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
