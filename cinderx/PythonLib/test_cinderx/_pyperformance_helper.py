import os
from pathlib import Path


def find_pyperformance_benchmark(module_dir: str) -> Path | None:
    candidates: list[Path] = []

    for env_name in ("PYPERFORMANCE_ROOT", "PYPERF_ROOT", "PY_PERFORMANCE_ROOT"):
        root = os.environ.get(env_name)
        if not root:
            continue
        root_path = Path(root)
        candidates.append(
            root_path / "pyperformance" / "data-files" / "benchmarks" / module_dir / "run_benchmark.py"
        )
        candidates.append(root_path / module_dir / "run_benchmark.py")

    try:
        import pyperformance  # type: ignore[import-not-found]
    except ImportError:
        pyperformance = None

    if pyperformance is not None:
        pkg_root = Path(pyperformance.__file__).resolve().parent
        candidates.append(
            pkg_root / "data-files" / "benchmarks" / module_dir / "run_benchmark.py"
        )

    home = Path.home()
    candidates.append(
        home / "Repo" / "pyperformance" / "pyperformance" / "data-files" / "benchmarks" / module_dir / "run_benchmark.py"
    )
    candidates.append(
        home / "Agents-Repo" / "pyperformance" / "pyperformance" / "data-files" / "benchmarks" / module_dir / "run_benchmark.py"
    )

    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if path.exists():
            return path
    return None
