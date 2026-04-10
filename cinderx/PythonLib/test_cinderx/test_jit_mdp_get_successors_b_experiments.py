import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

import cinderx.jit

from ._pyperformance_helper import find_pyperformance_benchmark


@unittest.skipUnless(cinderx.jit.is_enabled(), "Tests functionality on cinderjit")
class MdpGetSuccessorsBExperimentTests(unittest.TestCase):
    def test_priority_compare_add_reduces_generic_binary_ops(self) -> None:
        module_path = find_pyperformance_benchmark("bm_mdp")
        if module_path is None:
            self.skipTest("bm_mdp benchmark source unavailable")

        code = textwrap.dedent(
            f"""
            import importlib.util
            import json

            import cinderx.jit as jit
            import cinderjit

            spec = importlib.util.spec_from_file_location(
                "bm_mdp",
                {str(module_path)!r},
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            badges = (1, 0, 0, 0)
            starfixed = mod.fixeddata_t(
                59, mod.stats_t(40, 44, 56, 50), 11, mod.NOMODS, 115
            )
            starhalf = mod.halfstate_t(
                starfixed, 59, 0, mod.NOMODS, mod.stats_t(40, 44, 56, 50)
            )
            charfixed = mod.fixeddata_t(
                63, mod.stats_t(39, 34, 46, 38), 26, badges, 65
            )
            charhalf = mod.halfstate_t(
                charfixed,
                63,
                0,
                mod.NOMODS,
                mod.applyBadgeBoosts(badges, mod.stats_t(39, 34, 46, 38)),
            )
            jit.enable()
            jit.enable_specialized_opcodes()
            jit.compile_after_n_calls(1000000)

            summaries = {{}}
            for action in ("Dig", "Super Potion"):
                statep = (1, (charhalf, starhalf, 0), action)
                battle = mod.Battle()
                for _ in range(10000):
                    battle._getSuccessorsB(statep)
                summaries[action] = sorted(
                    (repr(key), value)
                    for key, value in battle._getSuccessorsB(statep).items()
                )

            assert jit.force_compile(mod.Battle._getSuccessorsB)
            counts = cinderjit.get_function_hir_opcode_counts(mod.Battle._getSuccessorsB)
            print(counts.get("BinaryOp", 0))
            print(counts.get("LongBinaryOp", 0))
            print(json.dumps(summaries, sort_keys=True))
            """
        )

        with tempfile.TemporaryDirectory() as tmp:
            script = f"{tmp}/mdp_get_successors_b.py"
            with open(script, "w", encoding="utf-8") as fp:
                fp.write(code)

            env_baseline = dict(os.environ)
            env_baseline["PYTHONJIT_ARM_MDP_PRIORITY_COMPARE_ADD"] = "0"
            proc_baseline = subprocess.run(
                [sys.executable, script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env_baseline,
            )
            self.assertEqual(
                proc_baseline.returncode,
                0,
                f"stdout:\n{proc_baseline.stdout}\nstderr:\n{proc_baseline.stderr}",
            )

            proc_default = subprocess.run(
                [sys.executable, script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=dict(os.environ),
            )
            self.assertEqual(
                proc_default.returncode,
                0,
                f"stdout:\n{proc_default.stdout}\nstderr:\n{proc_default.stderr}",
            )

            baseline = [
                line.strip() for line in proc_baseline.stdout.splitlines() if line.strip()
            ]
            optimized = [
                line.strip() for line in proc_default.stdout.splitlines() if line.strip()
            ]
            self.assertEqual(len(baseline), 3, proc_baseline.stdout)
            self.assertEqual(len(optimized), 3, proc_default.stdout)

            b_binary_op = int(baseline[0])
            b_long_binary_op = int(baseline[1])
            b_summary = baseline[2]

            o_binary_op = int(optimized[0])
            o_long_binary_op = int(optimized[1])
            o_summary = optimized[2]

            self.assertEqual(b_summary, o_summary, (proc_baseline.stdout, proc_default.stdout))
            self.assertLess(o_binary_op, b_binary_op, (proc_baseline.stdout, proc_default.stdout))
            self.assertGreaterEqual(
                o_long_binary_op,
                b_long_binary_op,
                (proc_baseline.stdout, proc_default.stdout),
            )
