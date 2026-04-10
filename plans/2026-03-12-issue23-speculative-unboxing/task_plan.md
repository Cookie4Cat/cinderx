# Task Plan: Issue 23 Speculative Unboxing for Int Hot Loops

## Goal
Reduce boxed `LongExact` overhead in integer-dense hot loops by finding the smallest viable speculative unboxing optimization path for the current CinderX JIT.

## Workflow
- Brainstorming equivalent: inspect existing integer HIR/LIR/runtime support before editing.
- Write plan: keep design notes and evidence in this directory.
- TDD equivalent: add targeted tests for the chosen scope.
- Verification before completion: use remote ARM validation for HIR, asm, and benchmark evidence.

## Constraints
- All meaningful execution validation should use `124.70.162.35`.
- Avoid introducing a broad new IR surface if a smaller slice proves the concept.
- Keep overflow behavior correct; any speculative integer path must preserve Python semantics via deopt or fallback.

## Status
- [x] Start planning
- [x] Inspect existing long/int infrastructure
- [x] Reproduce hot-loop baseline on remote
- [x] Implement and evaluate a first unboxing slice
- [x] Implement loop-carried primitive-phi variant
- [x] Verify remotely

## Current Assessment
- Tried a narrower phase-1 slice:
  - speculative compact-long unboxing for `LongInPlaceOp<Add/Subtract>`
  - raw checked-int add/sub
  - result re-boxing after each arithmetic op
- This changed HIR as intended, but did **not** improve the hot loop.
- On remote `hot_loop(10000)` it regressed versus baseline, so this path should not be kept.
- Conclusion:
  - removing helper calls alone is not enough
  - keeping loop-carried values boxed still costs too much
  - the next viable design must keep loop-carried longs as primitive phi values

## Current Result
- Added minimal infrastructure needed for correct speculative long unboxing:
  - `CheckedIntBinaryOp`
  - `LongUnboxCompact`
  - `Guard` lowering with compact-long check
- Added a narrow `LongLoopUnboxing` HIR pass:
  - only runs when `specialized_opcodes` is enabled
  - targets single-backedge `while` loops with loop-carried `LongExact` phis
  - rewrites the hot `CompareBool + LongInPlaceOp + LongInPlaceOp` pattern into:
    - one-time `GuardType<LongExact> + LongUnboxCompact` for the loop bound
    - primitive `CInt64` shadow phis for loop-carried values
    - `PrimitiveCompare`
    - `CheckedIntBinaryOp`
    - one exit `PrimitiveBox`
- Remote validation on `124.70.162.35` passed:
  - build: success
  - new runtime regression: `ArmRuntimeTests.test_hot_loop_uses_long_loop_unboxing` -> `OK`
  - existing runtime regressions re-run:
    - `test_list_annotation_enables_exact_slice_and_item_specialization`
    - `test_primitive_unbox_cse_for_float_add_self`
    - both `OK`
- Remote final HIR for `hot_loop(n)` now shows:
  - `CheckedIntBinaryOp: 2`
  - `LongUnboxCompact: 1`
  - `PrimitiveCompare: 1`
  - `PrimitiveBox: 1`
  - `LongInPlaceOp: 0`
  - `CompareBool: 0`
- Remote microbenchmark on `hot_loop(10000)`:
  - baseline median: `0.8306s`
  - current median: `0.0281s`
  - speedup: about `29.6x`
