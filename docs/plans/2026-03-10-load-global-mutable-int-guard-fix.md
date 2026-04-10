# Plan: Fix LOAD_GLOBAL GuardIs on Mutable Large Int Globals

## Goal
- Fix repeated deopts caused by `LOAD_GLOBAL` using `GuardIs` for mutable large integer globals.
- Follow the requested loop: brainstorming -> writing-plans -> TDD -> verification-before-completion.
- Run all tests and verification through the remote entrypoint `root@124.70.162.35`.
- Record key commands and outcomes in `findings.md`.

## Brainstorming
- Symptom:
  - `LoadGlobalCached` loads the current global-cache value at runtime.
  - `GuardIs` still pins that value to the exact compile-time object.
  - For `TIMESTAMP += 1` with a value outside the small-int cache, each update creates a new `int` object, so the identity guard keeps failing.
- Current code location:
  - In this branch the relevant logic is in `cinderx/Jit/hir/builder.cpp` inside `emitLoadGlobal()`, not `compiler.cpp`.

## Options
1. Narrow fix: only downgrade mortal exact ints from `GuardIs` to `GuardType<TLongExact>`.
2. Broad fix: downgrade all non-immortal globals from `GuardIs` to `GuardType<ExactType>`.

## Chosen Approach
- Use option 1.
- Reason:
  - It fixes the reported benchmark pathology directly.
  - It keeps identity-based specialization for other globals, especially callable globals that may benefit from it.

## TDD
1. Add a remote regression in `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`.
2. Sync the test to the remote host and capture RED on current code.
3. Implement the HIR builder change.
4. Rebuild remotely and capture GREEN.

## Verification
- Targeted:
  - `python cinderx/PythonLib/test_cinderx/test_arm_runtime.py ArmRuntimeTests.test_load_global_mutable_large_int_avoids_repeated_deopts -v`
- Regression:
  - `python cinderx/PythonLib/test_cinderx/test_arm_runtime.py`

## Status
- [x] Brainstorming
- [x] Writing-plans
- [x] TDD-RED
- [x] Implementation
- [x] TDD-GREEN
- [x] Remote verification
