# Task Plan: issue-37 IsTruthy bool fast path

## Goal
Avoid unnecessary `_PyObject_IsTrue` calls when `IsTruthy` operates on bool objects by lowering to pointer comparisons instead.

## Scope
- `Opcode::kIsTruthy` lowering in LIR generation
- Static bool input fast path
- Dynamic object input fast path guarded by `PyBool_Type`
- ARM runtime regression coverage and remote verification

## Workflow
1. Brainstorming: inspect current `IsTruthy` simplify/codegen paths and identify where bool still falls through to C calls
2. Writing-Plans: record the chosen LIR fast-path design and validation strategy
3. Test-Driven-Development: add a bool-heavy regression first, then implement
4. Verification-Before-Completion: run remote build/tests and collect evidence

## Status
- [x] Brainstorming
- [x] Writing-Plans
- [x] Test-Driven-Development
- [x] Verification-Before-Completion

## Remote Test Entry
- `scripts/arm/remote_update_build_test.sh`

## Latest Result
- `IsTruthy` lowering now has:
  - a direct static-`TBool` pointer compare path
  - a dynamic bool fast path guarded by `PyBool_Type`
  - fallback to `PyObject_IsTrue` only on non-bool objects
- Remote ARM verification passed through the standard entry script.
- Targeted remote LIR repro showed:
  - `equal_count = 2`
  - `contains_call = True` (slow path retained)
  - runtime result `0`
