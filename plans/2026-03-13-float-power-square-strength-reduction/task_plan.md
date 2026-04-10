# Task Plan: issue-28 float power-square strength reduction

## Goal
Lower `float ** 2` to the same unboxed multiply path as `float * float`, so hot numeric code avoids the generic `PyNumber_Power` path.

## Scope
- `BinaryOp<Power>` / `FloatBinaryOp<Power>` simplification for exact-float base
- Constant exponent pattern `2` / `2.0`
- ARM runtime regression coverage for HIR lowering and behavior
- Remote verification through the standard ARM test entry flow

## Workflow
1. Brainstorming: inspect the current float-power path and find the narrowest safe lowering site
2. Writing-Plans: record the chosen rewrite, semantics, and validation
3. Test-Driven-Development: add a regression for `x ** 2` before changing the simplifier
4. Verification-Before-Completion: run remote build/tests and record findings

## Status
- [x] Brainstorming
- [x] Writing-Plans
- [x] Test-Driven-Development
- [x] Verification-Before-Completion

## Remote Test Entry
- `scripts/arm/remote_update_build_test.sh`

## Latest Result
- `float ** 2` now lowers through the same unboxed multiply path as `float * float`.
- Remote ARM verification passed through the standard entry script.
- Targeted remote HIR repro showed:
  - `square_pow` now contains `GuardType<FloatExact>`
  - `PrimitiveUnbox<CDouble>`
  - `DoubleBinaryOp<Multiply>`
  - `PrimitiveBox<CDouble>`
