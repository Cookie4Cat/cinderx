# Task Plan: pyperformance coroutines HIR/LIR fix

## Goal
On remote ARM host `124.70.162.35`, improve the CinderX JIT performance of the
`pyperformance` `coroutines` benchmark on branch `bench-cur-7c361dce`, with HIR
changes preferred over LIR/runtime changes.

## Workflow
1. Brainstorming
2. Writing-Plans
3. Test-Driven-Development
4. Verification-Before-Completion

## Remote Test Entry
- `scripts/arm/remote_update_build_test.sh`

## Benchmark Shape
- `pyperformance` `bm_coroutines`:
  - recursive `await fibonacci(n - 1) + await fibonacci(n - 2)`
  - extremely sensitive to coroutine call / await / resume constant overhead

## Brainstorming
- Hypothesis A:
  - recursive awaited calls spend too much time on generic call lowering
  - likely hot path: `VectorCall -> JITRT_Vectorcall` for runtime `PyFunction`
- Hypothesis B:
  - awaited coroutine path in 3.12+ still pays generic `GET_AWAITABLE` helper
    cost (`JitCoro_GetAwaitableIter` + awaited-state checks) on every recursive
    step
- Hypothesis C:
  - `YieldFrom` / resume / generator runtime state transitions add avoidable
    refcount or helper overhead after call lowering is fixed

## TDD Plan
- Add a targeted regression in `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
  for a recursive coroutine microcase that:
  - preserves functional result
  - captures final HIR / opcode counts for the hottest awaited-call shape
  - gives a stable signal for whichever optimization is chosen
- Only after the test exists, implement the fix.

## Verification Plan
- Remote entry smoke/tests via `scripts/arm/remote_update_build_test.sh`
- Remote pyperformance gate with `BENCH=coroutines`
- Append key results to top-level `findings.md`

## Status
- [completed] Brainstorming: located the remote entry, benchmark shape, and primary hot path
- [completed] Writing-Plans: refined the optimization after remote HIR/deopt evidence
- [completed] Test-Driven-Development: two targeted coroutine regressions are in place
- [completed] Verification-Before-Completion: the standard remote entry now passes the targeted coroutine runtime tests and produces green `coroutines` jitlist/autojit benchmark artifacts on `124.70.162.35`
