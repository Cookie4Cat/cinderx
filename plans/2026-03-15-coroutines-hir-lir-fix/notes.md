# Notes: pyperformance coroutines HIR/LIR fix

## Confirmed Environment
- Local repo: `C:\work\code\coroutines\cinderx`
- Branch: `bench-cur-7c361dce`
- Remote host SSH: `root@124.70.162.35` works
- Unified remote entry:
  - Windows launcher: `scripts/push_to_arm.ps1`
  - ARM entrypoint: `scripts/arm/remote_update_build_test.sh`

## Current Constraints
- Top-level `task_plan.md` is for another task; keep this work isolated under
  `plans/2026-03-15-coroutines-hir-lir-fix/`.
- Meaningful validation should go through the standard remote entrypoint.

## Relevant Existing Signals
- Historical docs already show `coroutines` is materially slower under CinderX
  JIT than both CinderX interpreter and CPython own JIT.
- The branch already has strong `test_arm_runtime.py` coverage for HIR/LIR
  regression guards, including remote-friendly dump-based assertions.

## Initial Code Read
- `emitAnyCall()` in `cinderx/Jit/hir/builder.cpp` disables awaited-call
  detection on 3.12+ (`is_awaited = false`).
- `emitGetAwaitable()` still performs generic helper-driven awaitable handling.
- Generic `VectorCall` on 3.12+ lowers through `JITRT_Vectorcall` whenever the
  callable is not statically known as `TFunc`.
- Recursive coroutine calls in the benchmark are a plausible match for that
  generic path.

## Additional Confirmation
- Current branch does not yet fast-path runtime `PyFunction` callables in:
  - `JITRT_Call()`
  - `JITRT_Vectorcall()`
- That means a hot recursive shape can still pay the generic
  `_PyObject_VectorcallTstate(...)` path even when the runtime callable is a
  plain Python function.
- `JITRT_CallMethod()` is also absent on this branch, so there is no dedicated
  method-shaped helper yet either.

## Working Optimization Order
1. Confirm current remote `coroutines` baseline on this branch.
2. Add a targeted ARM regression that exposes the recursive coroutine hot path.
3. Prefer an HIR-visible optimization if a clear one emerges.
4. If the dominant cost is still generic call runtime overhead, land the small
   runtime helper fast path and keep the regression focused on the benchmark
   shape rather than helper internals.

## Closure
- The final fix stayed HIR-first:
  - `CLEANUP_THROW` is now modeled as an exception-only deopt path
  - fresh known coroutine call results bypass generic awaitable helpers in
    `emitGetAwaitable()`
- The auxiliary LIR/backend fix that remained necessary was:
  - initialize `initial_yield_spill_size_` to `0` in regalloc so recursive
    coroutine compilation no longer trips the assertion on clean builds
- Standard remote entry validation on `124.70.162.35` is now green:
  - `ArmRuntimeTests.test_recursive_coroutine_fibonacci_force_compile`
  - `ArmRuntimeTests.test_recursive_coroutine_immediate_await_skips_awaitable_helpers`
  - `coroutines` jitlist: `55.61 ms`
  - `coroutines` autojit50: `55.77 ms`
- The earlier `get_function_hir_opcode_counts()` mismatch did not reproduce in
  the standard-entry path once the clean-build + latest HIR/regalloc fixes were
  in place.
