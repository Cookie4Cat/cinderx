# CinderX Local Test Gate

Local merge gate for ARM64 CPython 3.14 CinderX JIT work on top of
`meta/main`.

```bash
python cinderx/TestGate/run_gate.py pr
```

On the ARM64 server, run the same command inside the checkout, using the desired
CPython 3.14 interpreter. Logs and `summary.json` are written under
`build/testgate/`.

The `pr` suite builds a release wheel, installs it into an isolated venv, then
runs:

- `lib_test_release_frame_eval_nojit`: CPython `Lib/test` with CinderX
  initialized, the frame evaluator installed, and JIT disabled.
- `test_cinderx_release`: CinderX Python tests from the fresh wheel.

Known exclusions:

- `test_jit_support_instrumentation.py` is filtered to ARM64-supported cases.
- `lib_test_release_frame_eval_nojit` uses official CinderX skip metadata plus
  `cinderx/TestGate/skiplists/` for frame-eval-only incompatibilities.
- `test.test_code` runs outside the parallel batch with only incompatible
  code-object internal cases filtered.

Future work: add compiler side-by-side coverage for
`test_compiler_sbs_stdlib_0.py` through `test_compiler_sbs_stdlib_9.py`.
