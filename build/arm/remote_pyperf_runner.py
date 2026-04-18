#!/opt/python-3.14/bin/python3.14
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shlex
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts" / "arm_pyperf"
BOOTSTRAP = ARTIFACTS / "bootstrap"
BIN = ARTIFACTS / "bin"
TOOLS = ARTIFACTS / "tools"
WHEELS = ARTIFACTS / "wheels"
DEPS = Path("/root/src/cinderx-deps")
VENV = Path("/root/venv-cinderx-meta-main-gcc14")
PYTHON = Path("/opt/python-3.14/bin/python3.14")
CPY_JIT = Path("/opt/cpython-jit/bin/python3.14")
CANDIDATE_SITE_PACKAGES = VENV / "lib" / "python3.14" / "site-packages"
CPY_JIT_SITE_PACKAGES = Path("/opt/cpython-jit/lib/python3.14/site-packages")
CC = "/opt/gcc-14.2/bin/gcc"
CXX = "/opt/gcc-14.2/bin/g++"
PARALLEL_HASHMAP_LOCAL = DEPS / "parallel-hashmap"
FMT_LOCAL = DEPS / "fmt"
USDT_LOCAL = DEPS / "usdt"
CAPSTONE_LOCAL = DEPS / "capstone"
PARALLEL_HASHMAP_CACHE = Path(
    "/root/cinderx-main-run/build-rt-gcc14/_deps/parallel-hashmap-src"
)
FMT_CACHE = Path("/root/cinderx-main-run/build-rt-gcc14/_deps/fmt-src")
USDT_CACHE = Path("/root/cinderx-main-run/build-rt-gcc14/_deps/usdt-src")
CAPSTONE_CACHE = Path("/root/cinderx-main-run/build-rt-gcc14-opt/_deps/capstone-src")

TARGET_BENCHES = "richards,deltablue"
GUARDRAIL_BENCHES = "richards,deltablue,nbody,fannkuch,binary_trees,spectral_norm"
WARMUPS = 5
COMPILE_AFTER_N_CALLS = 5
RICHARDS_SCRIPT = (
    "/opt/python-3.14/lib/python3.14/site-packages/pyperformance/"
    "data-files/benchmarks/bm_richards/run_benchmark.py"
)
DELTABLUE_SCRIPT = (
    "/opt/python-3.14/lib/python3.14/site-packages/pyperformance/"
    "data-files/benchmarks/bm_deltablue/run_benchmark.py"
)
RAYTRACE_SCRIPT = (
    "/opt/python-3.14/lib/python3.14/site-packages/pyperformance/"
    "data-files/benchmarks/bm_raytrace/run_benchmark.py"
)


def run(cmd: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(shlex.quote(x) for x in cmd), flush=True)
    return subprocess.run(
        cmd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=str(cwd) if cwd else None,
    )


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def ensure_bootstrap() -> None:
    BOOTSTRAP.mkdir(parents=True, exist_ok=True)
    BIN.mkdir(parents=True, exist_ok=True)
    TOOLS.mkdir(parents=True, exist_ok=True)
    WHEELS.mkdir(parents=True, exist_ok=True)
    (BOOTSTRAP / "sitecustomize.py").write_text(
        (
            "from pathlib import Path\n"
            "import os\n"
            "import sys\n"
            "\n"
            "argv0 = Path(sys.argv[0]).name if sys.argv else ''\n"
            "skip_jit = argv0 == '_pythoninfo.py' or os.environ.get('CINDERX_DISABLE_SITE_JIT') == '1'\n"
            "if not skip_jit:\n"
            "    import cinderx.jit\n"
            "    cinderx.jit.enable()\n"
            f"    cinderx.jit.compile_after_n_calls({COMPILE_AFTER_N_CALLS})\n"
            "    cinderx.jit.enable_specialized_opcodes()\n"
            "    cinderx.jit.enable_emit_type_annotation_guards()\n"
            "    cinderx.jit.set_max_code_size(1 << 30)\n"
        ),
        encoding="utf-8",
    )
    write_executable(
        BIN / "cpython-jit.sh",
        f"#!/bin/bash\nexport PYTHON_JIT=1\nexec {CPY_JIT} \"$@\"\n",
    )
    write_executable(
        BIN / "cinderx.sh",
        (
            "#!/bin/bash\n"
            f"export PYTHONPATH={BOOTSTRAP}:${{PYTHONPATH}}\n"
            f"exec {VENV / 'bin/python3.14'} \"$@\"\n"
        ),
    )
    write_executable(
        BIN / "cinderx-focused.sh",
        (
            "#!/bin/bash\n"
            "export CINDERX_DISABLE_SITE_JIT=1\n"
            "export CINDERX_ENABLE_FOCUSED_JIT=1\n"
            "export FOCUSED_HARD_EXIT=1\n"
            f"export PYTHONPATH={BOOTSTRAP}:${{PYTHONPATH}}\n"
            f"exec {VENV / 'bin/python3.14'} \"$@\"\n"
        ),
    )
    (TOOLS / "focused_bench.py").write_text(
        (
            "from __future__ import annotations\n"
            "\n"
            "import argparse\n"
            "import importlib.util\n"
            "import os\n"
            "import sys\n"
            "import time\n"
            "import types\n"
            "from pathlib import Path\n"
            "\n"
            "RICHARDS = Path(\n"
            f"    {RICHARDS_SCRIPT!r}\n"
            ")\n"
            "DELTABLUE = Path(\n"
            f"    {DELTABLUE_SCRIPT!r}\n"
            ")\n"
            "RAYTRACE = Path(\n"
            f"    {RAYTRACE_SCRIPT!r}\n"
            ")\n"
            "\n"
            "def load_module(name: str, path: Path):\n"
            "    if 'pyperf' not in sys.modules:\n"
            "        sys.modules['pyperf'] = types.SimpleNamespace(Runner=object, perf_counter=time.perf_counter)\n"
            "    spec = importlib.util.spec_from_file_location(name, path)\n"
            "    mod = importlib.util.module_from_spec(spec)\n"
            "    assert spec.loader is not None\n"
            "    spec.loader.exec_module(mod)\n"
            "    return mod\n"
            "\n"
            "def make_runner(name: str):\n"
            "    if name == 'richards':\n"
            "        mod = load_module('bm_richards_mod', RICHARDS)\n"
            "        runner = mod.Richards()\n"
            "        def run_richards():\n"
            "            ok = runner.run(1)\n"
            "            if ok is not True:\n"
            "                raise RuntimeError(f'richards failed: {ok!r}')\n"
            "        return run_richards\n"
            "    if name == 'deltablue':\n"
            "        mod = load_module('bm_deltablue_mod', DELTABLUE)\n"
            "        def run_deltablue():\n"
            "            mod.delta_blue(100)\n"
            "        return run_deltablue\n"
            "    if name == 'raytrace':\n"
            "        mod = load_module('bm_raytrace_mod', RAYTRACE)\n"
            "        def run_raytrace():\n"
            "            mod.bench_raytrace(1, mod.DEFAULT_WIDTH, mod.DEFAULT_HEIGHT, None)\n"
            "        return run_raytrace\n"
            "    raise ValueError(name)\n"
            "\n"
            "def maybe_enable_cinderx() -> None:\n"
            "    if os.environ.get('CINDERX_ENABLE_FOCUSED_JIT') != '1':\n"
            "        return\n"
            "    import cinderx.jit\n"
            "    cinderx.jit.enable()\n"
            f"    cinderx.jit.compile_after_n_calls({COMPILE_AFTER_N_CALLS})\n"
            "    cinderx.jit.enable_specialized_opcodes()\n"
            "    cinderx.jit.enable_emit_type_annotation_guards()\n"
            "    cinderx.jit.set_max_code_size(1 << 30)\n"
            "\n"
            "def maybe_dump_jit_stats() -> None:\n"
            "    if os.environ.get('CINDERX_ENABLE_FOCUSED_JIT') != '1':\n"
            "        return\n"
            "    if os.environ.get('CINDERX_FOCUSED_DUMP_STATS') != '1':\n"
            "        return\n"
            "    import cinderx.jit\n"
            "    try:\n"
            "        compiled = cinderx.jit.get_compiled_functions()\n"
            "        print(f'compiled_count={len(compiled)}')\n"
            "        for func in compiled[:20]:\n"
            "            try:\n"
            "                counts = cinderx.jit.get_function_hir_opcode_counts(func)\n"
            "                print(f'compiled {func.__module__} {func.__qualname__} {counts}')\n"
            "            except Exception as exc:\n"
            "                print(f'compiled_err {func!r} {exc!r}')\n"
            "        print(f'runtime_stats={cinderx.jit.get_and_clear_runtime_stats()}')\n"
            "    except Exception as exc:\n"
            "        print(f'jit_stats_error={exc!r}')\n"
            "\n"
            "def main() -> int:\n"
            "    parser = argparse.ArgumentParser()\n"
            "    parser.add_argument('bench', choices=['richards', 'deltablue', 'raytrace'])\n"
            "    parser.add_argument('--warmups', type=int, default=5)\n"
            "    parser.add_argument('--loops', type=int, default=20)\n"
            "    args = parser.parse_args()\n"
            "    maybe_enable_cinderx()\n"
            "    bench = make_runner(args.bench)\n"
            "    for _ in range(args.warmups):\n"
            "        bench()\n"
            "    started = time.perf_counter()\n"
            "    for _ in range(args.loops):\n"
            "        bench()\n"
            "    elapsed = time.perf_counter() - started\n"
            "    print(f'bench={args.bench} loops={args.loops} elapsed={elapsed:.6f}')\n"
            "    maybe_dump_jit_stats()\n"
            "    sys.stdout.flush()\n"
            "    sys.stderr.flush()\n"
            "    if os.environ.get('FOCUSED_HARD_EXIT') == '1':\n"
            "        os._exit(0)\n"
            "    return 0\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    raise SystemExit(main())\n"
        ),
        encoding="utf-8",
    )
    (TOOLS / "run_pyperformance_cinderx.py").write_text(
        (
            "from __future__ import annotations\n"
            "\n"
            "import os\n"
            "import subprocess\n"
            "import sys\n"
            "from pathlib import Path\n"
            "\n"
            "import pyperformance._benchmark as pyperformance_benchmark\n"
            "import pyperformance.cli\n"
            "from pyperformance.venv import VenvForBenchmarks\n"
            "\n"
            "WHEEL = Path(os.environ['CINDERX_WHEEL']).resolve()\n"
            "BOOTSTRAP = Path(os.environ['CINDERX_BOOTSTRAP']).resolve()\n"
            "MARKER_NAME = '.cinderx-wheel-installed'\n"
            "ORIG_ENSURE_REQS = VenvForBenchmarks.ensure_reqs\n"
            "ORIG_PREP_CMD = pyperformance_benchmark._prep_cmd\n"
            "\n"
            "def install_cinderx_once(venv: VenvForBenchmarks) -> None:\n"
            "    marker = Path(venv.root) / MARKER_NAME\n"
            "    marker_value = f'{WHEEL}|{WHEEL.stat().st_size}|{WHEEL.stat().st_mtime_ns}'\n"
            "    if marker.exists() and marker.read_text(encoding='utf-8') == marker_value:\n"
            "        return\n"
            "    env = dict(venv._env)\n"
            "    env['PIP_DISABLE_PIP_VERSION_CHECK'] = '1'\n"
            "    cmd = [\n"
            "        venv.python,\n"
            "        '-m',\n"
            "        'pip',\n"
            "        'install',\n"
            "        '--force-reinstall',\n"
            "        '--no-deps',\n"
            "        str(WHEEL),\n"
            "    ]\n"
            "    print('+', ' '.join(cmd), flush=True)\n"
            "    subprocess.run(cmd, check=True, env=env)\n"
            "    marker.write_text(marker_value, encoding='utf-8')\n"
            "\n"
            "def patched_ensure_reqs(self, requirements=None):\n"
            "    install_cinderx_once(self)\n"
            "    return ORIG_ENSURE_REQS(self, requirements)\n"
            "\n"
            "def patched_prep_cmd(python, script, opts, runid, on_set_envvar=None):\n"
            "    argv, env = ORIG_PREP_CMD(python, script, opts, runid, on_set_envvar)\n"
            "    pyperformance_benchmark._insert_on_PYTHONPATH(str(BOOTSTRAP), env)\n"
            "    return argv, env\n"
            "\n"
            "VenvForBenchmarks.ensure_reqs = patched_ensure_reqs\n"
            "pyperformance_benchmark._prep_cmd = patched_prep_cmd\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    raise SystemExit(pyperformance.cli.main())\n"
        ),
        encoding="utf-8",
    )


def candidate_wheel() -> Path:
    wheels = sorted(WHEELS.glob("cinderx-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected exactly one candidate wheel in {WHEELS}, found {len(wheels)}")
    return wheels[0]


def build() -> None:
    ensure_bootstrap()
    if not VENV.exists():
        run([str(PYTHON), "-m", "venv", str(VENV)])
    env = os.environ.copy()
    env["CC"] = CC
    env["CXX"] = CXX
    if PARALLEL_HASHMAP_LOCAL.exists():
        env["CINDERX_PARALLEL_HASHMAP_SOURCE_DIR"] = str(PARALLEL_HASHMAP_LOCAL)
    elif PARALLEL_HASHMAP_CACHE.exists():
        env["CINDERX_PARALLEL_HASHMAP_SOURCE_DIR"] = str(PARALLEL_HASHMAP_CACHE)
    if FMT_LOCAL.exists():
        env["CINDERX_FMT_SOURCE_DIR"] = str(FMT_LOCAL)
    elif FMT_CACHE.exists():
        env["CINDERX_FMT_SOURCE_DIR"] = str(FMT_CACHE)
    if USDT_LOCAL.exists():
        env["CINDERX_USDT_SOURCE_DIR"] = str(USDT_LOCAL)
    elif USDT_CACHE.exists():
        env["CINDERX_USDT_SOURCE_DIR"] = str(USDT_CACHE)
    if CAPSTONE_LOCAL.exists():
        env["CINDERX_CAPSTONE_SOURCE_DIR"] = str(CAPSTONE_LOCAL)
    elif CAPSTONE_CACHE.exists():
        env["CINDERX_CAPSTONE_SOURCE_DIR"] = str(CAPSTONE_CACHE)
    for wheel in WHEELS.glob("*.whl"):
        wheel.unlink()
    run([str(VENV / "bin/python3.14"), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], env=env)
    run([str(VENV / "bin/python3.14"), "-m", "pip", "install", "--upgrade", "pyperf", "psutil"], env=env)
    run(
        [
            str(VENV / "bin/python3.14"),
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "-w",
            str(WHEELS),
            ".",
        ],
        env=env,
        cwd=ROOT,
    )
    run([str(VENV / "bin/python3.14"), "-m", "pip", "install", "--force-reinstall", "--no-build-isolation", "."], env=env, cwd=ROOT)


def metadata(interpreter: str, extra: dict[str, object]) -> dict[str, object]:
    base = {
        "root": str(ROOT),
        "interpreter": interpreter,
        "candidate_python": str(VENV / "bin/python3.14"),
        "compile_after_n_calls": COMPILE_AFTER_N_CALLS,
        "warmups": WARMUPS,
        "specialized_opcodes": True,
        "hir_inliner": False,
        "type_annotation_guards": True,
        "cc": CC,
        "cxx": CXX,
    }
    base.update(extra)
    return base


def preflight() -> None:
    ensure_bootstrap()
    if not VENV.exists():
        raise RuntimeError(f"candidate venv is missing: {VENV}; run build first")
    cp = run([str(CPY_JIT), "-c", "import sys; print(sys._jit.is_available(), sys._jit.is_enabled())"], env={**os.environ, "PYTHON_JIT": "1"})
    print(cp.stdout)
    cx = run(
        [
            str(VENV / "bin/python3.14"),
            "-c",
            (
                "import cinderx.jit\n"
                "cinderx.jit.enable()\n"
                f"cinderx.jit.compile_after_n_calls({COMPILE_AFTER_N_CALLS})\n"
                "def f(x):\n"
                "    return x + 1\n"
                "for i in range(20):\n"
                "    f(i)\n"
                "print(cinderx.jit.is_enabled(), cinderx.jit.is_jit_compiled(f))\n"
            ),
        ],
        env={**os.environ, "PYTHONPATH": str(BOOTSTRAP)},
    )
    print(cx.stdout)


def pyperf_run(
    python_exe: str,
    output: Path,
    benches: str,
    mode: str,
    *,
    launcher: list[str] | None = None,
    env: dict[str, str] | None = None,
    inherit_env: tuple[str, ...] = (),
    same_loops: Path | None = None,
) -> None:
    cmd = [
        *(launcher if launcher is not None else [str(PYTHON), "-m", "pyperformance"]),
        "run",
        "--affinity",
        "0",
        "--warmups",
        str(WARMUPS),
        "-b",
        benches,
        "-o",
        str(output),
        "-p",
        python_exe,
    ]
    if same_loops is not None:
        cmd.extend(["--same-loops", str(same_loops)])
    if inherit_env:
        cmd.extend(["--inherit-environ", ",".join(inherit_env)])
    cmd.append("--fast" if mode == "fast" else "--rigorous")
    run(cmd, env=env)


def pyperf_compare(base: Path, changed: Path, out: Path) -> None:
    cp = run([str(PYTHON), "-m", "pyperformance", "compare", "-O", "table", str(base), str(changed)])
    out.write_text(cp.stdout, encoding="utf-8")


@contextlib.contextmanager
def clean_cpython_jit_site_packages():
    moved: list[tuple[Path, Path]] = []
    try:
        if CPY_JIT_SITE_PACKAGES.exists():
            for path in CPY_JIT_SITE_PACKAGES.glob("__editable__.cinderx-*.pth"):
                hidden = path.with_suffix(path.suffix + ".disabled")
                if hidden.exists():
                    hidden.unlink()
                path.rename(hidden)
                moved.append((hidden, path))
        yield
    finally:
        for hidden, original in reversed(moved):
            if original.exists():
                original.unlink()
            if hidden.exists():
                hidden.rename(original)


def perf_stat(tag: str, wrapper: str, bench: str) -> None:
    out = ARTIFACTS / f"{tag}.{bench}.perf.txt"
    cmd = [
        "perf",
        "stat",
        "-o",
        str(out),
        "-e",
        "cycles,instructions,branches,branch-misses,cache-references,cache-misses",
        wrapper,
        str(TOOLS / "focused_bench.py"),
        bench,
        "--warmups",
        str(WARMUPS),
        "--loops",
        "20",
    ]
    run(cmd)


def bench(suite: str, mode: str, tag: str) -> None:
    ensure_bootstrap()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    benches = TARGET_BENCHES if suite == "target" else GUARDRAIL_BENCHES
    cpyjit = ARTIFACTS / f"{tag}.cpyjit.json"
    cinderx = ARTIFACTS / f"{tag}.cinderx.json"
    wheel = candidate_wheel()

    cpyjit_env = {**os.environ, "PYTHON_JIT": "1"}
    cinderx_env = {
        **os.environ,
        "CINDERX_WHEEL": str(wheel),
        "CINDERX_BOOTSTRAP": str(BOOTSTRAP),
    }
    with clean_cpython_jit_site_packages():
        pyperf_run(
            str(BIN / "cpython-jit.sh"),
            cpyjit,
            benches,
            mode,
            env=cpyjit_env,
            inherit_env=("PYTHON_JIT",),
        )
    pyperf_run(
        str(BIN / "cinderx.sh"),
        cinderx,
        benches,
        mode,
        launcher=[str(PYTHON), str(TOOLS / "run_pyperformance_cinderx.py")],
        env=cinderx_env,
        inherit_env=("PYTHONPATH",),
        same_loops=cpyjit,
    )

    try:
        pyperf_compare(cpyjit, cinderx, ARTIFACTS / f"{tag}.cpyjit_vs_cinderx.txt")
    except subprocess.CalledProcessError as exc:
        (ARTIFACTS / f"{tag}.cpyjit_vs_cinderx.txt").write_text(
            exc.stdout or "",
            encoding="utf-8",
        )

    (ARTIFACTS / f"{tag}.cpyjit.meta.json").write_text(
        json.dumps(
            metadata(
                str(CPY_JIT),
                {
                    "benchmarks": benches,
                    "mode": mode,
                    "PYTHON_JIT": 1,
                    "inherit_environ": ["PYTHON_JIT"],
                },
            ),
            indent=2,
        ),
        encoding="utf-8",
    )
    (ARTIFACTS / f"{tag}.cinderx.meta.json").write_text(
        json.dumps(
            metadata(
                str(VENV / "bin/python3.14"),
                {
                    "benchmarks": benches,
                    "mode": mode,
                    "CINDERX_BOOTSTRAP": str(BOOTSTRAP),
                    "CINDERX_WHEEL": str(wheel),
                    "inherit_environ": ["PYTHONPATH"],
                },
            ),
            indent=2,
        ),
        encoding="utf-8",
    )

    if suite == "target":
        perf_stat(f"{tag}.cpyjit", str(BIN / "cpython-jit.sh"), "richards")
        perf_stat(f"{tag}.cpyjit", str(BIN / "cpython-jit.sh"), "deltablue")
        perf_stat(f"{tag}.cinderx", str(BIN / "cinderx-focused.sh"), "richards")
        perf_stat(f"{tag}.cinderx", str(BIN / "cinderx-focused.sh"), "deltablue")


def profile() -> None:
    ensure_bootstrap()
    env = {**os.environ, "PYTHONPATH": str(BOOTSTRAP)}
    for wrapper_name, wrapper in (
        ("cpyjit", BIN / "cpython-jit.sh"),
        ("cinderx", BIN / "cinderx-focused.sh"),
    ):
        for bench in ("richards", "deltablue"):
            out = ARTIFACTS / f"profile.{wrapper_name}.{bench}.txt"
            cp = subprocess.run(
                [
                    str(wrapper),
                    str(TOOLS / "focused_bench.py"),
                    bench,
                    "--warmups",
                    str(WARMUPS),
                    "--loops",
                    "50",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
            )
            out.write_text(cp.stdout, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    sub.add_parser("preflight")
    bench_p = sub.add_parser("bench")
    bench_p.add_argument("--suite", choices=["target", "guardrail"], default="target")
    bench_p.add_argument("--mode", choices=["fast", "rigorous"], default="fast")
    bench_p.add_argument("--tag", default="adhoc")
    sub.add_parser("profile")
    args = parser.parse_args()
    if args.cmd == "build":
        build()
    elif args.cmd == "preflight":
        preflight()
    elif args.cmd == "bench":
        bench(args.suite, args.mode, args.tag)
    elif args.cmd == "profile":
        profile()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
