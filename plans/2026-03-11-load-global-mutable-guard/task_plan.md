# Task Plan: issue-21 mutable load_global guard strategy

## Goal
Stop JIT-compiled `LOAD_GLOBAL` sites from becoming persistent deopt points when a mutable global is rebound to a new object of the same exact type.

## Scope
- `HIRBuilder::emitLoadGlobal()`
- Guard selection for `LoadGlobalCached`
- Regression coverage for mutable object globals
- Remote ARM verification through the standard remote test entry flow

## Workflow
1. Brainstorming: inspect current `LOAD_GLOBAL` lowering and existing mutable-global regressions
2. Writing-Plans: record the chosen guard strategy, tradeoffs, and risks
3. Test-Driven-Development: add a failing regression for mutable object globals, then implement
4. Verification-Before-Completion: run remote build/tests and write findings

## Status
- [x] Brainstorming
- [x] Writing-Plans
- [x] Test-Driven-Development
- [x] Verification-Before-Completion

## Remote Test Entry
- `scripts/arm/remote_update_build_test.sh`

## Latest Result
- Issue 21 implementation is in place locally and verified on `124.70.162.35`.
- The standard remote entry flow completed successfully with `SKIP_PYPERF=1`.
- The mutable-object global regression no longer emits `GuardIs` for `get_planner()`.
- Runtime deopt count for repeated planner rebinding is `0`.
