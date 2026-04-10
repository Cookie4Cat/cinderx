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
    def test_resolve_generators_benchmark(self) -> None:
        harness = _load_harness()
        spec = harness.resolve_benchmark("generators")
        self.assertEqual(spec.module_dir, "bm_generators")
        self.assertEqual(spec.bench_func, "bench_generators")

    def test_resolve_mdp_benchmark(self) -> None:
        harness = _load_harness()
        spec = harness.resolve_benchmark("mdp")
        self.assertEqual(spec.module_dir, "bm_mdp")
        self.assertEqual(spec.bench_func, "bench_mdp")

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
