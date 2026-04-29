# CinderX Local Test Gate

Local merge gate for ARM64 CPython 3.14 CinderX JIT work on top of
`meta/main`.

```bash
python cinderx/TestGate/run_gate.py pr
```

On the ARM64 server, run the same command inside the checkout, using the desired
CPython 3.14 interpreter. Logs and `summary.json` are written under
`build/testgate/`.

Lib/test jobs default to `min(os.cpu_count(), 64)` workers. Set
`CINDERX_TESTGATE_WORKERS` or pass `--num-workers` to the lib-test runner to
override it.
The lib-test runner also accepts `--test-from-file` for an explicit module list
and `--defer-pattern` to move slow groups, such as `test.test_asyncio`, to the
end of the run.

The `pr` suite builds a release wheel, installs it into an isolated venv, then
runs:

- `lib_test_release_frame_eval_nojit`: CPython `Lib/test` with CinderX
  initialized, the frame evaluator installed, and JIT disabled.
- `test_cinderx_release`: CinderX Python tests from the fresh wheel.

`lib_test_jit_all` is an optional full CPython `Lib/test` suite with CinderX
initialized, the frame evaluator installed, and `-X jit-all`. It is intentionally
separate from `pr` because it is much slower and should be invoked only when a
change needs broad JIT coverage. Before running regrtest, it executes a small
JIT probe and records the result in the suite summary.

`lib_test_jit_all_probe` is a diagnostic version of the same coverage:

```bash
python cinderx/TestGate/run_gate.py lib_test_jit_all_probe
```

It runs every discovered `Lib/test` module in its own `frame-eval-jit-all`
runner invocation, defers `test.test_asyncio.*` to the end, and writes per-module
logs plus JIT compilation stats. The JIT stats are collected by the same startup
hook used by the real runner, so they describe functions compiled during each
module's regrtest process, not a separate synthetic probe. The diagnostic returns
non-zero after finishing the full list if any module fails, times out, or reports
`ENV CHANGED`. Modules with no newly compiled functions are listed in the JSON
summary, but do not fail the diagnostic yet.

The gate startup hook patches selected `_testcapi` helpers for CinderX JIT
generators. These helpers are CPython internal test APIs and assume exact
`PyGen_Type` objects. The patches keep regular CPython generators on the
original paths, and adapt CinderX JIT generators only so the tests continue to
exercise Python-visible generator semantics instead of failing on exact-type
assumptions. This is gate compatibility only, not a runtime compatibility fix
for arbitrary C extensions.

Known exclusions:

- `test_jit_support_instrumentation.py` is filtered to ARM64-supported cases.
- `lib_test_release_frame_eval_nojit` uses official CinderX skip metadata plus
  `cinderx/TestGate/skiplists/` for frame-eval-only incompatibilities.
- `lib_test_jit_all` also uses official CinderX JIT skip metadata.
- `test.test_code` runs outside the parallel batch with only incompatible
  code-object internal cases filtered.

Known `lib_test_jit_all` debts:

- `test.test_ordered_dict.*test_free_after_iterating*` reports
  `ENV CHANGED` from unraisable `ValueError: generator already executing`
  under frame-eval jit-all. This appears to be JIT generator finalization
  clearing locals while the generator is still observable as executing.
- `test.test_userlist.UserListTest.test_free_after_iterating` reports
  `ENV CHANGED` from unraisable `ValueError: generator already executing`
  under frame-eval jit-all. This is the same finalization/frame-state ordering
  class as the ordered-dict failure.
- `test.test_xml_etree.BadElementTest.test_element_get_tail` and
  `test.test_xml_etree.BadElementTest.test_element_get_text` report
  `ENV CHANGED` from unraisable free-variable `NameError` under frame-eval
  jit-all. This also involves object finalizers observing locals during frame
  cleanup.

Future work: add compiler side-by-side coverage for
`test_compiler_sbs_stdlib_0.py` through `test_compiler_sbs_stdlib_9.py`.
