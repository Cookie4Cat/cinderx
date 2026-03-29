#!/usr/bin/env python3
"""Run attach-based perf diagnostics for CPU-bound targets on ARM.

This script is meant to run on the ARM host. It standardizes the flow for:
1) spawning a target process,
2) waiting until it is ready to profile,
3) verifying the target is consuming CPU,
4) collecting perf stat / perf record artifacts,
5) writing a summary bundle to an output directory.

Targets supported today:
- busy-loop: shell spin loop
- python-busy: Python CPU loop
- deltablue: compiled-only steady-state benchmark via profile_steady_autojit.py
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import sysconfig
import time
from pathlib import Path


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def read_proc_cpu_ticks(pid: int) -> int:
    stat_fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
    utime = int(stat_fields[13])
    stime = int(stat_fields[14])
    return utime + stime


def wait_for_path(path: Path, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return True
        time.sleep(0.1)
    return path.exists() and path.stat().st_size > 0


def wait_for_pid_exit(pid: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.1)
    return False


def terminate_process_group(proc: subprocess.Popen[str], timeout_s: float) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=timeout_s)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    proc.wait(timeout=timeout_s)


def run_command(
    argv: list[str],
    *,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
    check: bool = False,
    env: dict[str, str] | None = None,
    text: bool = True,
) -> subprocess.CompletedProcess[str]:
    stdout_handle = stdout_path.open("w", encoding="utf-8") if stdout_path else subprocess.PIPE
    stderr_handle = stderr_path.open("w", encoding="utf-8") if stderr_path else subprocess.PIPE
    try:
        return subprocess.run(
            argv,
            check=check,
            env=env,
            text=text,
            stdout=stdout_handle,
            stderr=stderr_handle,
        )
    finally:
        if stdout_path:
            stdout_handle.close()
        if stderr_path:
            stderr_handle.close()


def summarize_perf_report(data_path: Path, report_path: Path) -> dict[str, object]:
    summary: dict[str, object] = {
        "data_size_bytes": data_path.stat().st_size if data_path.exists() else 0,
        "report_size_bytes": report_path.stat().st_size if report_path.exists() else 0,
        "has_samples": False,
    }
    if not report_path.exists():
        return summary

    lines = report_path.read_text(encoding="utf-8", errors="replace").splitlines()
    excerpt = [line for line in lines if line.strip()][:12]
    if excerpt:
        summary["report_excerpt"] = excerpt

    samples_line = next(
        (line.strip() for line in lines if line.lstrip().startswith("# Samples:")),
        "",
    )
    if samples_line:
        summary["has_samples"] = True
        summary["samples_line"] = samples_line
    return summary


def default_deltablue_module_path() -> Path:
    purelib = Path(sysconfig.get_path("purelib"))
    module_path = purelib / "benchmarks" / "bm_deltablue" / "run_benchmark.py"
    if not module_path.exists():
        raise FileNotFoundError(
            f"unable to locate deltablue benchmark module at {module_path}"
        )
    return module_path


def build_target_command(
    args: argparse.Namespace,
    out_dir: Path,
) -> tuple[list[str], Path | None, bool]:
    if args.target == "busy-loop":
        return ["bash", "-lc", "while :; do :; done"], None, False

    if args.target == "python-busy":
        code = (
            "import math\n"
            "x = 0.1\n"
            "while True:\n"
            "    x = math.sin(x) * math.cos(x) + 0.1\n"
        )
        return [sys.executable, "-c", code], None, False

    if args.target == "deltablue":
        ready_path = out_dir / "target_ready.json"
        result_path = out_dir / "target_result.json"
        module_path = Path(args.module_path) if args.module_path else default_deltablue_module_path()
        cmd = [
            sys.executable,
            str(Path(__file__).with_name("profile_steady_autojit.py")),
            "--module-path",
            str(module_path),
            "--module-name",
            args.module_name,
            "--bench-func",
            args.bench_func,
            "--bench-args-json",
            args.bench_args_json,
            "--autojit",
            str(args.autojit),
            "--warmup-min-runs",
            str(args.warmup_min_runs),
            "--stabilize-rounds",
            str(args.stabilize_rounds),
            "--attach-wait-seconds",
            str(args.attach_wait_seconds),
            "--steady-seconds",
            str(args.steady_seconds),
            "--ready-file",
            str(ready_path),
            "--output",
            str(result_path),
        ]
        if args.specialized_opcodes:
            cmd.append("--specialized-opcodes")
        return cmd, ready_path, True

    raise ValueError(f"unsupported target {args.target}")


def parse_ready_pid(ready_path: Path) -> int:
    payload = json.loads(ready_path.read_text(encoding="utf-8"))
    pid = int(payload["pid"])
    return pid


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["busy-loop", "python-busy", "deltablue"], required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--startup-wait-seconds", type=float, default=1.0)
    parser.add_argument("--ready-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--cpu-tick-wait-seconds", type=float, default=0.5)
    parser.add_argument("--terminate-timeout-seconds", type=float, default=5.0)
    parser.add_argument("--perf-stat-seconds", type=float, default=5.0)
    parser.add_argument("--perf-record-seconds", type=float, default=10.0)
    parser.add_argument("--stat-events", default="cpu-clock,task-clock,cycles,instructions")
    parser.add_argument("--record-events", default="cpu-clock")
    parser.add_argument("--record-frequency", type=int, default=999)
    parser.add_argument("--call-graph", choices=["none", "fp", "dwarf"], default="none")
    parser.add_argument("--profile-start-delay-seconds", type=float, default=None)
    parser.add_argument("--specialized-opcodes", action="store_true")

    parser.add_argument("--module-path", default="")
    parser.add_argument("--module-name", default="bm_deltablue_run_benchmark")
    parser.add_argument("--bench-func", default="delta_blue")
    parser.add_argument("--bench-args-json", default="[100]")
    parser.add_argument("--autojit", type=int, default=50)
    parser.add_argument("--warmup-min-runs", type=int, default=30)
    parser.add_argument("--stabilize-rounds", type=int, default=8)
    parser.add_argument("--attach-wait-seconds", type=float, default=20.0)
    parser.add_argument("--steady-seconds", type=float, default=20.0)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    target_cmd, ready_path, target_exits_on_its_own = build_target_command(args, out_dir)
    target_log = out_dir / "target.log"

    meta: dict[str, object] = {
        "target": args.target,
        "target_cmd": target_cmd,
        "cwd": os.getcwd(),
        "perf_version": subprocess.run(
            ["perf", "--version"], capture_output=True, check=False, text=True
        ).stdout.strip(),
        "record_events": split_csv(args.record_events),
        "stat_events": split_csv(args.stat_events),
        "call_graph": args.call_graph,
    }
    profile_start_delay = args.profile_start_delay_seconds
    if profile_start_delay is None:
        profile_start_delay = args.attach_wait_seconds if args.target == "deltablue" else 0.0
    meta["profile_start_delay_seconds"] = profile_start_delay

    with target_log.open("w", encoding="utf-8") as log_handle:
        proc = subprocess.Popen(
            target_cmd,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )

    target_pid = proc.pid
    if ready_path is not None:
        if not wait_for_path(ready_path, args.ready_timeout_seconds):
            meta["ready_error"] = f"ready file not produced: {ready_path}"
            terminate_process_group(proc, args.terminate_timeout_seconds)
            (out_dir / "summary.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return 1
        target_pid = parse_ready_pid(ready_path)
        meta["ready_file"] = str(ready_path)
    else:
        time.sleep(args.startup_wait_seconds)

    meta["target_pid"] = target_pid
    if profile_start_delay > 0:
        time.sleep(profile_start_delay)

    ticks_before = read_proc_cpu_ticks(target_pid)
    time.sleep(args.cpu_tick_wait_seconds)
    ticks_after = read_proc_cpu_ticks(target_pid)
    meta["cpu_ticks_before"] = ticks_before
    meta["cpu_ticks_after"] = ticks_after
    meta["cpu_ticks_delta"] = ticks_after - ticks_before

    stat_path = out_dir / "perf_stat.txt"
    stat_events = ",".join(split_csv(args.stat_events))
    stat_cmd = [
        "perf",
        "stat",
        "-e",
        stat_events,
        "-p",
        str(target_pid),
        "--",
        "sleep",
        str(args.perf_stat_seconds),
    ]
    stat_proc = run_command(stat_cmd, stderr_path=stat_path, check=False)
    meta["perf_stat_returncode"] = stat_proc.returncode

    record_results = []
    for event in split_csv(args.record_events):
        event_key = event.replace("-", "_")
        data_path = out_dir / f"perf_{event_key}.data"
        record_log = out_dir / f"perf_{event_key}.record.log"
        report_path = out_dir / f"perf_{event_key}.report.txt"

        record_cmd = [
            "perf",
            "record",
            "-e",
            event,
            "-F",
            str(args.record_frequency),
            "-o",
            str(data_path),
            "-p",
            str(target_pid),
        ]
        if args.call_graph != "none":
            record_cmd.extend(["--call-graph", args.call_graph])
        record_cmd.extend(["--", "sleep", str(args.perf_record_seconds)])

        record_proc = run_command(record_cmd, stderr_path=record_log, check=False)
        report_proc = run_command(
            [
                "perf",
                "report",
                "--stdio",
                "--percent-limit",
                "1",
                "-i",
                str(data_path),
            ],
            stdout_path=report_path,
            stderr_path=report_path.with_suffix(".stderr.txt"),
            check=False,
        )
        record_results.append(
            {
                "event": event,
                "record_returncode": record_proc.returncode,
                "report_returncode": report_proc.returncode,
                "data_path": str(data_path),
                "record_log": str(record_log),
                "report_path": str(report_path),
                **summarize_perf_report(data_path, report_path),
            }
        )

    if target_exits_on_its_own:
        proc.wait(timeout=args.attach_wait_seconds + args.steady_seconds + 30.0)
    else:
        terminate_process_group(proc, args.terminate_timeout_seconds)
        wait_for_pid_exit(target_pid, args.terminate_timeout_seconds)

    meta["target_returncode"] = proc.returncode
    meta["record_results"] = record_results

    summary_path = out_dir / "summary.json"
    summary_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
