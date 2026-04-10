# Task Plan: issue-22 generators attr/decref optimization

## Goal
Reduce the generator-path overhead exposed by the `generators.py` benchmark, with emphasis on repeated `LoadAttrCached` and excessive refcount/decref expansion.

## Scope
- Generator-heavy `yield from` path in HIR/LIR
- `LoadAttrCached` duplication around truthiness checks
- Refcount insertion / decref lowering behavior when it is a dominant cost
- Remote verification through the standard ARM test entry flow

## Workflow
1. Brainstorming: inspect current HIR/LIR patterns and pick the highest-value safe optimization
2. Writing-Plans: record the chosen design, alternative hypotheses, and risks
3. Test-Driven-Development: add targeted regression coverage first, then implement
4. Verification-Before-Completion: run remote build/tests and write findings

## Status
- [x] Brainstorming
- [x] Writing-Plans
- [x] Test-Driven-Development
- [x] Verification-Before-Completion

## Remote Test Entry
- `scripts/arm/remote_update_build_test.sh`

## Latest Result
- The first fix targets the highest-confidence root cause found during analysis:
  generator helpers with very few locals were blocked from instance-value lowering.
- Remote ARM verification passed through the standard entry script.
- A targeted repro on the remote host showed:
  - `LoadField = 20`
  - `LoadAttrCached = 0`
  - `Decref = 10`
  - `BatchDecref = 0`
- This confirms attr-cache C calls were removed for the generator path, while decref blowup remains a follow-up optimization area.

## Phase 2 Result
- Generator `Decref/XDecref` lowering now uses runtime helpers instead of per-site multi-block inline expansion.
- Remote ARM verification passed again through the standard entry script.
- A targeted remote LIR repro showed:
  - `bb_count = 43`
  - `compiled_size = 2424`
  - output sequence still `[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]`
