# Task Plan: issue-19 getlength unboxing

## Goal
Eliminate boxed `LongExact` / `Bool` objects when `len()` feeds simple integer arithmetic and comparisons in JIT-compiled code.

## Scope
- `GetLength`
- `LongCompare`
- `LongBinaryOp`
- HIR simplification around `len()` arithmetic chains
- Remote ARM verification through the standard remote test entrypoint

## Workflow
1. Brainstorming: inspect current HIR shapes and choose the smallest safe lowering
2. Writing-Plans: record design, risks, and validation path
3. Test-Driven-Development: add regression tests first, then implement
4. Verification-Before-Completion: run remote build/tests and write findings

## Status
- [x] Brainstorming
- [x] Writing-Plans
- [x] Test-Driven-Development
- [x] Verification-Before-Completion

## Remote Test Entry
- `scripts/arm/remote_update_build_test.sh`

## Latest Result
- Issue 19 implementation is in place locally and verified on `124.70.162.35`.
- Remote build/test was rerun with `PARALLEL=6`.
- Clean build verification passed, followed by an incremental rerun of the same remote entry flow.
- Targeted ARM runtime checks all passed:
  - `ArmRuntimeTests.test_math_sqrt_cdouble_lowers_to_double_sqrt`
  - `ArmRuntimeTests.test_math_sqrt_negative_input_preserves_value_error`
  - `ArmRuntimeTests.test_slot_type_version_guards_are_deduplicated`
  - `ArmRuntimeTests.test_len_arithmetic_uses_primitive_int_chain`
