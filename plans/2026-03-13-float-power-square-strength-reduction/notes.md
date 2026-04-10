# Design Notes: issue-28 float power-square strength reduction

## Current State
- `x * x` on exact floats already lowers to:
  - `PrimitiveUnbox<CDouble>`
  - `DoubleBinaryOp<Multiply>`
  - `PrimitiveBox<CDouble>`
- `x ** 2` still goes through the generic power path and ultimately calls Python numeric helpers.

## Existing Related Optimization
- `simplifyFloatBinaryOp()` already has a special case for:
  - `x ** 0.5`
  - lowered to unboxed `DoubleBinaryOp<Power>` so LIR/codegen can map it to `sqrt`

## Chosen Strategy
- Extend the float-power simplification to match exponent `2` as well.
- For exact-float base and exponent `2` / `2.0`:
  - unbox base once
  - emit `DoubleBinaryOp<Multiply>` with the same operand twice
  - box the result back to `FloatExact`

## Why This Site
- It reuses the existing float fast-path infrastructure.
- No new opcode or pass is needed.
- It is narrower and lower-risk than rewriting generic `BinaryOp<Power>` globally.

## Semantic Constraints
- Only apply when the base is already exact-float.
- Restrict to exponent exactly `2` or `2.0`; do not try to generalize other exponents.
- Preserve Python object result type (`FloatExact`) by boxing the final `CDouble`.

## Validation
- Add a regression that compares:
  - `square_pow(x) = x ** 2`
  - `square_mul(x) = x * x`
- Require final HIR for `square_pow` to contain `DoubleBinaryOp<Multiply>` and avoid the generic power path.
