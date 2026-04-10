import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import _pyperformance_helper
from ._pyperformance_helper import find_pyperformance_benchmark


class PyperformanceHelperTests(unittest.TestCase):
    def test_find_pyperformance_benchmark_uses_env_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmark = (
                root
                / "pyperformance"
                / "data-files"
                / "benchmarks"
                / "bm_mdp"
                / "run_benchmark.py"
            )
            benchmark.parent.mkdir(parents=True)
            benchmark.write_text("print('ok')\n", encoding="utf-8")

            with mock.patch.dict(os.environ, {"PYPERFORMANCE_ROOT": str(root)}, clear=False):
                self.assertEqual(find_pyperformance_benchmark("bm_mdp"), benchmark)

    def test_find_pyperformance_benchmark_returns_none_when_missing(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(_pyperformance_helper.Path, "home", return_value=Path("/nonexistent-home")):
                with mock.patch.object(_pyperformance_helper.Path, "exists", return_value=False):
                    with mock.patch.dict("sys.modules", {"pyperformance": None}):
                        self.assertIsNone(find_pyperformance_benchmark("bm_mdp"))
