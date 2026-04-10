# Findings: issue-32 bimorphic unpack_sequence fast path

## Remote Verification
- Host: `124.70.162.35`
- Entry: `scripts/arm/remote_update_build_test.sh`
- Mode: remote source sync, wheel build, install, ARM runtime validation
- Options: `PARALLEL=6`, `CINDERX_BUILD_JOBS=6`, `FORCE_CLEAN_BUILD=1`, `SKIP_PYPERF=1`

## Confirmed Results
- The standard remote entry flow completed successfully end-to-end.
- A targeted shared tuple/list unpack repro showed:
  - `LoadFieldAddress = 1`
  - `LoadField = 1`
  - `DeoptCount = 0`
  - `TupleResult = 18000`
  - `ListResult = 18000`

## Interpretation
- The compiled function now retains both data paths:
  - tuple path via `LoadFieldAddress`
  - list path via `LoadField`
- The previous permanent list-side deopt loop is gone.

## Lightweight Performance Check
- Shared-function microbenchmark on the remote host:
  - tuple: `0.0292s`
  - list: `0.0316s`
  - ratio: `1.08x`
- This is consistent with the user’s hypothesis that list unpack itself is not inherently much slower once it stays on the compiled fast path.

## Implementation Summary
- Specialized `UNPACK_SEQUENCE_*` opcodes no longer emit a monomorphic pre-guard.
- They now only choose branch order:
  - tuple-specialized: tuple check first, list second
  - list-specialized: list check first, tuple second
- Deopt now only occurs when the runtime object is neither tuple nor list (or list fast path is unavailable under `Py_GIL_DISABLED`).
