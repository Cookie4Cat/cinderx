# Task Plan: merge facebookincubator/cinderx main into bench-cur-7c361dce

## Goal
Merge `facebookincubator/cinderx:main` into local `bench-cur-7c361dce`,
resolve conflicts cleanly, verify basic functionality plus key performance
benchmarks (`richards`, `generators`, `raytrace`), and push the validated result
to `origin/bench-cur-7c361dce`.

## Workflow
1. Brainstorming
2. Writing-Plans
3. Merge + Conflict Resolution
4. Functional Verification
5. Performance Verification
6. Push Verified Result

## Inputs
- Local branch: `bench-cur-7c361dce`
- Remote target: `origin/bench-cur-7c361dce`
- Upstream source: `facebookincubator/cinderx:main`

## Verification Targets
- Build/install remains functional
- Basic runtime sanity checks stay green
- Benchmark gates to spot regressions:
  - `richards`
  - `generators`
  - `raytrace`

## Status
- [completed] Brainstorming / Writing-Plans: upstream main was fetched via remote-host git bundle, merge surface identified, and a dedicated merge branch was used for integration
- [completed] Merge + Conflict Resolution: upstream main merged and the remaining API/conflict fallout was resolved on the branch
- [completed] Functional Verification: remote ARM scratch build succeeded and `test_arm_runtime.py` finished green (`Ran 50 tests ... OK`)
- [completed] Performance Verification: remote `richards`, `generators`, and `raytrace` autojit50 runs all improved versus the pre-merge baseline
- [in_progress] Push Verified Result: finalize local commits and fast-forward `origin/bench-cur-7c361dce`
