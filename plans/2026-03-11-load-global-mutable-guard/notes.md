# Design Notes: issue-21 mutable load_global guard strategy

## Current Behavior
- `HIRBuilder::emitLoadGlobal()` lowers watchable globals to:
  - `LoadGlobalCached`
  - then either `GuardIs` or a special-case `GuardType` for large mortal ints
- This means mutable object globals such as `planner = Planner()` are pinned to the compile-time instance identity.

## Confirmed Root Cause
- The global cache slot itself is fine: rebinding updates the cached pointer.
- The problem is the extra `GuardIs` on the loaded value.
- Once the global is rebound, the guard fails on every call and the function keeps deopting instead of running on the compiled path.

## Candidate Fix
- Generalize the current large-int special case.
- Keep `GuardIs` only for values that are worthwhile to treat as identity-stable constants.
- Use `GuardType` for mutable mortal runtime objects whose exact type is known and stable enough to preserve downstream specialization.

## Conservative Direction
- Preserve `GuardIs` for:
  - functions / methods / modules / types
  - immortal constants / true singleton-style values
- Prefer `GuardType` for:
  - mortal exact objects with a unique runtime type, including user-defined instances like `Planner()`

## Expected Outcome
- Mutable object globals stop producing repeated `GuardFailure` deopts after rebinding.
- Final HIR should no longer show `GuardIs<compile_time_instance>` for those globals.
- Type-based specialization should still be available to downstream passes.

## Risks
- If the heuristic is too broad, stable constant globals may lose some constant-propagation opportunities.
- If the heuristic is too narrow, object-global rebinding will still deopt.
- Need to ensure builtins / function globals that benefit from identity-based specialization keep that behavior.
