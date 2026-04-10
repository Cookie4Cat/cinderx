# Findings: issue-28 float power-square strength reduction

## Remote Verification
- Host: `124.70.162.35`
- Entry: `scripts/arm/remote_update_build_test.sh`
- Mode: remote source sync, wheel build, install, ARM runtime validation
- Options: `PARALLEL=6`, `CINDERX_BUILD_JOBS=6`, `FORCE_CLEAN_BUILD=1`, `SKIP_PYPERF=1`

## Confirmed Results
- The standard remote entry flow completed successfully end-to-end.
- A targeted `square_pow` / `square_mul` repro on the remote host showed matching numeric results:
  - `square_pow(2.718) = 7.387524`
  - `square_mul(2.718) = 7.387524`

## HIR Confirmation
- `square_pow` final HIR now lowers to:
  - `GuardType<FloatExact>`
  - `PrimitiveUnbox<CDouble>`
  - `DoubleBinaryOp<Multiply>`
  - `PrimitiveBox<CDouble>`
- The generic `BinaryOp<Power>` path is no longer present in final HIR for the hot float case.

## Implementation Note
- The fix is intentionally narrow:
  - exponent must be exactly `2` or `2.0`
  - the transformation produces the same float-specialized guard shape as `x * x`
- `FloatBinaryOp<Power>` keeps its existing `x ** 0.5` fast path and now also recognizes `x ** 2`.
