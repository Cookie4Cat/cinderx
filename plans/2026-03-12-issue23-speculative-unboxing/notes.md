# Notes: Issue 23

## Initial Questions
- Is there already enough infrastructure to represent "boxed long exact -> native int" without inventing many new HIR ops?
- Can we land a narrow loop-local optimization first, instead of full generic speculative unboxing?
- Where is the safest deopt point if overflow or multi-digit longs appear?
- How much of the current overhead comes from compare vs add vs repeated boxing?

## Candidate Directions
1. Narrow proof-of-concept:
   - exact longs only
   - single-digit compact longs only
   - loop-local `i < n`, `i += 1`, `s += i`
2. More reusable path:
   - add explicit HIR for `UnboxLongExact`, `BoxLong`, and primitive checked add/compare
3. Runtime-helper-heavy bridge:
   - use helpers for uncommon materialization/deopt
   - still try to keep the steady-state loop in native integer registers

## Risk
- Python 3.14 `PyLongObject` layout details matter; getting compact/single-digit detection wrong is correctness-critical.
- Over-aggressive deopt insertion could erase the intended performance win.

## Remote Reproduction
- `hot_loop(n)` final HIR on remote baseline:
  - `LongCompare: 1`
  - `LongInPlaceOp: 2`
  - `PrimitiveCompare: 1`
  - `Decref: 4`
- `fannkuch(9)` final HIR on remote baseline:
  - `LongCompare: 6`
  - `LongInPlaceOp: 4`
  - `LongBinaryOp: 4`

## Phase-1 Attempt
- Implemented locally and validated remotely:
  - compact-long unboxing per operation
  - raw checked int add/sub
  - result re-boxing after each arithmetic op
- Resulting `hot_loop(n)` HIR became:
  - `CheckedIntBinaryOp: 2`
  - `LongUnboxCompact: 3`
  - `PrimitiveBox: 2`
  - `LongCompare: 1`
  - `LongInPlaceOp: 0`

## Benchmark Result
- apples-to-apples remote microbenchmark on `hot_loop(10000)`:
  - baseline median: `1.6614s`
  - phase-1 attempt median: `1.7248s`
  - regression: about `+3.8%`

## Interpretation
- The helper-call removal on the add path did not pay for itself.
- Per-iteration re-boxing remains too expensive.
- Therefore, issue 23 likely needs a stronger design:
  - primitive loop-carried phis for counters/accumulators
  - one-time unboxing at loop entry
  - one-time boxing at loop exit / deopt

## Loop-Carried Primitive Phi Variant
- Added minimal new IR pieces instead of reviving the full phase-1 rewrite:
  - `CheckedIntBinaryOp` for checked add/sub with overflow deopt
  - `LongUnboxCompact` for exact-long compact-value extraction
  - `Guard` lowering support for compact-long checks
- Added a narrow HIR pass `LongLoopUnboxing`:
  - gated on `specialized_opcodes`
  - matches the `hot_loop(n)` style dynamic loop:
    - loop-carried `LongExact` phis
    - one compare against a loop bound
    - backedge updates via `LongInPlaceOp<Add/Subtract>`
  - rewrites to primitive shadow phis plus one exit box

## Remote Validation
- Host: `124.70.162.35`
- Working tree used for final verification: `/root/work/cinderx-git`
- Reconfigured and rebuilt `_cinderx.so` successfully after adding the new pass source to CMake's view
- New targeted runtime regression:
  - `python -m unittest test_cinderx.test_arm_runtime.ArmRuntimeTests.test_hot_loop_uses_long_loop_unboxing`
  - result: `OK`
- Existing regressions re-run:
  - `test_list_annotation_enables_exact_slice_and_item_specialization`
  - `test_primitive_unbox_cse_for_float_add_self`
  - result: both `OK`

## Final HIR Shape
- `hot_loop(n)` final HIR on remote current implementation:
  - `CheckedIntBinaryOp: 2`
  - `LongUnboxCompact: 1`
  - `PrimitiveCompare: 1`
  - `PrimitiveBox: 1`
  - `LongInPlaceOp: 0`
  - `CompareBool: 0`
- The bound `n` is guarded and unboxed once in the preheader.
- `s` and `i` are carried as `CInt64` phis through the loop body.
- The only remaining box is the final return materialization.

## Benchmark Result
- Remote `hot_loop(10000)` apples-to-apples microbenchmark:
  - baseline median: `0.8305595869896933s`
  - current median: `0.028081598924472928s`
  - speedup: about `29.6x`
