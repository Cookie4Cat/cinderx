# Task Plan: issue-12 from-import math.sqrt intrinsify

## Goal
Extend the existing `math.sqrt` intrinsification so it also handles `from math import sqrt; sqrt(x)` call sites, not only `import math; math.sqrt(x)`.

## Scope
- `VectorCall` simplification for known builtin `math.sqrt`
- `LoadGlobalCached + GuardIs + VectorCall` callee shape
- ARM runtime regression coverage for both import styles
- Remote verification through the standard ARM test entry flow

## Workflow
1. Brainstorming: inspect the current `math.sqrt` intrinsify path and identify the missing callee shape
2. Writing-Plans: record the matching strategy and semantic constraints
3. Test-Driven-Development: add a regression for `from math import sqrt` first, then implement
4. Verification-Before-Completion: run remote build/tests and write findings

## Status
- [x] Brainstorming
- [x] Writing-Plans
- [x] Test-Driven-Development
- [x] Verification-Before-Completion

## Remote Test Entry
- `scripts/arm/remote_update_build_test.sh`

## Latest Result
- `math.sqrt` intrinsify now covers both:
  - `import math; math.sqrt(x)`
  - `from math import sqrt; sqrt(x)`
- Remote ARM verification passed through the standard entry script.
- Targeted remote repro results:
  - pattern A: `DoubleSqrt = 1`, `VectorCall = 0`, result `3.0`
  - pattern B: `DoubleSqrt = 1`, `VectorCall = 0`, result `4.0`
