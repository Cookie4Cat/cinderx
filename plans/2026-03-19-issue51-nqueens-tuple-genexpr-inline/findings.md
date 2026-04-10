# Findings: Issue 51 tuple(genexpr) inline for bm_nqueens

## 2026-03-19 kickoff

- Working branch: `codex/nqueens-tuple-genexpr-inline`
- Clean worktree: `C:/work/code/generators-nqueens-clean`
- Remote entry for all verification:
  - `scripts/arm/remote_update_build_test.sh`
- Shared scheduler DB:
  - `plans/remote-scheduler.sqlite3`

## Known baseline before this round

- Historical direct `bench_n_queens(8)`:
  - `compile_strategy=all`: `1.1747283110162243s`
  - `compile_strategy=none`: `1.389004991040565s`
  - no runtime deopts
- Historical hotspot note:
  - `permutations` still pays `CallMethod + MakeFunction` around `tuple(genexpr)`

## To fill after implementation

- Local targeted tests:
  - local Windows environment has no `python`, so runnable local verification was not available
- ARM remote lease ids:
  - compile `#10`: first ARM build/install and initial tuple(genexpr) tests
  - verify `#11`: bytecode/HIR shape capture and root-cause correction
  - compile `#12`: final clean install without temporary debug logging
  - benchmark `#13`: direct `bm_nqueens` and requested benchmark subset smoke
- ARM direct benchmark:
  - `bench_n_queens(8)` via `bench_pyperf_direct.py`
    - `compile_strategy=all`: median `0.13829927999904612s`
    - `compile_strategy=none`: median `0.2242956129994127s`
    - `total_deopt_count = 0`
- ARM regression subset:
  - requested subset completed once each on the final installed build:
    - `generators`
    - `coroutines`
    - `comprehensions`
    - `richards`
    - `richards_super`
    - `float`
    - `go`
    - `deltablue`
    - `raytrace`
    - `nqueens`
    - `nbody`
    - `unpack_sequence`
    - `fannkuch`
    - `coverage`
    - `scimark`
    - `spectral_norm`
    - `chaos`
    - `logging`
  - no `Benchmark died` in this smoke run
- x86 comparison:
  - not run in this round; user focus was to land and verify the ARM-side optimization and broad ARM regression smoke first

## 2026-03-19 Round 1 - HIR tuple(genexpr) inline

- First attempt status:
  - build/install succeeded on ARM
  - targeted tuple(genexpr) tests showed the rewrite did not trigger
  - simple/closure HIR still contained:
    - `CallMethod = 1`
    - `InvokeIterNext = 1`
    - `ListAppend = 1`
    - `CallIntrinsic<INTRINSIC_LIST_TO_TUPLE> = 1`
- Root cause:
  - the initial builder matcher modeled the optimized tuple path incorrectly
  - actual 3.14 optimized shape is:
    - `CALL 0`
    - `FOR_ITER`
    - `LIST_APPEND 2`
    - `JUMP_BACKWARD`
    - `END_FOR`
    - `POP_ITER`
    - `CALL_INTRINSIC_1(INTRINSIC_LIST_TO_TUPLE)`
    - then either:
      - `RETURN_VALUE`, or
      - `JUMP_FORWARD` into the outer `yield` continuation
  - additionally, `FOR_ITER.getJumpTarget()` in the builder points at the
    `POP_ITER` offset, not at the preceding `END_FOR`

## 2026-03-20 Round 1 - corrected HIR rewrite

- Final retained change:
  - the tuple(genexpr) builder rewrite now accepts cleanup targets that start at
    `POP_ITER`
  - it handles both:
    - direct-return tuple shape
    - `yield tuple(...)` continuation shape
- ARM targeted tests on final installed build:
  - `ArmRuntimeTests.test_tuple_genexpr_eliminates_generator_call`
  - `ArmRuntimeTests.test_tuple_genexpr_with_closure_eliminates_generator_call`
  - `ArmRuntimeTests.test_tuple_genexpr_preserves_exception_behavior`
  - `ArmRuntimeTests.test_tuple_genexpr_with_closure_preserves_exception_behavior`
  - `ArmRuntimeTests.test_tuple_genexpr_yield_shape_eliminates_generator_call`
  - result: all `OK`
- Targeted functional signal:
  - `yield tuple(pool[i] for i in indices[:r])` now reports:
    - `CallMethod = 0`
    - `MakeList = 1`
    - `ListAppend = 1`
    - `MakeTupleFromList = 1`
    - result `[(10, 20, 30)]`

## Interpretation

- The retained optimization is real:
  - HIR-level generator-object creation is removed from the optimized tuple path
  - both simple and closure cases stay correct
  - the actual `bm_nqueens`-like `yield tuple(...)` shape is covered
- The strongest quantitative signal captured this round is current-build
  `all` vs `none` on the same host:
  - `0.1383s` vs `0.2243s`
  - about `38.3%` faster in compiled-all mode
- Caution:
  - this round did not rebuild a same-host pre-patch baseline, so the direct
    incremental delta vs immediately previous source is not claimed from these
    numbers alone
