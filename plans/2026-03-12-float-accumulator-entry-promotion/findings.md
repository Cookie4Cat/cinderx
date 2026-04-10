# Findings: issue-26 float accumulator entry promotion

## Remote Verification
- Host: `124.70.162.35`
- Entry: `scripts/arm/remote_update_build_test.sh`
- Mode: remote source sync, wheel build, install, ARM runtime validation
- Options: `PARALLEL=6`, `CINDERX_BUILD_JOBS=6`, `FORCE_CLEAN_BUILD=1`, `SKIP_PYPERF=1`

## Confirmed Results
- The standard remote entry flow completed successfully end-to-end.
- A targeted `accumulate()` repro on the remote host showed:
  - runtime stats: `{'deopt': []}`
  - opcode counts include:
    - `DoubleBinaryOp = 1`
    - `GuardType = 1`
    - `Phi = 3`
  - final result: `1000.0`

## HIR Confirmation
- The optimized HIR now contains:
  - the original mixed `Phi` for the accumulator, still used on the empty-loop return path
  - a new float-only parallel `Phi`
  - only one remaining `GuardType`, on the incoming float element
- The previous `GuardType<FloatExact>` on the accumulator itself is gone.

## Behavioral Outcome
- Repeated calls no longer hit the first-iteration guard failure loop.
- Empty-iteration semantics remain intact because the original `int 0` path is preserved for `return s` when the loop body never runs.

## Performance Comparison
- Baseline: committed branch head `0f7bd9a1` (`Compact generator decref lowering`)
- Candidate: current working tree with float-accumulator-entry promotion
- Host: `124.70.162.35`
- Benchmark method:
  - build/install baseline and candidate into separate remote venvs
  - run the same hot-loop benchmark script for 7 samples each
  - compare mean wall time

### `accumulate(data)`
- Baseline:
  - mean: `0.01344s`
  - median: `0.01343s`
  - deopts: `3500`
- Candidate:
  - mean: `0.00964s`
  - median: `0.00961s`
  - deopts: `0`
- Delta:
  - about `28.3%` lower time
  - about `1.39x` speedup

### `accumulate_sq(data)`
- Baseline:
  - mean: `0.02242s`
  - median: `0.02242s`
  - deopts: `3500`
- Candidate:
  - mean: `0.00967s`
  - median: `0.00967s`
  - deopts: `0`
- Delta:
  - about `56.9%` lower time
  - about `2.32x` speedup

## Interpretation
- The candidate slightly increases compiled size (`1000 -> 1096` for `accumulate`, `1008 -> 1096` for `accumulate_sq`), but eliminating the per-call first-iteration deopt more than pays for it.
- The larger speedup on `accumulate_sq` is consistent with keeping more of the loop on the compiled float fast path instead of repeatedly bouncing through deopt.
