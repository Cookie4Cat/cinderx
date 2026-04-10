# Task Plan: issue-26 float accumulator entry promotion

## Goal
Eliminate the repeated deopt loop caused by `s = 0` followed by float accumulation in hot loops, without changing empty-iteration semantics.

## Scope
- Loop-header / accumulator HIR shape for specialized float `BINARY_OP`
- `GuardType<FloatExact>` simplification around mixed `Phi` inputs
- Regression coverage for repeated-call deopt behavior
- Remote ARM verification through the standard test entry flow

## Workflow
1. Brainstorming: inspect the `Phi` + `GuardType<FloatExact>` shape in the failing loop
2. Writing-Plans: record the chosen repair strategy and semantic constraints
3. Test-Driven-Development: add a regression for repeated deopts first, then implement
4. Verification-Before-Completion: run remote build/tests and write findings

## Status
- [x] Brainstorming
- [x] Writing-Plans
- [x] Test-Driven-Development
- [x] Verification-Before-Completion

## Remote Test Entry
- `scripts/arm/remote_update_build_test.sh`

## Latest Result
- The fix is implemented as a dedicated HIR pass that introduces a float-only
  parallel `Phi` for the loop body while preserving the original mixed `Phi`
  for the empty-iteration return path.
- Remote ARM verification passed through the standard entry script.
- Targeted remote repro results:
  - runtime stats: `{'deopt': []}`
  - `GuardType = 1`
  - `DoubleBinaryOp = 1`
  - result: `1000.0`
- Remote performance comparison against baseline `0f7bd9a1` showed:
  - `accumulate`: about `1.39x` faster
  - `accumulate_sq`: about `2.32x` faster
