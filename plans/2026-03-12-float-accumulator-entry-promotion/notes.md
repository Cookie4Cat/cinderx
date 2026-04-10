# Design Notes: issue-26 float accumulator entry promotion

## Observed HIR Shape
- The failing loop currently compiles into:
  - loop-header `Phi` merging:
    - preheader `LoadConst<0>` (int)
    - backedge float result
  - loop-body `GuardType<FloatExact>` on the accumulator
  - `DoubleBinaryOp<Add>` fast path after the guard
- This means the first iteration of every call always deopts, even though all later iterations are float-only.

## Semantic Constraint
- We cannot simply rewrite the loop-header `Phi` input from `0` to `0.0`.
- If the iterable is empty, the Python result must remain `0` (int), not `0.0` (float).

## Chosen Strategy
- Keep the loop-header `Phi` unchanged for the zero-iteration return path.
- Instead, specialize `simplifyGuardType(FloatExact)` for the narrow pattern:
  - guarded input is a `Phi`
  - all incoming values are either:
    - exact floats
    - exact integer constant `0`
- Replace the guard with a value-producing conditional:
  - float arm: keep the input and refine it to `FloatExact`
  - zero-int arm: use a float `0.0` constant
- This repairs the first-iteration path without changing the empty-loop return value.

## Why This Is Better Than Recompile Feedback
- The HIR already contains enough static information to fix the issue before runtime.
- No new recompile machinery or guard-failure heuristics are required.
- The transform is narrow and local to an existing simplification site.

## Validation
- Add an ARM runtime regression for:
  - `accumulate(data)` with `s = 0` and float elements
  - repeated calls after JIT compilation
  - assert repeated-call deopt count is `0`
  - preserve float result and keep `DoubleBinaryOp<Add>` in final HIR
