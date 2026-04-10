# Design Notes: issue-19 getlength unboxing

## Observation
- `GetLength` currently returns boxed `LongExact`.
- `simplifyGetLength()` already knows how to read `ob_size` as `TCInt64`, but immediately boxes it.
- The reported hot path is specifically:
  - `n = len(lst)`
  - `n == 0`
  - `n // 2`
  - `n + 1`

## Likely low-risk strategy
- Do not globally change `GetLength` to return `CInt64`.
- Instead, recognize boxed-`len()` producers in simplification and bypass boxing for specific consumers:
  - `LongCompare<Equal>` with `0`
  - `LongBinaryOp<FloorDivide>` with positive power-of-two constants, at least `2`
  - `LongBinaryOp<Add>` with small integer constants, at least `1`
- This keeps Python-level `len()` behavior intact while collapsing the arithmetic chain to primitive integer ops.

## Candidate rewrites
- `LongCompare<Equal>(GetLength(...), 0)` -> `PrimitiveCompare<Equal>(len_i64, 0)`
- `LongBinaryOp<FloorDivide>(GetLength(...), 2)` -> `IntBinaryOp<RShift>(len_i64, 1)` or `IntBinaryOp<FloorDivide>(len_i64, 2)`
- `LongBinaryOp<Add>(mid, 1)` -> `IntBinaryOp<Add>(mid_i64, 1)`
- Re-box only if later consumers still need Python objects.

## Risks
- `LongBinaryOp<FloorDivide>` is not generally equivalent to shift for negative values, but `len()` is non-negative, so the rewrite is valid when the source is proven to be `GetLength`.
- Need to avoid affecting arbitrary `LongExact` arithmetic outside this narrow pattern.
