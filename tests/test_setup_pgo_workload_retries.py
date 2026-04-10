import subprocess
import unittest
from unittest.mock import patch

import setup


class PgoWorkloadRetryTests(unittest.TestCase):
    def test_retries_once_then_succeeds(self) -> None:
        with patch.object(
            setup.subprocess,
            "run",
            side_effect=[
                subprocess.CalledProcessError(2, ["python", "-c", "pass"]),
                None,
            ],
        ) as run_mock:
            setup.run_pgo_workload(["python", "-c", "pass"], {"check": True})

        self.assertEqual(run_mock.call_count, 2)

    def test_raises_after_retry_budget_exhausted(self) -> None:
        with patch.object(
            setup.subprocess,
            "run",
            side_effect=[
                subprocess.CalledProcessError(2, ["python", "-c", "pass"]),
                subprocess.CalledProcessError(2, ["python", "-c", "pass"]),
            ],
        ) as run_mock:
            with self.assertRaises(subprocess.CalledProcessError):
                setup.run_pgo_workload(["python", "-c", "pass"], {"check": True})

        self.assertEqual(run_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
