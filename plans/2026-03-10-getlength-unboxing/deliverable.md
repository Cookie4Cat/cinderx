# Deliverable: issue-19 getlength unboxing

Implemented a primitive `len()` arithmetic path for the issue 19 pattern.

The JIT now introduces `GetLengthInt64`, keeps `len()`-derived values recognizable through simplification, and rewrites the hot arithmetic chain away from boxed `LongCompare` / `LongBinaryOp` into primitive compare and integer ops where the source is provably length-derived.

Remote verification on `124.70.162.35` passed with `PARALLEL=6`, including the dedicated regression `ArmRuntimeTests.test_len_arithmetic_uses_primitive_int_chain`. The remote HIR check confirmed:
- no `LongCompare<Equal>`
- no `LongBinaryOp<FloorDivide>`
- no `LongBinaryOp<Add>`
- one `PrimitiveCompare<Equal>`
- two `IntBinaryOp<...>` operations
