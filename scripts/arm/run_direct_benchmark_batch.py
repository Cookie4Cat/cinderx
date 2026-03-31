#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class BenchmarkResult:
    benchmark: str
    benchmark_dir: str
    status: str
    exit_code: int
    metric_name: str | None
    metric_seconds: float | None
    metric_display: str | None
    exit_detail: str
    stdout_path: str
    stderr_path: str
    json_path: str
    jit_log_glob: str
    jit_log_count: int
    hir_count: int


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_output_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("/tmp") / f"direct_benchmark_batch_{stamp}"


def parse_benchmarks(values: list[str]) -> list[str]:
    tokens: list[str] = []
    for value in values:
        for token in value.replace(",", " ").split():
            token = token.strip()
            if token:
                tokens.append(token)
    if not tokens:
        raise SystemExit("ERROR: at least one benchmark is required")
    return tokens


def benchmark_dir_name(name: str) -> str:
    return name if name.startswith("bm_") else f"bm_{name}"


def find_run_script(python_exe: str, benchmark_dir: str) -> Path:
    probe = (
        "import pyperformance, pathlib; "
        "root = pathlib.Path(pyperformance.__file__).resolve().parent / "
        "'data-files' / 'benchmarks' / "
        f"{benchmark_dir!r} / 'run_benchmark.py'; "
        "print(root)"
    )
    result = subprocess.run(
        [python_exe, "-c", probe],
        check=True,
        capture_output=True,
        text=True,
    )
    path = Path(result.stdout.strip())
    if not path.is_file():
        raise FileNotFoundError(f"missing benchmark script: {path}")
    return path


def load_metric(json_path: Path) -> tuple[str | None, float | None]:
    if not json_path.is_file():
        return None, None
    with json_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    benches = payload.get("benchmarks", [])
    if not benches:
        return None, None
    bench = benches[0]
    name = bench.get("metadata", {}).get("name")
    runs = bench.get("runs", [])
    values: list[float] = []
    for run in runs:
        values.extend(float(v) for v in run.get("values", []))
    if not values:
        return name, None
    return name, sum(values) / len(values)


def load_metric_display(stdout_path: Path, benchmark: str) -> str | None:
    if not stdout_path.is_file():
        return None

    prefix = f"{benchmark}:"
    try:
        lines = stdout_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    for line in reversed(lines):
        text = line.strip()
        if not text:
            continue
        if text.startswith(prefix):
            return text[len(prefix) :].strip() or text
        if "Mean +- std dev:" in text or "Mean ± std dev:" in text:
            return text
    return None


def count_hir_lines(paths: list[Path]) -> int:
    total = 0
    needle = b"Optimized HIR for"
    for path in paths:
        try:
            with path.open("rb") as fh:
                for line in fh:
                    if needle in line:
                        total += 1
        except OSError:
            pass
    return total


def build_env(
    hook_dir: Path,
    jit_log_pattern: str,
    autojit: int,
    specialized_opcodes: int,
) -> dict[str, str]:
    env = os.environ.copy()
    old_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONJITAUTO"] = str(autojit)
    env["PYTHONJITSPECIALIZEDOPCODES"] = str(specialized_opcodes)
    env["PYTHONPATH"] = f"{hook_dir}{os.pathsep}{old_pythonpath}" if old_pythonpath else str(hook_dir)
    env["PYTHONJITHUGEPAGES"] = "0"
    env["PYTHONJITLOGFILE"] = jit_log_pattern
    env["PYTHONJITDUMPFINALHIR"] = "1"
    env["PYTHONJITDUMPSTATS"] = "1"
    return env


def run_one(
    python_exe: str,
    hook_dir: Path,
    out_dir: Path,
    benchmark: str,
    warmups: int,
    autojit: int,
    specialized_opcodes: int,
    debug_single_value: bool,
) -> BenchmarkResult:
    bench_dir = benchmark_dir_name(benchmark)
    run_script = find_run_script(python_exe, bench_dir)

    stdout_path = out_dir / f"{benchmark}.stdout"
    stderr_path = out_dir / f"{benchmark}.stderr"
    json_path = out_dir / f"{benchmark}.json"
    jit_log_glob = out_dir / f"{benchmark}.jit-*.log"
    jit_log_pattern = str(out_dir / f"{benchmark}.jit-{{pid}}.log")

    env = build_env(
        hook_dir=hook_dir,
        jit_log_pattern=jit_log_pattern,
        autojit=autojit,
        specialized_opcodes=specialized_opcodes,
    )

    cmd = [python_exe, str(run_script), "--warmups", str(warmups), "--output", str(json_path)]
    if debug_single_value:
        cmd.append("--debug-single-value")

    with stdout_path.open("w", encoding="utf-8") as out, stderr_path.open(
        "w", encoding="utf-8"
    ) as err:
        proc = subprocess.run(cmd, env=env, stdout=out, stderr=err)

    metric_name, metric_seconds = load_metric(json_path)
    metric_display = load_metric_display(stdout_path, benchmark)
    jit_logs = sorted(out_dir.glob(f"{benchmark}.jit-*.log"))
    hir_count = count_hir_lines(jit_logs)
    status = "ok" if proc.returncode == 0 else "fail"
    if proc.returncode < 0:
        try:
            exit_detail = signal.Signals(-proc.returncode).name
        except ValueError:
            exit_detail = f"signal {-proc.returncode}"
    else:
        exit_detail = str(proc.returncode)

    return BenchmarkResult(
        benchmark=benchmark,
        benchmark_dir=bench_dir,
        status=status,
        exit_code=proc.returncode,
        metric_name=metric_name,
        metric_seconds=metric_seconds,
        metric_display=metric_display,
        exit_detail=exit_detail,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        json_path=str(json_path),
        jit_log_glob=str(jit_log_glob),
        jit_log_count=len(jit_logs),
        hir_count=hir_count,
    )


def write_summary(results: list[BenchmarkResult], out_dir: Path) -> None:
    summary_json = out_dir / "summary.json"
    summary_tsv = out_dir / "summary.tsv"

    payload = {
        "generated_at": datetime.now().isoformat(),
        "results": [asdict(row) for row in results],
    }
    summary_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    headers = list(asdict(results[0]).keys()) if results else []
    with summary_tsv.open("w", encoding="utf-8") as fh:
        fh.write("\t".join(headers) + "\n")
        for row in results:
            record = asdict(row)
            fh.write(
                "\t".join("" if record[key] is None else str(record[key]) for key in headers)
                + "\n"
            )

    print(f"summary_json={summary_json}")
    print(f"summary_tsv={summary_tsv}")


def print_table(results: list[BenchmarkResult]) -> None:
    headers = [
        "benchmark",
        "status",
        "result",
        "exit",
    ]
    rows = []
    for row in results:
        rows.append(
            [
                row.benchmark,
                row.status,
                row.metric_display or "",
                row.exit_detail,
            ]
        )

    widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    def fmt(parts: list[str]) -> str:
        return "  ".join(part.ljust(widths[idx]) for idx, part in enumerate(parts))

    print(fmt(headers))
    print(fmt(["-" * w for w in widths]))
    for row in rows:
        print(fmt(row))

    ok_rows = [row for row in results if row.metric_seconds is not None and row.exit_code == 0]
    if ok_rows:
        fastest = min(ok_rows, key=lambda row: row.metric_seconds or float("inf"))
        slowest = max(ok_rows, key=lambda row: row.metric_seconds or float("-inf"))
        print()
        print(f"fastest={fastest.benchmark} {fastest.metric_display or fastest.metric_seconds}")
        print(f"slowest={slowest.benchmark} {slowest.metric_display or slowest.metric_seconds}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmarks", nargs="+", help="benchmark names, supports comma-separated input")
    parser.add_argument("--python", default=sys.executable, help="python executable used to run run_benchmark.py")
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--autojit", type=int, default=2)
    parser.add_argument("--specialized-opcodes", type=int, default=1)
    parser.add_argument("--output-dir", default=str(default_output_dir()))
    parser.add_argument(
        "--debug-single-value",
        action="store_true",
        help="enable --debug-single-value for fast debugging runs",
    )
    args = parser.parse_args()

    benchmarks = parse_benchmarks(args.benchmarks)
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    hook_dir = repo_root() / "scripts" / "arm" / "pyperf_env_hook"
    if not (hook_dir / "sitecustomize.py").is_file():
        raise SystemExit(f"ERROR: missing hook dir: {hook_dir}")

    results: list[BenchmarkResult] = []
    for benchmark in benchmarks:
        print(f">> running {benchmark}")
        result = run_one(
            python_exe=args.python,
            hook_dir=hook_dir,
            out_dir=out_dir,
            benchmark=benchmark,
            warmups=args.warmups,
            autojit=args.autojit,
            specialized_opcodes=args.specialized_opcodes,
            debug_single_value=args.debug_single_value,
        )
        results.append(result)
        print(
            f"   status={result.status} exit={result.exit_code} "
            f"detail={result.exit_detail} result={result.metric_display!r}"
        )

    print()
    print_table(results)
    write_summary(results, out_dir)
    return 0 if all(row.exit_code == 0 for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
