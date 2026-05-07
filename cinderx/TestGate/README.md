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

The `pr` suite is the small local merge gate. It builds a release wheel,
installs it into an isolated venv, then runs:

- `lib_test_release_frame_eval_nojit`: CPython `Lib/test` with CinderX
  initialized, the frame evaluator installed, and JIT disabled.
- `test_cinderx_release`: CinderX Python tests from the fresh wheel.

Broader suites are split by gate class:

| Suite | Class | Purpose |
| --- | --- | --- |
| `lib_test_jit_all` | hard | Full `Lib/test` with frame evaluator and `-X jit-all`. |
| `lib_test_jit_all_probe` | baseline/probe | Per-module jit-all run with JIT compilation stats. |
| `lib_test_adaptive_aware_50` | hard | Full `Lib/test` with frame evaluator and `compile_after_n_calls(50)`. |
| `lib_test_adaptive_aware_50_module_probe` | baseline/probe | Per-module AUTOJIT=50 run with correctness classification and JIT stats. |
| `lib_test_adaptive_aware_8_pressure_sample` | pressure probe | Full per-module `Lib/test` probe at a smaller legal AutoJIT threshold. |
| `lib_test_adaptive_aware_1_pressure_sample` | pressure probe | Full per-module `Lib/test` probe at the earliest AutoJIT threshold. |
| `lib_test_adaptive_aware_1000000_control_sample` | control probe | Full per-module JIT-enabled, almost-no-compilation control probe used to separate JIT-enabled side effects from compiled-code failures. |

Compatibility aliases are kept for older notes:

- `lib_test_adaptive_aware` is the same threshold-50 full suite shape.
- `lib_test_adaptive_aware_probe` is the same threshold-50 module probe shape.

Run a suite with:

```bash
python cinderx/TestGate/run_gate.py lib_test_adaptive_aware_50
```

The module probes run each selected `Lib/test` module in its own runner
invocation and write per-module logs plus JIT compilation stats. These stats are
collected by the same startup hook used by the real runner, so they describe
functions compiled during each module's regrtest process, not a separate
synthetic probe.

Pressure and control probes pass `--no-fail-on-test-failure` to keep artifact
collection ergonomic. Their JSON summaries still contain the actual per-module
failures and must be compared against the frozen baseline files before judging a
change. The three suite names still contain `sample` for compatibility with
earlier notes, but they now discover and run the full `Lib/test` module list.
The default module-probe summary is compact; detailed per-process JIT stats stay
under each module's artifact directory. Pass `--include-jit-details` only for
small targeted probes.

Frozen baseline metadata lives under `cinderx/TestGate/baselines/`. Start with
`baselines/index.json`; it maps each frozen result to the suite that produced
it. Current policy:

- Hard gates should not introduce failures beyond the frozen `meta/main`
  baseline.
- Pressure probes should not introduce new crashes, hangs, or materially worse
  failures.
- Control probes are for classification: `nojit pass + control fail` means the
  JIT-enabled machinery changed interpreter behavior even without meaningful
  compilation.

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
- `lib_test_adaptive_aware` uses its own gate skiplist so adaptive-aware debts
  do not get conflated with jit-all debts.
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

Known `lib_test_adaptive_aware_probe` debts:

- Full `compile_after_n_calls(50)` probe baseline on 2026-04-29:
  469 modules attempted; 433 passed, 20 have confirmed failures, 1 reported
  `ENV CHANGED`, 1 timed out, 10 were `resource_denied`, 3 had no runnable tests
  after filtering, and `test.test_regrtest` was a probe anomaly that did not
  reproduce on isolated rerun. 189 modules had `module_new_count > 0`.
- `cinderx.jit.compile_after_n_calls(50)` can crash recursive keyword-call
  paths before they raise `RecursionError`. A minimal shape is
  `def recurse_kw(a=0): recurse_kw(a=0)`. `cinderx.init()` alone and
  `cinderx.init()` plus the frame evaluator both pass `test.test_call`; the
  crash appears when AutoJIT delayed-threshold scheduling is enabled. The
  failure is likely in the mixed state where a function's vectorcall has been
  replaced by CinderX's AutoJIT entrypoint, early recursive calls still dispatch
  to the interpreted entrypoint, and a later recursive keyword call crosses the
  threshold and enters `JITRT_CallWithKeywordArgs`.
- The 2026-04-29 adaptive-aware probe failures cluster around a few risk areas:
  recursion protection (`test_call`, `test_exceptions`, `test_isinstance`,
  `test_json`, `test_opcache`, `test_pickle`, `test_support`, `test_sys`,
  `test_traceback`), monitoring/tracing/debugger/profiler behavior
  (`test_cprofile`, `test_external_inspection`, `test_monitoring`, `test_pdb`,
  `test_profile`, `test_sys_settrace`), generator/frame-local semantics
  (`test_generators`), and signal/threading behavior (`test_signal`,
  `test_threading`).
- Separate triage found:
  `test_capi` passes under frame-eval-nojit, but fails with CinderX JIT enabled
  even at `compile_after_n_calls(1000000)`. The stable failures are
  `Test_Pep523API.test_inlined_binary_subscr`, where CPython's PEP 523 test
  eval-frame recorder observes 0 calls instead of 200, and
  `CAPITest.test_is_unique_temporary`, where the CPython 3.14
  `LOAD_FAST_BORROW` temporary-refcount expectation sees refcount 2 instead of
  1. No functions were recorded as JIT compiled in the high-threshold rerun, so
  this is a JIT-enabled/interpreter-contract incompatibility, not a compiled-code
  failure.
- `test_dis` passes under frame-eval-nojit, but fails with CinderX JIT enabled
  even at `compile_after_n_calls(1000000)`. `test_loop_quicken` expects
  CPython's adaptive disassembly to show `CALL_PY_GENERAL`, but observes plain
  `CALL`. No functions were recorded as JIT compiled in the high-threshold
  rerun, so this is a specialization/disassembly expectation mismatch in
  JIT-enabled mode.
- `test_compileall` passes at `compile_after_n_calls(1000000)` but fails
  consistently at `compile_after_n_calls(50)`. The failures are in
  `HardlinkDedupTests*`, where `.pyc` files expected to be hardlinked are not.
  Treat this as an AutoJIT threshold interaction with compileall/pyc generation
  or its subprocess environment.
- `test_regrtest` passed on isolated adaptive-aware AUTOJIT=50 rerun. The
  original full probe had return code 2 while being classified as `no_tests`;
  this is tracked as a probe anomaly rather than a confirmed baseline failure.
- The frozen baseline classification is also stored in
  `cinderx/TestGate/baselines/meta_main_arm64_314_adaptive_aware_50_module_probe.json`.

Known `lib_test_adaptive_aware_8_pressure_sample` debts:

- Full `compile_after_n_calls(8)` probe baseline on 2026-05-07:
  469 modules attempted with `--num-workers auto` resolving to 8; 428 passed,
  29 failed, 1 reported `ENV CHANGED`, 1 timed out, and 10 were
  `resource_denied`. 467 modules recorded `compiled_delta > 0`, and 285 had
  `module_new_count > 0`.
- Frozen classification is stored in
  `cinderx/TestGate/baselines/meta_main_arm64_314_adaptive_aware_8_full_probe.json`.

Known `lib_test_adaptive_aware_1_pressure_sample` debts:

- Full `compile_after_n_calls(1)` probe baseline on 2026-05-07:
  469 modules attempted with `--num-workers auto` resolving to 8; 425 passed,
  32 failed, 1 reported `ENV CHANGED`, 1 timed out, and 10 were
  `resource_denied`. 467 modules recorded `compiled_delta > 0`, and 334 had
  `module_new_count > 0`.
- Frozen classification is stored in
  `cinderx/TestGate/baselines/meta_main_arm64_314_adaptive_aware_1_full_probe.json`.

Known `lib_test_adaptive_aware_1000000_control_sample` debts:

- Full `compile_after_n_calls(1000000)` control baseline on 2026-05-07:
  469 modules attempted with `--num-workers auto` resolving to 8; 451 passed,
  8 failed, and 10 were `resource_denied`. 38 modules recorded
  `compiled_delta > 0`, while only 1 had `module_new_count > 0`.
- This is a high-threshold JIT-enabled control, not a no-JIT run. Its failures
  separate JIT-enabled interpreter-contract side effects from compiled-code
  failures.
- Frozen classification is stored in
  `cinderx/TestGate/baselines/meta_main_arm64_314_adaptive_aware_1000000_full_control_probe.json`.

Future work: add compiler side-by-side coverage for
`test_compiler_sbs_stdlib_0.py` through `test_compiler_sbs_stdlib_9.py`.
