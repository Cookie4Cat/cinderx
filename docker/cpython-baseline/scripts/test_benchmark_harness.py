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
    def test_resolve_mdp_benchmark(self) -> None:
        harness = _load_harness()
        spec = harness.resolve_benchmark("mdp")
        self.assertEqual(spec.module_dir, "bm_mdp")
        self.assertEqual(spec.bench_func, "bench_mdp")
        self.assertEqual(spec.bench_args, (1,))

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
            pathlib.Path("/scripts/configs/mdp/stable.env"),
        )

    def test_results_root_defaults_to_results_directory(self) -> None:
        harness = _load_harness()
        self.assertEqual(harness.results_root(), pathlib.Path("/results"))

    def test_base_image_name_defaults_to_shared_arm64_image(self) -> None:
        compose_text = pathlib.Path("docker/cpython-baseline/docker-compose.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'image: ${BASE_IMAGE:-cinderx-cpython-baseline:arm64}',
            compose_text,
        )


if __name__ == "__main__":
    unittest.main()
