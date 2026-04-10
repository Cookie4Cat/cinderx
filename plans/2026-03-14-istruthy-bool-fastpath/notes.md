# Design Notes: issue-37 IsTruthy bool fast path

## Current State
- `simplifyIsTruthy()` already folds:
  - constant trusted objects
  - statically typed `TBool`
  - some length-based cases
- But many hot real-world paths still reach LIR as `IsTruthy` on plain `TObject`.
- Current LIR lowering always emits:
  - `Call PyObject_IsTrue`
  - then a negative-result guard

## Targeted Improvement
- In `Opcode::kIsTruthy` lowering:
  - if operand type is already `TBool`, emit direct compare with `Py_True`
  - otherwise emit a dynamic bool fast path:
    - load `ob_type`
    - compare with `PyBool_Type`
    - if true: compare object pointer with `Py_True`
    - else: fall back to existing `PyObject_IsTrue` call

## Why LIR Instead Of HIR
- The hot cases described in the issue often still have `TObject` in final HIR.
- LIR can still optimize those by guarding on the runtime type without changing HIR semantics or introducing deopts.
- This keeps behavior identical for non-bool objects while removing the C call for actual bool values.

## Validation
- Add an ARM runtime regression based on a bool attribute branch (`Foo.enabled`).
- Require correct output and use targeted remote measurement to confirm improvement for the bool-heavy path.
