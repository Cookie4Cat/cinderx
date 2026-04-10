import unittest

from scripts.bench import richards_metrics as metrics


class RichardsMetricsTests(unittest.TestCase):
    def test_bootstrap_ci_bounds_are_ordered(self) -> None:
        lo, hi = metrics.bootstrap_mean_ci(
            [-5.0, -1.0, 0.0, 2.0, 4.0], iterations=500, seed=7
        )
        self.assertLessEqual(lo, hi)

    def test_arm_speedup_positive_when_arm_is_faster(self) -> None:
        arm = [0.090, 0.095, 0.092]
        x86 = [0.100, 0.104, 0.101]
        result = metrics.compare_arm_vs_x86(arm, x86)
        self.assertGreater(result["speedup_pct"], 0.0)

    def test_sample_summary_has_required_fields(self) -> None:
        summary = metrics.summarize_samples([1.0, 2.0, 3.0, 4.0])
        for key in ("count", "mean", "median", "min", "max"):
            self.assertIn(key, summary)

    def test_validate_runner_payload_contract(self) -> None:
        payload = {
            "host": "example-host",
            "benchmark": "richards",
            "mode_samples": {
                "nojit": [0.1, 0.11],
                "jitlist": [0.09, 0.095],
                "autojit50": [0.085, 0.083],
            },
        }
        self.assertTrue(metrics.validate_runner_payload(payload))


if __name__ == "__main__":
    unittest.main()
