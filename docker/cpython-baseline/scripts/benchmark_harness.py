#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import NamedTuple


class BenchmarkSpec(NamedTuple):
    name: str
    module_dir: str
    bench_func: str
    bench_args: tuple[int, ...]
    benchmark_url: str


BENCHMARK_SPECS: dict[str, BenchmarkSpec] = {
    "generators": BenchmarkSpec(
        name="generators",
        module_dir="bm_generators",
        bench_func="bench_generators",
        bench_args=(1,),
        benchmark_url="https://raw.githubusercontent.com/python/pyperformance/main/pyperformance/data-files/benchmarks/bm_generators/run_benchmark.py",
    ),
    "mdp": BenchmarkSpec(
        name="mdp",
        module_dir="bm_mdp",
        bench_func="bench_mdp",
        bench_args=(1,),
        benchmark_url="https://raw.githubusercontent.com/python/pyperformance/main/pyperformance/data-files/benchmarks/bm_mdp/run_benchmark.py",
    ),
}


def resolve_benchmark(name: str) -> BenchmarkSpec:
    try:
        return BENCHMARK_SPECS[name]
    except KeyError as exc:
        raise KeyError(f"unsupported benchmark: {name}") from exc


def load_benchmark(benchmarks_root: Path | str, name: str):
    spec = resolve_benchmark(name)
    root = Path(benchmarks_root)
    module_path = root / spec.module_dir / "run_benchmark.py"
    import_spec = importlib.util.spec_from_file_location(spec.module_dir, module_path)
    if import_spec is None or import_spec.loader is None:
        raise RuntimeError(f"failed to load benchmark module from {module_path}")
    module = importlib.util.module_from_spec(import_spec)
    sys.path.insert(0, str(module_path.parent))
    try:
        import_spec.loader.exec_module(module)
    finally:
        try:
            sys.path.remove(str(module_path.parent))
        except ValueError:
            pass
    bench = getattr(module, spec.bench_func)
    return module, bench


def benchmark_module_path(benchmarks_root: Path, name: str) -> Path:
    spec = resolve_benchmark(name)
    return benchmarks_root / spec.module_dir / "run_benchmark.py"


def stock_cpython_source_root() -> Path:
    return Path(os.environ.get("CPYTHON_SOURCE_ROOT", "/cpython"))


def stock_cpython_prefix() -> Path:
    return Path(os.environ.get("CPYTHON_INSTALL_ROOT", "/opt/cpython-jit"))


def stock_cpython_python() -> Path:
    return stock_cpython_prefix() / "bin/python3"


def stock_cpython_configure_args() -> tuple[str, ...]:
    return (
        "./configure",
        f"--prefix={stock_cpython_prefix()}",
        "--enable-experimental-jit=yes-off",
    )


def stock_cpython_runtime_env() -> dict[str, str]:
    return {"PYTHON_JIT": "1"}


def cinderx_wheel_glob() -> Path:
    return Path(os.environ.get("CINDERX_WHEEL_GLOB", "/dist/cinderx-*-linux_aarch64.whl"))


def default_opt_env_file(name: str) -> Path:
    resolve_benchmark(name)
    return Path("/scripts/configs") / name / "stable.env"


def results_root() -> Path:
    return Path(os.environ.get("RESULTS_ROOT", "/results"))


def load_opt_env_file(path: Path | str | None) -> dict[str, str]:
    if path is None:
        return {}
    env_path = Path(path)
    if not env_path.exists():
        return {}
    env: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not key:
            raise ValueError(f"invalid env line in {env_path}: {raw_line!r}")
        env[key] = value
    return env


def opt_config_name(path: Path | str | None, enable_optimization: bool) -> str:
    if not enable_optimization:
        return "baseline"
    if path is None:
        return "stable"
    return Path(path).stem


def comparison_results_path(results_root: Path | str, benchmark: str, config_name: str) -> Path:
    return Path(results_root) / benchmark / config_name / "comparison.json"

