import importlib.util
import pathlib
import sys
import tempfile
import textwrap
import unittest

def _load_harness():
    root = pathlib.Path(__file__).resolve().parent
    path = root / "benchmark_harness.py"
    spec = importlib.util.spec_from_file_location("benchmark_harness", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BenchmarkHarnessTests(unittest.TestCase):
    def test_baseline_script_uses_pyperformance_and_json_output(self) -> None:
        script_text = (
            pathlib.Path(__file__).resolve().parent / "test-baseline.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("-m pyperformance run", script_text)
        self.assertIn('-o "$OUTPUT_FILE"', script_text)
        self.assertIn('PYTHON_JIT="$PYTHON_JIT"', script_text)

    def test_cinderx_script_uses_pyperformance_worker_hook_and_json_output(self) -> None:
        script_text = (
            pathlib.Path(__file__).resolve().parent / "test-cinderx.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("python3 -m pyperformance run", script_text)
        self.assertIn('-o "$OUTPUT_FILE"', script_text)
        self.assertIn('PYTHONJIT="${PYTHONJIT:-1}"', script_text)
        self.assertIn('PYTHONJITAUTO="$AUTOJIT"', script_text)
        self.assertIn('DIAG=${DIAG:-0}', script_text)
        self.assertIn('JIT_LOG_FILE=${JIT_LOG_FILE:-/tmp/cinderx-jit.log}', script_text)
        self.assertIn('LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}"', script_text)
        self.assertIn(
            'base = ["LD_LIBRARY_PATH", "PYTHONJIT", "PYTHONJITAUTO", "PYTHONJITHUGEPAGES"]',
            script_text,
        )
        self.assertIn('diag = ["PYTHONJITLOGFILE", "PYTHONJITDUMPFINALHIR", "PYTHONJITDUMPSTATS"]', script_text)
        self.assertNotIn("CINDERX_WORKER_PYTHONJITAUTO", script_text)
        self.assertNotIn("PYPERF_HOOK_ROOT_RESOLVED", script_text)

    def test_cinderx_script_disables_jit_during_install(self) -> None:
        script_text = (
            pathlib.Path(__file__).resolve().parent / "test-cinderx.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'PYTHONJITDISABLE=1 python3 -m pip install --quiet --no-deps "$CINDERX_WHEEL_PATH"',
            script_text,
        )
        self.assertIn(
            'PYTHONJITDISABLE=1 python3 -m pip install --quiet "$PYPERFORMANCE_TMP"',
            script_text,
        )

    def test_cinderx_script_reuses_cached_wheel(self) -> None:
        script_text = (
            pathlib.Path(__file__).resolve().parent / "test-cinderx.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('CINDERX_WHEEL_CACHE_DIR=${CINDERX_WHEEL_CACHE_DIR:-/opt/cinderx-wheel-cache}', script_text)
        self.assertIn('CINDERX_WHEEL_PATH=$(ls -t "$CINDERX_WHEEL_CACHE_DIR"/cinderx-*-linux_aarch64.whl', script_text)
        self.assertIn('PYTHONJITDISABLE=1 python3 -m pip install --quiet --no-deps "$CINDERX_WHEEL_PATH"', script_text)
        self.assertNotIn("python3 -m build --wheel", script_text)

    def test_comparison_script_consumes_json_outputs(self) -> None:
        script_text = (
            pathlib.Path(__file__).resolve().parent / "test-comparison.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('BASELINE_OUTPUT=${BASELINE_OUTPUT:-/tmp/pyperformance-baseline.json}', script_text)
        self.assertIn('CINDERX_BASELINE_OUTPUT=${CINDERX_BASELINE_OUTPUT:-/tmp/pyperformance-cinderx-baseline.json}', script_text)
        self.assertIn('CINDERX_OPT_OUTPUT=${CINDERX_OPT_OUTPUT:-/tmp/pyperformance-cinderx-optimized.json}', script_text)
        self.assertIn("pyperf.BenchmarkSuite.load", script_text)
        self.assertIn("python3 -m pyperformance compare", script_text)

    def test_builtin_benchmarks_have_benchmark_toml(self) -> None:
        harness = _load_harness()
        config_root = pathlib.Path(__file__).resolve().parent.parent / "configs"

        generators = harness.load_benchmark_config(config_root, "generators")
        self.assertEqual(generators["bench_func"], "bench_generators")
        self.assertEqual(generators["pyperformance_benchmark"], "generators")
        self.assertEqual(generators["args"]["mode"], "fixed_tuple")
        self.assertEqual(generators["prepare"]["mode"], "pyperformance_files")
        self.assertEqual(generators["run"]["default_excludes"], [])
        self.assertEqual(generators["run"]["extra_env"], {})

        mdp = harness.load_benchmark_config(config_root, "mdp")
        self.assertEqual(mdp["bench_func"], "bench_mdp")
        self.assertEqual(mdp["pyperformance_benchmark"], "mdp")
        self.assertEqual(mdp["args"]["mode"], "fixed_tuple")
        self.assertEqual(mdp["prepare"]["mode"], "pyperformance_files")

        regex_compile = harness.load_benchmark_config(config_root, "regex_compile")
        self.assertEqual(regex_compile["bench_func"], "bench_regex_compile")
        self.assertEqual(regex_compile["pyperformance_benchmark"], "regex_compile")
        self.assertEqual(regex_compile["args"]["mode"], "regex_compile_capture")
        self.assertEqual(regex_compile["prepare"]["mode"], "pyperformance_files")
        self.assertEqual(
            regex_compile["support_files"],
            ["bm_regex_effbot.py", "bm_regex_v8.py"],
        )

    def test_pyperformance_metadata_comes_from_config(self) -> None:
        harness = _load_harness()
        config_root = pathlib.Path(__file__).resolve().parent.parent / "configs"
        self.assertEqual(
            harness.pyperformance_benchmark_name("mdp", config_root=config_root),
            "mdp",
        )
        self.assertEqual(
            harness.benchmark_prepare_mode("regex_compile", config_root=config_root),
            "pyperformance_files",
        )
        self.assertEqual(
            harness.default_run_excludes("generators", config_root=config_root),
            (),
        )
        self.assertEqual(
            harness.benchmark_extra_env("mdp", config_root=config_root),
            {},
        )
        self.assertEqual(
            harness.pyperformance_benchmark_filter("mdp,-regex_compile", config_root=config_root),
            "mdp,-regex_compile",
        )
        self.assertEqual(harness.pyperformance_source_root(), pathlib.Path("/pyperformance"))
        self.assertEqual(harness.pyperformance_hook_root(), pathlib.Path("/pyperf_env_hook"))

    def test_benchmark_downloads_come_from_config(self) -> None:
        harness = _load_harness()
        config_root = pathlib.Path(__file__).resolve().parent.parent / "configs"
        downloads = harness.benchmark_downloads("regex_compile", config_root=config_root)
        self.assertEqual(
            downloads,
            (
                (
                    "run_benchmark.py",
                    "https://raw.githubusercontent.com/python/pyperformance/main/pyperformance/data-files/benchmarks/bm_regex_compile/run_benchmark.py",
                ),
                (
                    "bm_regex_effbot.py",
                    "https://raw.githubusercontent.com/python/pyperformance/main/pyperformance/data-files/benchmarks/bm_regex_compile/bm_regex_effbot.py",
                ),
                (
                    "bm_regex_v8.py",
                    "https://raw.githubusercontent.com/python/pyperformance/main/pyperformance/data-files/benchmarks/bm_regex_compile/bm_regex_v8.py",
                ),
            ),
        )

    def test_resolve_bench_args_fixed_tuple_mode(self) -> None:
        harness = _load_harness()
        config = {
            "args": {
                "mode": "fixed_tuple",
                "values": [1],
            }
        }
        self.assertEqual(harness.resolve_bench_args(object(), config), (1,))

    def test_resolve_bench_args_regex_compile_capture_mode(self) -> None:
        harness = _load_harness()

        class Module:
            called = False

            @staticmethod
            def capture_regexes():
                Module.called = True
                return ["re1", "re2"]

        config = {
            "args": {
                "mode": "regex_compile_capture",
                "fixed_int": 1,
                "capture_func": "capture_regexes",
            }
        }
        self.assertEqual(
            harness.resolve_bench_args(Module, config),
            (1, ["re1", "re2"]),
        )
        self.assertTrue(Module.called)

    def test_benchmark_module_path_comes_from_config(self) -> None:
        harness = _load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            config_root = pathlib.Path(tmp) / "configs"
            bench_root = pathlib.Path(tmp) / "benchmarks"
            bench_dir = config_root / "custom"
            bench_dir.mkdir(parents=True)
            (bench_dir / "benchmark.toml").write_text(
                textwrap.dedent(
                    """
                    name = "custom"
                    pyperformance_benchmark = "custom"
                    module_dir = "bm_custom"
                    entry_file = "entry.py"
                    bench_func = "bench_custom"

                    support_files = []

                    [[downloads]]
                    target = "entry.py"
                    url = "https://example.invalid/entry.py"

                    [args]
                    mode = "fixed_tuple"
                    values = [1]

                    [prepare]
                    mode = "pyperformance_files"

                    [run]
                    default_excludes = ["dask"]

                    [run.extra_env]
                    FOO = "BAR"
                    """
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                harness.benchmark_module_path(bench_root, "custom", config_root=config_root),
                bench_root / "bm_custom" / "entry.py",
            )
            self.assertEqual(
                harness.pyperformance_benchmark_name("custom", config_root=config_root),
                "custom",
            )
            self.assertEqual(
                harness.benchmark_prepare_mode("custom", config_root=config_root),
                "pyperformance_files",
            )
            self.assertEqual(
                harness.default_run_excludes("custom", config_root=config_root),
                ("dask",),
            )
            self.assertEqual(
                harness.benchmark_extra_env("custom", config_root=config_root),
                {"FOO": "BAR"},
            )

    def test_load_benchmark_uses_configured_entry_file(self) -> None:
        harness = _load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            config_root = pathlib.Path(tmp) / "configs"
            bench_root = pathlib.Path(tmp) / "benchmarks"
            bench_dir = config_root / "custom"
            bench_dir.mkdir(parents=True)
            (bench_dir / "benchmark.toml").write_text(
                textwrap.dedent(
                    """
                    name = "custom"
                    module_dir = "bm_custom"
                    entry_file = "entry.py"
                    bench_func = "bench_custom"

                    support_files = []

                    [[downloads]]
                    target = "entry.py"
                    url = "https://example.invalid/entry.py"

                    [args]
                    mode = "fixed_tuple"
                    values = [1]
                    """
                ),
                encoding="utf-8",
            )

            target_dir = bench_root / "bm_custom"
            target_dir.mkdir(parents=True)
            (target_dir / "entry.py").write_text(
                "def bench_custom(loops):\n    return loops + 41\n",
                encoding="utf-8",
            )

            module, bench = harness.load_benchmark(bench_root, "custom", config_root=config_root)
            self.assertEqual(module.__name__, "bm_custom")
            self.assertEqual(bench(1), 42)

    def test_load_benchmark_config_reads_toml(self) -> None:
        harness = _load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            config_root = pathlib.Path(tmp)
            bench_dir = config_root / "regex_compile"
            bench_dir.mkdir(parents=True)
            (bench_dir / "benchmark.toml").write_text(
                textwrap.dedent(
                    """
                    name = "regex_compile"
                    pyperformance_benchmark = "regex_compile"
                    module_dir = "bm_regex_compile"
                    entry_file = "run_benchmark.py"
                    bench_func = "bench_regex_compile"

                    support_files = ["bm_regex_effbot.py", "bm_regex_v8.py"]

                    [[downloads]]
                    target = "run_benchmark.py"
                    url = "https://example.invalid/run_benchmark.py"

                    [args]
                    mode = "regex_compile_capture"
                    fixed_int = 1
                    capture_func = "capture_regexes"

                    [prepare]
                    mode = "pyperformance_files"

                    [run]
                    default_excludes = []

                    [run.extra_env]
                    """
                ),
                encoding="utf-8",
            )

            config = harness.load_benchmark_config(config_root, "regex_compile")
            self.assertEqual(config["name"], "regex_compile")
            self.assertEqual(config["module_dir"], "bm_regex_compile")
            self.assertEqual(config["entry_file"], "run_benchmark.py")
            self.assertEqual(config["bench_func"], "bench_regex_compile")
            self.assertEqual(config["support_files"], ["bm_regex_effbot.py", "bm_regex_v8.py"])
            self.assertEqual(config["args"]["mode"], "regex_compile_capture")

    def test_resolve_mdp_benchmark_metadata(self) -> None:
        harness = _load_harness()
        config_root = pathlib.Path(__file__).resolve().parent.parent / "configs"
        config = harness.resolve_benchmark_metadata("mdp", config_root)
        self.assertEqual(config["module_dir"], "bm_mdp")
        self.assertEqual(config["bench_func"], "bench_mdp")
        self.assertEqual(config["args"]["mode"], "fixed_tuple")

    def test_load_benchmark_module_and_entrypoint(self) -> None:
        harness = _load_harness()
        code = textwrap.dedent(
            """
            def bench_mdp(loops):
                return loops
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bench_dir = root / "bm_mdp"
            bench_dir.mkdir()
            module_path = bench_dir / "run_benchmark.py"
            module_path.write_text(code, encoding="utf-8")
            module, bench = harness.load_benchmark(root, "mdp")
            self.assertEqual(module.__name__, "bm_mdp")
            self.assertEqual(bench(3), 3)

    def test_load_benchmark_accepts_string_root(self) -> None:
        harness = _load_harness()
        code = textwrap.dedent(
            """
            def bench_mdp(loops):
                return loops + 1
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bench_dir = root / "bm_mdp"
            bench_dir.mkdir()
            module_path = bench_dir / "run_benchmark.py"
            module_path.write_text(code, encoding="utf-8")
            module, bench = harness.load_benchmark(str(root), "mdp")
            self.assertEqual(module.__name__, "bm_mdp")
            self.assertEqual(bench(3), 4)

    def test_load_benchmark_allows_local_pyperf_shim_import(self) -> None:
        harness = _load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bench_dir = root / "bm_mdp"
            bench_dir.mkdir()
            (bench_dir / "pyperf.py").write_text(
                "value = 7\n",
                encoding="utf-8",
            )
            (bench_dir / "run_benchmark.py").write_text(
                textwrap.dedent(
                    """
                    import pyperf

                    def bench_mdp(loops):
                        return loops + pyperf.value
                    """
                ),
                encoding="utf-8",
            )
            sys.modules.pop("pyperf", None)
            module, bench = harness.load_benchmark(root, "mdp")
            self.assertEqual(module.__name__, "bm_mdp")
            self.assertEqual(bench(3), 10)

    def test_stock_cpython_python_defaults_to_jit_prefix(self) -> None:
        harness = _load_harness()
        self.assertEqual(
            harness.stock_cpython_python(),
            pathlib.Path("/opt/cpython-jit/bin/python3"),
        )

    def test_stock_cpython_configure_args_enable_yes_off(self) -> None:
        harness = _load_harness()
        self.assertEqual(
            harness.stock_cpython_configure_args(),
            (
                "./configure",
                "--prefix=/opt/cpython-jit",
                "--enable-experimental-jit=yes-off",
            ),
        )

    def test_stock_cpython_runtime_env_enables_jit(self) -> None:
        harness = _load_harness()
        self.assertEqual(harness.stock_cpython_runtime_env(), {"PYTHON_JIT": "1"})

    def test_cinderx_wheel_glob_defaults_to_dist_directory(self) -> None:
        harness = _load_harness()
        self.assertEqual(
            harness.cinderx_wheel_glob(),
            pathlib.Path("/dist/cinderx-*-linux_aarch64.whl"),
        )

    def test_load_opt_env_file_reads_key_value_pairs(self) -> None:
        harness = _load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            env_file = pathlib.Path(tmp) / "round3.env"
            env_file.write_text(
                textwrap.dedent(
                    """
                    # comment
                    PYTHONJIT_ARM_MDP_INT_CLAMP_MIN_MAX=1
                    PYTHONJIT_ARM_MDP_FRACTION_MIN_COMPARE=1

                    """
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                harness.load_opt_env_file(env_file),
                {
                    "PYTHONJIT_ARM_MDP_INT_CLAMP_MIN_MAX": "1",
                    "PYTHONJIT_ARM_MDP_FRACTION_MIN_COMPARE": "1",
                },
            )

    def test_load_opt_env_file_missing_is_empty(self) -> None:
        harness = _load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            env_file = pathlib.Path(tmp) / "missing.env"
            self.assertEqual(harness.load_opt_env_file(env_file), {})

    def test_load_opt_env_file_rejects_invalid_line(self) -> None:
        harness = _load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            env_file = pathlib.Path(tmp) / "broken.env"
            env_file.write_text("NOT A VALID LINE\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                harness.load_opt_env_file(env_file)

    def test_opt_config_name_defaults_to_stable(self) -> None:
        harness = _load_harness()
        self.assertEqual(harness.opt_config_name(None, enable_optimization=True), "stable")

    def test_opt_config_name_uses_env_file_stem(self) -> None:
        harness = _load_harness()
        self.assertEqual(
            harness.opt_config_name("/tmp/mdp/stable.env", enable_optimization=True),
            "stable",
        )

    def test_opt_config_name_uses_baseline_when_disabled(self) -> None:
        harness = _load_harness()
        self.assertEqual(
            harness.opt_config_name("/tmp/mdp/stable.env", enable_optimization=False),
            "baseline",
        )

    def test_comparison_results_path_nests_by_benchmark_and_config(self) -> None:
        harness = _load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            results_root = pathlib.Path(tmp)
            path = harness.comparison_results_path(results_root, "mdp", "stable")
            self.assertEqual(path, results_root / "mdp" / "stable" / "comparison.json")

    def test_default_opt_env_file_uses_configs_directory(self) -> None:
        harness = _load_harness()
        self.assertEqual(
            harness.default_opt_env_file("mdp"),
            harness.benchmark_config_root() / "mdp" / "stable.env",
        )

    def test_default_opt_env_file_returns_none_for_composite_selection(self) -> None:
        harness = _load_harness()
        self.assertIsNone(harness.default_opt_env_file("all,-dask"))

    def test_results_root_defaults_to_results_directory(self) -> None:
        harness = _load_harness()
        self.assertEqual(harness.results_root(), pathlib.Path("/results"))

    def test_base_image_name_defaults_to_shared_arm64_image(self) -> None:
        compose_text = pathlib.Path("docker/cpython-baseline/docker-compose.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'image: ${BASE_IMAGE:-cinderx-pyperf-realenv:arm64}',
            compose_text,
        )


if __name__ == "__main__":
    unittest.main()
