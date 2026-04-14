# Notes: issue31 raytrace regression closeout 2026-03-15

## Root cause

- The regression came from combining issue31's exact-instance attr path with specialized float guards on helper-heavy no-backedge raytrace methods.
- Methods such as `Point.__sub__(self, other)` and `Vector.dot(self, other)` see mixed receiver and mixed numeric shapes, so exact `other` inference plus downstream float guards was unsafe on the hot raytrace helpers.

## Retained policy

- infer exact type for non-self arg `other` only when that arg is used exclusively for plain attr reads
- keep aggressive split-dict pure-load lowering only for functions marked safe by preloader metadata
- keep specialized numeric exact guards for loop-hot code, but not for helper-heavy no-backedge raytrace shapes

## Closeout revalidation

- ARM staging workdir: `/root/work/frame-issue31-closeout-20260315`
- Import path:
  - `PYTHONPATH=scratch/lib.linux-aarch64-cpython-314:cinderx/PythonLib`
- Targeted tests passed:
  - `ArmRuntimeTests.test_specialized_numeric_leaf_mixed_types_avoid_deopts`
  - `ArmRuntimeTests.test_plain_instance_other_arg_guard_eliminates_cached_attr_loads`
  - `ArmRuntimeTests.test_other_arg_inference_skips_helper_method_shapes`
- A/B probes still favor `other`:
  - `PointOther.dist` median: `0.295552274096s`
  - `PointRhs.dist` median: `0.315386445029s`
  - `PointOther` mixed median: `0.246739777969s`
  - `PointRhs` mixed median: `0.276117506088s`
- Raytrace compile-all revalidation:
  - median wall: `0.5452457539504394s`
  - `Vector.dot`, `Point.__sub__`, `Sphere.intersectionTime`: `0`
  - remaining follow-ups: `Vector.scale`, `addColours`

## Follow-up kept out of issue31

- residual mixed numeric deopts in `Vector.scale` and `addColours`
- separate non-issue31 top deopts in `Scene.rayColour`, `Scene._lightIsVisible`, `Canvas.plot`, and `SimpleSurface.colourAt`

## 2026-03-15 raytrace follow-up: polymorphic method-with-values narrowing

### Problem
- After issue31 closeout, raytrace still had a large non-issue31 deopt bucket from `LOAD_ATTR_METHOD_WITH_VALUES`.
- The hottest remaining sites were:
  - `Scene.rayColour` line `272`
  - `Scene._lightIsVisible` line `284`
  - `SimpleSurface.colourAt` line `316`
- Those sites are polymorphic method loads such as:
  - `s.colourAt(...)`
  - `o.normalAt(...)`
  - `o.intersectionTime(...)`

### Retained heuristic
- keep `LOAD_ATTR_METHOD_WITH_VALUES` lowering when:
  - receiver already has a stable exact type, or
  - receiver is the real `self` arg and the descriptor owner type has no subclasses
- otherwise fall back to normal `LoadMethod` lowering

### Why this shape
- The first broader fallback removed the method-load deopts but cost too much throughput because it also disabled useful monomorphic self-call sites.
- Restricting the retained fast path to exact receivers or leaf-owner `self` calls preserved the good monomorphic cases while still removing the polymorphic raytrace call-site deopts.

### Remote result
- ARM staging workdir:
  - `/root/work/frame-issue31-closeout-20260315`
- Targeted regressions:
  - `test_polymorphic_method_load_avoids_method_with_values_deopts`
  - the three issue31 guards
  - all passed
- Raytrace direct benchmark (`compile_strategy=all`, `prewarm_runs=1`, `samples=5`):
  - previous median: `0.5452457539504394s`
  - current median: `0.5257585040526465s`
  - previous total deopts: `257510`
  - current total deopts: `130005`
- Removed top deopts:
  - `Scene.rayColour` `LOAD_ATTR_METHOD_WITH_VALUES`
  - `Scene._lightIsVisible` `LOAD_ATTR_METHOD_WITH_VALUES`
  - `SimpleSurface.colourAt` `LOAD_ATTR_METHOD_WITH_VALUES`
- Remaining next targets:
  - `Canvas.plot`
  - `Vector.scale`
  - `addColours`
  - `SimpleSurface.colourAt` `LOAD_ATTR_INSTANCE_VALUE`

## 2026-03-15 raytrace follow-up: narrow no-backedge float guards and int clamp min/max

### Problem
- After the polymorphic method-load fix, the next top deopts were:
  - `Canvas.plot` line `202`
  - `Vector.scale` line `49`
  - `addColours` line `299`
- `Canvas.plot` HIR showed `min/max` float specialization trying to guard exact ints like `255` as `FloatExact`.
- `Vector.scale` and `addColours` were still keeping no-backedge float exact guards even though they are not issue31-style `self`/`other` leaf methods.

### Retained heuristic
- specialized numeric float guards on no-backedge code stay enabled only when a stable exact non-self arg type was inferred
- integer clamp shapes with a known exact long operand do not use the float-specialized builtin `min/max` path

### Remote result
- ARM staging workdir:
  - `/root/work/frame-issue31-closeout-20260315`
- Targeted regressions:
  - `test_self_only_float_leaf_mixed_factor_avoids_deopts`
  - `test_builtin_min_max_int_clamp_shape_avoids_float_guard_deopts`
  - the existing method-load and issue31 guards
  - all passed
- Raytrace direct benchmark (`compile_strategy=all`, `prewarm_runs=1`, `samples=5`):
  - previous median: `0.5452457539504394s`
  - current median: `0.5367581009631976s`
  - previous total deopts: `257510`
  - current total deopts: `19285`
- Removed top deopts:
  - `Canvas.plot`
  - `Vector.scale`
  - `addColours`
- Remaining next target:
  - `SimpleSurface.colourAt` `LOAD_ATTR_INSTANCE_VALUE`

### Discarded attempt
- I also tried disabling `LOAD_ATTR_INSTANCE_VALUE` for non-leaf `self` receivers.
- That did remove the last deopt bucket, but raytrace regressed to about `1.92s`, so that change was discarded.

## 2026-03-15 nqueens analysis

### Stable remote baseline
- Workdir: `/root/work/cinderx-nqueens-head`
- Built from local `HEAD` `4d1c7c778f0dd57d75814246c11fccc7d8c67440` through the remote helper script.
- Direct `bench_pyperf_direct.py` results on `bm_nqueens:bench_n_queens(8)`:
  - `compile_strategy=all`: median `1.1747283110162243s`
  - `compile_strategy=none`: median `1.389004991040565s`
  - no runtime deopts

### Current hotspot split
- `n_queens` itself is no longer the main problem.
- Current `n_queens` final HIR already has:
  - `MakeSet = 2`
  - `SetSetItem = 2`
  - `CallMethod = 2`
  - `VectorCall = 2`
- The larger remaining cost sits in `permutations`:
  - `VectorCall = 7`
  - `CallMethod = 2`
  - `MakeFunction = 2`
  - `BuildSlice = 2`
  - `ListSlice = 4`

### Key remaining shape
- In Python 3.14, `tuple(genexpr)` is already compiler-optimized at bytecode level.
- The optimized bytecode shape is:
  - `BUILD_LIST`
  - `MAKE_FUNCTION`
  - `CALL 0` to create the generator object
  - `FOR_ITER + LIST_APPEND`
  - `CALL_INTRINSIC_1(INTRINSIC_LIST_TO_TUPLE)`
- So the real residual overhead is not the outer tuple call.
- The remaining waste is:
  - generator-function allocation (`MakeFunction`)
  - generator-object creation (`CallMethod/Call 0`)

### Best next optimization candidate
- A cross-basic-block builder rewrite for the compiler-optimized tuple-genexpr path:
  - consume `CALL 0 -> FOR_ITER -> LIST_APPEND -> LIST_TO_TUPLE`
  - inline the genexpr body directly into the outer list collector loop
  - avoid generator-object creation entirely

### Smaller helper route check
- Investigated whether we could get a cheaper intermediate win by only removing:
  - `MakeFunction`
  - `CallMethod` / generator-function call dispatch
- Current runtime support does not make this especially cheap:
  - frame/generator initialization paths still depend on `PyFunctionObject*`
  - `jitFrameInit()` and `JITRT_InitFrameCellVars()` both expect a real function object
  - so a helper that still needs to manufacture a function object would not remove the main allocation cost
- Conclusion:
  - the "small helper" route is lower value than it first looked
  - the real high-value path is still full tuple-genexpr lowering across blocks

### Prototype status
- A first tuple-genexpr builder prototype was explored.
- It can be made to match the residual `permutations` shape, but it is not ready to keep:
  - same-block `CALL 1` consumer matching is insufficient
  - the real tuple path spans multiple bytecode blocks
  - on 3.14 the compiler already emits an exact-builtin fast path:
    - `LOAD_GLOBAL tuple`
    - builtin identity check
    - `BUILD_LIST`
    - `CALL 0`
    - `FOR_ITER + LIST_APPEND`
    - `CALL_INTRINSIC_1(INTRINSIC_LIST_TO_TUPLE)`
  - and also a fallback generic path for shadowed `tuple`
  - so raw HIR opcode counts overstate the executed-path overhead unless we separate fast path from fallback path
  - a naive rewrite destabilized CFG/stack handling
- Current local worktree has been restored to stable `HEAD` after the experiment.
