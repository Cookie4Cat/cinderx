# Findings: issue-12 from-import math.sqrt intrinsify

## Remote Verification
- Host: `124.70.162.35`
- Entry: `scripts/arm/remote_update_build_test.sh`
- Mode: remote source sync, wheel build, install, ARM runtime validation
- Options: `PARALLEL=6`, `CINDERX_BUILD_JOBS=6`, `FORCE_CLEAN_BUILD=1`, `SKIP_PYPERF=1`

## Confirmed Results
- The standard remote entry flow completed successfully end-to-end.
- A targeted repro covering both import patterns showed:
  - pattern A (`import math; math.sqrt(x)`):
    - `DoubleSqrt = 1`
    - `VectorCall = 0`
    - result `3.0`
  - pattern B (`from math import sqrt; sqrt(x)`):
    - `DoubleSqrt = 1`
    - `VectorCall = 0`
    - result `4.0`

## Implementation Notes
- The existing module-attr path still uses `GuardModuleAttrValue`.
- The new path recognizes a guarded callee whose `GuardIs` target is the builtin `math.sqrt` object.
- This lets the `from-import` call shape fold to `DoubleSqrt` without requiring a separate global-value guard opcode.

## Additional Note
- A pre-existing ARM build break in [frame_asm.cpp](/c:/work/code/interpreter/cinderx/cinderx/Jit/codegen/frame_asm.cpp) had to be fixed (`remove stray brace in TLS offset probe`) to complete clean remote verification. That fix is orthogonal to the `sqrt` intrinsify logic.
