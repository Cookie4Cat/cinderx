# Deliverable: issue-28 float power-square strength reduction

Implemented a narrow strength-reduction for float power-square in [simplify.cpp](/c:/work/code/interpreter/cinderx/cinderx/Jit/hir/simplify.cpp).

For exponent exactly `2` or `2.0`, the JIT now rewrites the float hot path to the same unboxed multiply sequence used by `x * x`:
- `GuardType<FloatExact>`
- `PrimitiveUnbox<CDouble>`
- `DoubleBinaryOp<Multiply>`
- `PrimitiveBox<CDouble>`

Regression coverage was added in [test_arm_runtime.py](/c:/work/code/interpreter/cinderx/cinderx/PythonLib/test_cinderx/test_arm_runtime.py), and remote ARM verification confirmed that `square_pow` now lowers to `DoubleBinaryOp<Multiply>` instead of retaining `BinaryOp<Power>` in final HIR.
