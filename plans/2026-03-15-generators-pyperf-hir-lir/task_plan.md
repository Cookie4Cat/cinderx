# Task Plan: pyperformance generators HIR/LIR optimization

## Goal
Optimize the CinderX JIT path exercised by `pyperformance generators` on the
remote ARM host `124.70.162.35`, prioritizing HIR improvements first and only
using LIR changes where HIR is insufficient.

## Constraints
- Follow the workflow: brainstorming -> writing-plans -> test-driven-development
  -> verification-before-completion.
- All meaningful tests/verification must go through the standard remote entry
  flow rooted at `scripts/push_to_arm.ps1` ->
  `scripts/arm/remote_update_build_test.sh`.
- Record key commands, measurements, and conclusions in `findings.md`.

## Remote Entry
- Windows entry: `scripts/push_to_arm.ps1`
- Remote entry: `scripts/arm/remote_update_build_test.sh`
- Host: `124.70.162.35`
- Benchmark: `generators`

## Phase Status

### Phase 1: Brainstorming
- [x] Collect current remote `generators` benchmark behavior and hot JIT shapes
- [x] Inspect current generator-specific HIR/LIR fixes already present
- [x] Select the highest-confidence remaining optimization target
- Status: completed

### Phase 2: Writing-Plans
- [x] Record the chosen optimization, rejected alternatives, and risks in notes
- [x] Define the TDD target before code changes
- Status: completed

### Phase 3: Test-Driven-Development
- [x] Add/adjust focused regression coverage for the chosen HIR/LIR behavior
- [x] Implement the optimization with HIR-first bias
- [x] Keep the change isolated from unrelated JIT paths
- Status: completed

### Phase 4: Verification-Before-Completion
- [x] Run the unified remote entry with `generators`
- [x] Re-check targeted generator regression coverage on remote ARM
- [x] Capture benchmark/HIR/LIR evidence and append to `findings.md`
- Status: completed

## Baseline Summary
- Unified remote entry passed on a clean `WORKDIR`
  (`/root/work/cinderx-generators-base`) with unrelated ARM runtime failures
  explicitly skipped via `ARM_RUNTIME_SKIP_TESTS`.
- pyperformance baseline on `124.70.162.35`:
  - `jitlist`: `0.1604569710 s`
  - `autojit=50`: `0.1209691360 s`
  - auto-jit compiled only 3 benchmark-local `__main__` functions
- Current hot compiled functions from `bm_generators`:
  - `Tree.__iter__`: `compiled_size = 2528`
  - `bench_generators`: `compiled_size = 2712` (not hot in auto-jit gate)
  - `tree`: `compiled_size = 1704` (not timed by the benchmark loop)

## Chosen Optimization
- HIR already reflects the earlier generator field-lowering and decref-compaction
  fixes; the remaining hot cost is LIR-side `IsTruthy` lowering on `Tree/None`
  field values inside `Tree.__iter__`.
- Implement a generalized `IsTruthy` fast path for:
  - `obj is Py_None` -> false
  - exact `bool` -> compare with `Py_True`
  - objects with no `nb_bool`, `mp_length`, or `sq_length` slots -> true
- Keep `PyObject_IsTrue` as the slow path when any truthiness slot exists.

## Deliverables
- Updated source + regression tests
- Remote verification evidence in `findings.md`
- Final summary in `deliverable.md`
