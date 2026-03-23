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
class RegexCompileExperimentTests(unittest.TestCase):
    def test_explicit_compile_after_n_calls_still_controls_loop_function(self) -> None:
        code = textwrap.dedent(
            """
            import json

            import cinderx.jit as jit

            jit.enable()
            jit.enable_specialized_opcodes()
            jit.compile_after_n_calls(5)

            def f(n):
                s = 0
                for i in range(n):
                    s += i
                return s

            states = []
            for _ in range(6):
                f(10)
                states.append(jit.is_jit_compiled(f))

            print(json.dumps(states))
            """
        )

        with tempfile.TemporaryDirectory() as tmp:
            script = f"{tmp}/compile_after_n_calls_loop.py"
            with open(script, "w", encoding="utf-8") as fp:
                fp.write(code)

            env = dict(os.environ)
            env["PYTHONJITHUGEPAGES"] = "0"
            proc = subprocess.run(
                [sys.executable, script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}",
            )
            self.assertEqual(
                proc.stdout.strip(),
                "[false, false, false, false, false, true]",
                proc.stdout,
            )

    def test_auto_jit_compiles_loop_heavy_regex_compile_benchmark(self) -> None:
        module_path = find_pyperformance_benchmark("bm_regex_compile")
        if module_path is None:
            self.skipTest("bm_regex_compile benchmark source unavailable")

        code = textwrap.dedent(
            f"""
            import importlib.util
            import sys

            import cinderx.jit as jit

            module_path = {str(module_path)!r}
            sys.path.insert(0, str(module_path.rsplit("/", 1)[0]))

            spec = importlib.util.spec_from_file_location(
                "bm_regex_compile",
                module_path,
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            jit.enable()
            jit.enable_specialized_opcodes()
            jit.auto()

            regexes = mod.capture_regexes()
            for _ in range(8):
                mod.bench_regex_compile(1, regexes)

            print(jit.is_jit_compiled(mod.bench_regex_compile))
            """
        )

        with tempfile.TemporaryDirectory() as tmp:
            script = f"{tmp}/regex_compile_autojit.py"
            with open(script, "w", encoding="utf-8") as fp:
                fp.write(code)

            env = dict(os.environ)
            env["PYTHONJITHUGEPAGES"] = "0"
            proc = subprocess.run(
                [sys.executable, script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}",
            )
            lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
            self.assertGreaterEqual(len(lines), 1, proc.stdout)
            self.assertEqual(lines[-1], "True", proc.stdout)

    def test_auto_jit_avoids_stdlib_tuple_genexpr_crash(self) -> None:
        module_path = find_pyperformance_benchmark("bm_regex_compile")
        if module_path is None:
            self.skipTest("bm_regex_compile benchmark source unavailable")

        code = textwrap.dedent(
            f"""
            import importlib.util
            import json
            import statistics
            import sys
            import time

            import cinderx.jit as jit

            module_path = {str(module_path)!r}
            sys.path.insert(0, str(module_path.rsplit("/", 1)[0]))

            spec = importlib.util.spec_from_file_location(
                "bm_regex_compile",
                module_path,
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            jit.enable()
            jit.enable_specialized_opcodes()
            jit.auto()

            times = []
            for _ in range(8):
                regexes = mod.capture_regexes()
                t0 = time.perf_counter()
                mod.bench_regex_compile(1, regexes)
                times.append(time.perf_counter() - t0)

            print(
                json.dumps(
                    {{
                        "compiled": jit.is_jit_compiled(mod.bench_regex_compile),
                        "median_ms": round(statistics.median(times) * 1000, 3),
                    }}
                )
            )
            """
        )

        with tempfile.TemporaryDirectory() as tmp:
            script = f"{tmp}/regex_compile_autojit_stdlib.py"
            with open(script, "w", encoding="utf-8") as fp:
                fp.write(code)

            env = dict(os.environ)
            env["PYTHONJITHUGEPAGES"] = "0"
            proc = subprocess.run(
                [sys.executable, script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}",
            )
            payload = json.loads(proc.stdout.strip())
            self.assertTrue(payload["compiled"], proc.stdout)
