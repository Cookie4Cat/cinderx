# Task Plan: Issue 31 Raytrace Regression Fix

## Goal
Keep the issue31 instance-attr specialization gains while removing the severe raytrace regression introduced by commit `4c14dd10`.

## Current Phase
Closeout complete: revalidated on ARM staging and ready for review.

## Phases

### Phase 1: Reproduction and root cause
- [x] Reproduce the regression on the provided raytrace script on remote ARM
- [x] Confirm whether the regression is caused by exact `other` arg guards, downstream float specialization, or both
- [x] Capture current HIR/deopt evidence for the hottest failing methods
- Status: completed

### Phase 2: Minimal safe fix
- [x] Narrow or remove the unsafe exact-arg inference that causes the regression
- [x] Preserve the stable issue31 gains on the safe Point.dist / linear_combination-style shape
- [x] Add a regression test for the raytrace shape
- Status: completed

### Phase 3: Verification
- [x] Remote rebuild on ARM staging
- [x] Verify the new raytrace regression test
- [x] Re-run the issue31 targeted test to ensure no regression on the intended optimization
- [x] Check raytrace deopt counts and timing after the fix
- Status: completed

### Phase 4: Evidence
- [x] Append the root cause and fix results to findings.md
- [x] Update task status for review/commit readiness
- Status: completed

## Issue 31 Closeout Summary
- Closeout revalidation used ARM staging workdir `/root/work/frame-issue31-closeout-20260315`.
- Import path for staging verification:
  - `PYTHONPATH=scratch/lib.linux-aarch64-cpython-314:cinderx/PythonLib`
- Retained strategy:
  - exact `other` arg inference only on plain attr-read methods
  - specialized float-op guards disabled on helper-heavy no-backedge methods
- Verified balance:
  - issue31 plain attr gains still remain (`PointOther.dist` and the mixed probe both remain faster with `other` than with `rhs`)
  - raytrace's worst deopt offenders (`Vector.dot`, `Point.__sub__`, `Sphere.intersectionTime`) are no longer present in runtime deopt stats for the provided repro
- Deliberately out of scope for this closeout:
  - smaller residual deopts in `Vector.scale` and `addColours`
- Status:
  - issue31 is ready for review / merge as a closed fix

## Raytrace Follow-up: polymorphic method loads

### Goal
- Reduce the remaining raytrace deopts caused by over-eager `LOAD_ATTR_METHOD_WITH_VALUES` lowering on polymorphic method call sites after issue31 was closed.

### Result
- Current retained policy in `builder.cpp`:
  - keep the `LOAD_ATTR_METHOD_WITH_VALUES` fast path for:
    - receivers already known to have a stable exact type
    - true `self` receivers whose descriptor owner type has no subclasses
  - fall back to normal `LoadMethod` lowering for polymorphic unpacked locals such as raytrace's `o.intersectionTime(...)` and `s.colourAt(...)`
- New regression coverage:
  - `test_polymorphic_method_load_avoids_method_with_values_deopts`
- Remote ARM staging validation:
  - targeted tests:
    - `test_polymorphic_method_load_avoids_method_with_values_deopts`
    - `test_specialized_numeric_leaf_mixed_types_avoid_deopts`
    - `test_plain_instance_other_arg_guard_eliminates_cached_attr_loads`
    - `test_other_arg_inference_skips_helper_method_shapes`
  - result: `OK`
- Raytrace `compile_strategy=all` update:
  - previous median: `0.5452457539504394s`
  - current median: `0.5257585040526465s`
  - improvement: about `3.6%`
  - previous total deopts: `257510`
  - current total deopts: `130005`
  - removed deopt family:
    - `Scene.rayColour` `LOAD_ATTR_METHOD_WITH_VALUES`
    - `Scene._lightIsVisible` `LOAD_ATTR_METHOD_WITH_VALUES`
    - `SimpleSurface.colourAt` `LOAD_ATTR_METHOD_WITH_VALUES`
- Remaining follow-up after this round:
  - `Canvas.plot`
  - `Vector.scale`
  - `addColours`
  - `SimpleSurface.colourAt` instance-value path

## Raytrace Follow-up: mixed float guards and int clamp min/max

### Goal
- Reduce the next remaining raytrace deopt buckets after the polymorphic method-load fix:
  - `Vector.scale`
  - `addColours`
  - `Canvas.plot`

### Result
- Current retained policy:
  - for specialized numeric float guards on no-backedge code, keep them only for loop-hot code or issue31-style leaf methods with inferred exact non-self args
  - leave self-only helpers such as `Vector.scale()` and generic helpers such as `addColours()` on the generic path
  - leave obvious integer clamp shapes like `max(0, min(255, int(...)))` on the generic min/max path instead of forcing the float-specialized builtin lowering
- New regression coverage:
  - `test_self_only_float_leaf_mixed_factor_avoids_deopts`
  - `test_builtin_min_max_int_clamp_shape_avoids_float_guard_deopts`
- Remote ARM staging validation:
  - targeted tests:
    - `test_polymorphic_method_load_avoids_method_with_values_deopts`
    - `test_self_only_float_leaf_mixed_factor_avoids_deopts`
    - `test_builtin_min_max_int_clamp_shape_avoids_float_guard_deopts`
    - `test_specialized_numeric_leaf_mixed_types_avoid_deopts`
    - `test_plain_instance_other_arg_guard_eliminates_cached_attr_loads`
    - `test_other_arg_inference_skips_helper_method_shapes`
  - result: `OK`
- Raytrace `compile_strategy=all` update:
  - previous median: `0.5452457539504394s`
  - current median: `0.5367581009631976s`
  - previous total deopts: `257510`
  - current total deopts: `19285`
  - removed deopt families:
    - `Vector.scale`
    - `addColours`
    - `Canvas.plot`
- Remaining follow-up after this round:
  - `SimpleSurface.colourAt` `LOAD_ATTR_INSTANCE_VALUE`

### Discarded attempt
- A narrower `LOAD_ATTR_INSTANCE_VALUE` fallback for non-leaf `self` receivers was prototyped.
- It removed the remaining deopts but regressed raytrace wall time to about `1.92s`, so it was not kept.

## Issue 34: builtin `min/max` on two floats

### Goal
- Remove the generic `VectorCall` path for `min(a, b)` / `max(a, b)` when both arguments are exact floats.
- Preserve Python semantics for NaN handling, signed-zero ties, and result object identity.

### Analysis
- Direct lowering to `DoubleBinaryOp<Min/Max>` is not semantically safe for Python builtins:
  - `min/max` return one of the original operand objects, not a freshly boxed float.
  - NaN behavior is order-sensitive (`min(nan, 1.0)` differs from `min(1.0, nan)`).
  - Ties such as `0.0` vs `-0.0` preserve the first argument object.
- Safe specialization strategy:
  - keep the builtin `GuardIs`
  - guard both args to `FloatExact`
  - unbox to `CDouble`
  - compare `rhs < lhs` for `min` and `rhs > lhs` for `max`
  - branch/select between the original operand objects

### Verification
- Remote ARM editable rebuild on `/root/work/frame-stage-local`: completed
- Targeted tests:
  - `test_builtin_min_max_two_float_args_eliminate_vectorcall`: passed
  - `test_builtin_min_max_two_float_args_preserve_order_nan_and_identity`: passed
- Probe results (`N=2_000_000`):
  - `min_builtin`: `0.1626069820486009s`
  - `min_ternary`: `0.2111730769975111s`
  - `min_ratio`: `0.7700175815997482x`
  - `max_builtin`: `0.16318202891852707s`
  - `max_ternary`: `0.21114284498617053s`
  - `max_ratio`: `0.7728513316622934x`
- Optimized HIR evidence:
  - `VectorCall = 0`
  - `GuardType = 2`
  - `PrimitiveUnbox = 2`
  - `PrimitiveCompare = 1`
  - `CondBranch = 2`
  - `Phi = 1`

### Status
- Current local code for issue34 is ready for review/commit.

## Issue 33: builtin `abs` on float

### Goal
- Remove the generic `VectorCall` path for `abs(x)` when `x` is an exact float.
- Lower the hot path to a dedicated double abs opcode that can become ARM64 `FABS`.

### Analysis
- Unlike builtin `min/max`, `abs(float)` does not need to preserve operand object identity.
- The safe specialization strategy is:
  - keep the builtin `GuardIs`
  - guard the argument to `FloatExact`
  - `PrimitiveUnbox<CDouble>`
  - `DoubleAbs`
  - `PrimitiveBox<CDouble>`
- The repo does not have a generic `DoubleUnaryOp` hierarchy, so the minimal fit is a dedicated `DoubleAbs`, mirroring existing `DoubleSqrt`.

### Verification
- Remote ARM editable rebuild on `/root/work/frame-stage-local`: completed
- Targeted tests:
  - `test_builtin_abs_float_lowers_to_double_abs`: passed
  - `test_builtin_abs_float_preserves_nan_and_negative_zero`: passed
- Probe results (`N=2_000_000`):
  - `abs_builtin`: `0.7133366869529709s`
  - `abs_manual`: `0.649760145926848s`
  - `abs_ratio`: `1.0978461689666028x`
- Optimized HIR evidence:
  - `GuardIs = 1`
  - `GuardType = 1`
  - `PrimitiveUnbox = 1`
  - `DoubleAbs = 1`
  - `PrimitiveBox = 1`
  - `VectorCall = 0`

### Status
- Current local code for issue33 is ready for review/commit.

## Nqueens Optimization

### Goal
- Analyze current `pyperformance bm_nqueens` HIR/LIR bottlenecks on ARM.
- Identify the next highest-value optimization beyond the existing `set(genexpr)` work.
- Land the smallest safe improvement with remote-only verification and record the result in `findings.md`.

### Workflow
- Brainstorming:
  - capture current benchmark timing, compiled functions, deopts, and opcode mix
  - compare hotspot HIR/LIR against already optimized `set(genexpr)`-style shapes
- Writing plans:
  - keep the active checklist and decisions in this file
- TDD:
  - add a targeted runtime regression that proves the new lowering/optimization fires
- Verification before completion:
  - rebuild and benchmark only through the remote ARM entrypoint
  - record key HIR/LIR evidence and timing deltas in `findings.md`

### Current status
- [x] Capture current remote `bm_nqueens` baseline and hotspot functions
- [x] Inspect hotspot HIR/LIR and rank optimization opportunities
- [~] Implement the best narrow optimization
- [ ] Add a targeted regression test
- [ ] Rebuild and validate remotely
- [x] Record current evidence in `findings.md`

### Current findings
- Stable latest-code remote baseline (`/root/work/cinderx-nqueens-head`):
  - `compile_strategy=all`: median `1.1747283110162243s`
  - `compile_strategy=none`: median `1.389004991040565s`
  - no runtime deopts
- Current optimized `n_queens` already benefits from the earlier `set(genexpr)` work:
  - `MakeSet = 2`
  - `SetSetItem = 2`
  - no generator-object call chain on the two `set(...)` diagonals
- The remaining dominant hotspot is `bm_nqueens_run:permutations`:
  - `VectorCall = 7`
  - `CallMethod = 2`
  - `MakeFunction = 2`
  - `BuildSlice = 2`
  - `ListSlice = 4`
- Most important residual shape:
  - the two `tuple(pool[i] for i in indices[:r])` sites
  - on Python 3.14 these are already bytecode-optimized into:
    - `BUILD_LIST`
    - `MAKE_FUNCTION`
    - `CALL 0` to create the genexpr generator object
    - outer `FOR_ITER + LIST_APPEND`
    - `CALL_INTRINSIC_1(INTRINSIC_LIST_TO_TUPLE)`
  - so the remaining waste is generator-object creation, not the outer tuple call itself

### Prototype result
- Tried a builder-time rewrite to inline the compiler-optimized `tuple(genexpr)` path.
- Conclusion:
  - this is still the best expected next optimization for `nqueens`
  - but the straightforward prototype is not yet safe enough to land because it needs a cross-basic-block rewrite of the `CALL 0 -> FOR_ITER -> LIST_APPEND -> LIST_TO_TUPLE` pattern
  - on Python 3.14, the compiler emits both:
    - an exact-builtin fast path for `tuple`
    - a fallback generic call path if builtin identity does not hold
  - current HIR counts therefore mix executed fast-path ops with dormant fallback-path ops
  - more importantly, the `CALL 0` that creates the genexpr object and the following `FOR_ITER` live in different bytecode blocks, so the old `set(genexpr)` same-block rewrite structure does not apply
  - current local worktree has been restored to stable `HEAD`; no unverified nqueens optimization code is kept
