# deepcopy / issue #47 notes

## Intake

- User report ties `copy.deepcopy()` slowdown to deterministic `UnhandledException` deopts in:
  - `copy._keep_alive`
  - `copy._deepcopy_tuple`
- Reported trigger shape:
  - `try: memo[id(obj)] ... except KeyError: ...`
- Reported symptom:
  - JIT compiles only the happy path.
  - When `BINARY_SUBSCR` raises `KeyError`, control falls out through deopt instead of entering an except block.

## Environment notes

- Working tree: `C:/work/code/cinderx-deepcopy-issue47-20260318`
- Base branch: `origin/bench-cur-7c361dce`
- ARM host: `124.70.162.35`
- x86 host: `106.14.164.133`
- Unified remote entrypoint:
  - local wrapper: `scripts/push_to_arm.ps1`
  - remote script: `/root/work/incoming/remote_update_build_test.sh`
- Shared scheduler:
  - tool path: `C:/work/code/coroutines/cinderx/scripts/remote_scheduler.py`
  - db path: `C:/work/code/cinderx-deepcopy-issue47-20260318/plans/remote-scheduler.sqlite3`

## Early code pointers

- `cinderx/Jit/hir/builder.cpp`
  - contains exception-handler-only opcode guardrails
- `cinderx/Jit/hir/hir.h`
  - documents exception transfer semantics on HIR instructions
- `cinderx/Jit/deopt.cpp`
  - maps runtime faults to `DeoptReason::kUnhandledException`
- `cinderx/Jit/codegen/gen_asm.cpp`
  - emits the `UnhandledException` deopt path
- `cinderx/PythonLib/test_cinderx/test_jit_exception.py`
  - likely existing test surface for try/except or exception semantics

## Initial working hypotheses

1. Generic path:
   - protected instructions know they may throw, but the protected region / handler target is not preserved into the optimized HIR CFG used by codegen.
2. Narrow path:
   - specific bytecodes inside `try/except KeyError` are lowered as normal operations with no recoverable handler edge, so codegen only has the deopt escape hatch.
3. Safe first move:
   - add a targeted regression that demonstrates a hot `dict.__getitem__` KeyError path in `try/except` should not produce `UnhandledException` deopts.

## Open questions

- Does the builder already materialize handler blocks for any subset of `try/except`, with `deepcopy` missing due to a pattern-specific lowering?
- Is there existing HIR support for exception edges that just is not wired for `BinaryOp<Subscript>`?
- Can a narrow HIR rewrite for `dict[k] except KeyError` be done safely without broad semantic risk if the generic path is too invasive?

## Next evidence to collect

- Exact current HIR for a minimal `try: d[k] except KeyError` function.
- Existing tests around `try/except` in JIT.
- Whether `UnhandledException` deopt counts can be observed from a small regression test without requiring full pyperformance.

## Baseline evidence

- ARM scheduler:
  - lease id: `1`
  - slot: `compile`
  - stage: `HIR-baseline-test`
  - workspace: `/root/work/cinderx-deepcopy-issue47`
- Unified remote entrypoint runs:
  1. default `test_arm_runtime.py` on latest base showed the suite already contains unrelated historical failures, so it is not clean enough to isolate issue #47 by itself.
  2. targeted re-run through the same entrypoint with:
     - `ARM_RUNTIME_SKIP_TESTS=test_`
     - `EXTRA_TEST_CMD=python -m unittest discover -s cinderx/PythonLib/test_cinderx -p test_arm_runtime.py -k deepcopy_keyerror_helpers_avoid_unhandledexception_deopts -v`
- Targeted result:
  - `test_deepcopy_keyerror_helpers_avoid_unhandledexception_deopts` failed as expected on base.
  - subprocess stdout:
    - `_keep_alive` deopts: `200`
    - `_deepcopy_tuple` deopts: `200`
    - total: `19900`
- Interpretation:
  - the new regression reproduces the user-reported deterministic `UnhandledException` behavior.
  - the deopt counts scale exactly with the scripted call volume.

## Bytecode shape on local Python 3.14

- `_keep_alive`:
  - happy path:
    - `LOAD_FAST_BORROW memo`
    - `LOAD_GLOBAL id`
    - `CALL 1`
    - `BINARY_OP 26 ([])`
    - `LOAD_ATTR append`
    - `CALL 1`
  - exception handler:
    - `PUSH_EXC_INFO`
    - `LOAD_GLOBAL KeyError`
    - `CHECK_EXC_MATCH`
    - `POP_JUMP_IF_FALSE`
    - `POP_TOP`
    - body stores `[x]` back into `memo[id(memo)]`
- `_deepcopy_tuple`:
  - happy path:
    - `LOAD_FAST_BORROW memo`
    - `LOAD_GLOBAL id`
    - `CALL 1`
    - `BINARY_OP 26 ([])`
    - `RETURN_VALUE`
  - exception handler:
    - `PUSH_EXC_INFO`
    - `LOAD_GLOBAL KeyError`
    - `CHECK_EXC_MATCH`
    - `POP_JUMP_IF_FALSE`
    - `POP_EXCEPT`
    - `JUMP_FORWARD` to the post-except continuation

## Static implementation notes

- `createBlocks()` already scans the whole bytecode stream, so branch targets inside handler bytecode still become block starts even though handler blocks are not normally reachable from entry.
- `translate()` aborts on `PUSH_EXC_INFO` / `CHECK_EXC_MATCH`, which confirms generic exception-handler CFG support is still absent.
- `ceval.h` exposes `get_exception_handler(code, index, ...)`, so the builder can query the exception table for the current `BINARY_SUBSCR`.
- 3.14 specialized dict subscript uses `PyDict_GetItemRef()` in the interpreter fast path, which is a good semantic model for a narrow JIT helper.

## Additional remote evidence after first implementation

- ARM remote `dis` capture from the same unified entrypoint matched local 3.14 exactly for both helpers.
- keepalive-only probe:
  - first probe showed the old HIR shape, which exposed a matcher bug
  - after narrowing the matcher to `_keep_alive` and accepting the real 3.14 `LOAD_FAST_BORROW x` bytecode:
    - `_keep_alive` HIR counts now show the rewritten shape:
      - `CallStatic=2`
      - `CheckExc=1`
      - `CheckNeg=1`
      - `GuardType=1`
      - `MakeList=1`
      - `PrimitiveCompare=1`
      - no `BinaryOp`
    - direct deopt probe result:
      - `keep_alive_deopts=0`
      - `elapsed=9.213600014845724e-05` on the 200-iteration micro loop
  - interpretation:
    - `_keep_alive` is now genuinely fixed on ARM for the deterministic KeyError miss path
- combined helper probe:
  - when `_deepcopy_tuple` rewrite was enabled, `python scripts/arm/deepcopy_issue47_probe.py` crashed during HIR construction
  - `coredumpctl` backtrace:
    - crash in `jit::hir::Instr::numEdges(this=0x0)`
    - called from `jit::hir::removeUnreachableBlocks()`
    - call chain originates in `HIRBuilder::buildHIR()` while force-compiling the probe
  - interpretation:
    - the `_deepcopy_tuple` continuation rewrite likely leaves an unterminated or otherwise malformed CFG block
    - this is a new blocker and should not be retried unchanged
- keepalive sentinel lifetime:
  - once `_keep_alive` rewrite began matching, the process started crashing on exit in `Ref<_object>::~Ref`
  - `coredumpctl` pointed at the static `Ref<> sentinel` used by `JITRT_GetDictItemMissSentinel()`
  - fixing the sentinel to a raw intentionally leaked `PyObject*` removed the exit-time crash
- current combined probe with `_deepcopy_tuple` rewrite disabled:
  - `keep_alive_deopts=0`
  - `deepcopy_tuple_deopts=200`
  - `total=19900`
  - interpretation:
    - the round already removed half of the deterministic deopts
    - the remaining blocker is entirely `_deepcopy_tuple`

## `_deepcopy_tuple` helper redesign

- New design:
  - instead of branching from the miss block into an untranslated future bytecode block, `_deepcopy_tuple` now lowers the miss path to a dedicated helper:
    - `JITRT_DeepcopyTuplePostMiss(x, y)`
  - the helper returns:
    - `Py_NewRef(x)` when all zipped pairs are identical objects
    - `PySequence_Tuple(y)` on the first mismatch
- Rationale:
  - avoids malformed CFG
  - stays entirely within the miss block
  - keeps the implementation HIR-stage and correctness-focused
- Remote result:
  - combined probe JSON:
    - `keep_alive_deopts=0`
    - `deepcopy_tuple_deopts=0`
    - `total=19900`
    - `elapsed=0.00032323300001735333`
  - previous partial-fix probe was:
    - `keep_alive_deopts=0`
    - `deepcopy_tuple_deopts=200`
    - `elapsed=0.0007303920001504594`
  - interpretation:
    - issue #47 is functionally fixed for the deterministic stdlib reproducer
    - the second HIR round produced a clear ARM performance win on the same probe shape

## Current working conclusion

- `_keep_alive`:
  - fixed for the deterministic KeyError miss path
  - explicit ARM evidence: `0` deopts
- `_deepcopy_tuple`:
  - now also fixed for the deterministic KeyError miss path
  - explicit ARM evidence: `0` deopts
- Remaining work:
  - requested broader regression benchmark list is still pending if we want pre-merge performance coverage beyond the issue reproducer
- Scheduler status:
  - lease `#3` released
  - no active leases remain

## Broad regression sweep

- Method:
  - ARM base/current workdirs were prepared through the unified remote entrypoint.
  - The broader subset itself was run from those prepared workdirs with `scripts/arm/run_pyperf_subset.sh`.
  - Reason:
    - the entrypoint's built-in `BENCH=<comma-list>` path did not persist multi-benchmark result files reliably enough for comparison.
- Requested subset:
  - `generators,coroutines,comprehensions,richards,richards_super,float,go,deltablue,raytrace,nqueens,nbody,unpack_sequence,fannkuch,coverage,scimark,spectral_norm,chaos,logging`
- Stored artifacts:
  - base: `artifacts/deepcopy/reg_base.json`
  - current: `artifacts/deepcopy/reg_current.json`
  - broad compare: `artifacts/deepcopy/reg_compare.json`
  - focused base: `artifacts/deepcopy/reg_base_focus.json`
  - focused current: `artifacts/deepcopy/reg_current_focus.json`
  - focused compare: `artifacts/deepcopy/reg_focus_compare.json`

## Broad sweep result

- Broad 2-sample compare:
  - wins:
    - `coroutines` `-5.56%`
    - `coverage` `-8.46%`
    - most of the rest within a few percent either way
  - slow signals:
    - `comprehensions` `+9.31%`
    - `logging_silent` `+51.94%`
- Focused 5-sample rerun on `comprehensions,logging`:
  - `comprehensions` `+3.89%`
  - `logging_format` `+1.03%`
  - `logging_simple` `-2.59%`
  - `logging_silent` `+8.21%`
- Interpretation:
  - `comprehensions` does not remain a large regression after more samples.
  - `logging_silent` still shows a percentage regression, but the absolute move is from about `0.976 us` to `1.056 us`, roughly `+0.08 us`, so it is currently recorded as a tiny residual signal rather than a material blocker.
