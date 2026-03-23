import importlib.util
import pathlib
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
    def test_builtin_benchmarks_have_benchmark_toml(self) -> None:
        harness = _load_harness()
        config_root = pathlib.Path(__file__).resolve().parent.parent / "configs"

        generators = harness.load_benchmark_config(config_root, "generators")
        self.assertEqual(generators["bench_func"], "bench_generators")
        self.assertEqual(generators["args"]["mode"], "fixed_tuple")

        mdp = harness.load_benchmark_config(config_root, "mdp")
        self.assertEqual(mdp["bench_func"], "bench_mdp")
        self.assertEqual(mdp["args"]["mode"], "fixed_tuple")

        regex_compile = harness.load_benchmark_config(config_root, "regex_compile")
        self.assertEqual(regex_compile["bench_func"], "bench_regex_compile")
        self.assertEqual(regex_compile["args"]["mode"], "regex_compile_capture")
        self.assertEqual(
            regex_compile["support_files"],
            ["bm_regex_effbot.py", "bm_regex_v8.py"],
        )

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
            self.assertEqual(
                harness.benchmark_module_path(bench_root, "custom", config_root=config_root),
                bench_root / "bm_custom" / "entry.py",
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

    def test_resolve_generators_benchmark_metadata(self) -> None:
        harness = _load_harness()
        config_root = pathlib.Path(__file__).resolve().parent.parent / "configs"
        config = harness.resolve_benchmark_metadata("generators", config_root)
        self.assertEqual(config["module_dir"], "bm_generators")
        self.assertEqual(config["bench_func"], "bench_generators")

    def test_resolve_mdp_benchmark_metadata(self) -> None:
        harness = _load_harness()
        config_root = pathlib.Path(__file__).resolve().parent.parent / "configs"
        config = harness.resolve_benchmark_metadata("mdp", config_root)
        self.assertEqual(config["module_dir"], "bm_mdp")
        self.assertEqual(config["bench_func"], "bench_mdp")

    def test_load_benchmark_accepts_string_root(self) -> None:
        harness = _load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bench_dir = root / "bm_mdp"
            bench_dir.mkdir()
            (bench_dir / "run_benchmark.py").write_text(
                "def bench_mdp(loops):\n    return loops + 1\n",
                encoding="utf-8",
            )
            module, bench = harness.load_benchmark(str(root), "mdp")
            self.assertEqual(module.__name__, "bm_mdp")
            self.assertEqual(bench(2), 3)

    def test_pyperf_shim_code_contains_runner(self) -> None:
        harness = _load_harness()
        code = harness.pyperf_shim_code()
        self.assertIn("perf_counter", code)
        self.assertIn("class Runner", code)

    def test_load_opt_env_file_reads_key_value_pairs(self) -> None:
        harness = _load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            env_file = pathlib.Path(tmp) / "stable.env"
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

    def test_default_opt_env_file_uses_configs_directory(self) -> None:
        harness = _load_harness()
        self.assertEqual(
            harness.default_opt_env_file("mdp"),
            pathlib.Path("/scripts/configs/mdp/stable.env"),
        )

    def test_comparison_results_path_nests_by_benchmark_and_config(self) -> None:
        harness = _load_harness()
        self.assertEqual(
            harness.comparison_results_path("/results", "mdp", "stable"),
            pathlib.Path("/results/mdp/stable/comparison.json"),
        )


if __name__ == "__main__":
    unittest.main()
