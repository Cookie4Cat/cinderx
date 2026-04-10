# Findings: issue-21 mutable load_global guard strategy

## Remote Verification
- Host: `124.70.162.35`
- Entry: `scripts/arm/remote_update_build_test.sh`
- Mode: remote source sync, wheel build, install, ARM runtime validation
- Options: `FORCE_CLEAN_BUILD=1`, `SKIP_PYPERF=1`

## Confirmed Results
- The standard remote entry flow completed successfully end-to-end.
- A targeted post-build repro confirmed:
  - `GuardIs = 0`
  - `GuardType = 1`
  - `DeoptCount = 0`
  - `CurrentMark = 2000`

## Behavior Change
- `LOAD_GLOBAL planner` no longer pins `get_planner()` to a compile-time `Planner` instance identity.
- Rebinding `planner = Planner()` repeatedly now stays on the compiled path as long as the exact type remains the same.

## Scope of the Fix
- Existing large-mortal-int behavior was preserved.
- User heap-type instances loaded from globals now use `GuardType` instead of `GuardIs`.
- Stable globals such as modules, functions, types, and immortal constants still keep identity guards.
