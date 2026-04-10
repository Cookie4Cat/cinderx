# Findings: issue-19 getlength unboxing

## Remote Verification
- Host: `124.70.162.35`
- Build mode: remote wheel build + install into `/root/venv-cinderx314`
- Parallelism: `PARALLEL=6`

## Confirmed Results
- `ArmRuntimeTests.test_math_sqrt_cdouble_lowers_to_double_sqrt`: PASS
- `ArmRuntimeTests.test_math_sqrt_negative_input_preserves_value_error`: PASS
- `ArmRuntimeTests.test_slot_type_version_guards_are_deduplicated`: PASS
- `ArmRuntimeTests.test_len_arithmetic_uses_primitive_int_chain`: PASS

## HIR Confirmation
- Remote HIR dump for the `len()` arithmetic reproducer showed:
  - `LongCompare<Equal>` count: `0`
  - `LongBinaryOp<FloorDivide>` count: `0`
  - `LongBinaryOp<Add>` count: `0`
  - `PrimitiveCompare<Equal>` count: `1`
  - `IntBinaryOp<...>` count: `2`
- Runtime outputs matched expectation:
  - `-1, 1, 2, 2, 3, 26`

## Notes
- A temporary typo in the remote helper script truncated one test name (`...value_erro`); this only affected the remote wrapper, not repository code.
- After correcting the remote helper script, the full remote entry flow completed successfully.
