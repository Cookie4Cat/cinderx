# Plan: Analyze Why CPython JIT Beats CinderX JIT on raytrace

## Goal
- Explain why `raytrace` performs much better on CPython's built-in JIT than on CinderX JIT.
- Separate measurement-path effects from steady-state throughput.
- Use the remote ARM entrypoint `root@124.70.162.35` for any benchmark or verification runs.
- Record key evidence in `findings.md`.

## Current facts
- Existing remote direct-run artifacts already show this is a steady-state problem:
  - `cinderx_hot_direct`: median about `2.33s`
  - `cinderx_interp_direct`: median about `1.74s`
  - `cpython_ownjit_direct`: median about `0.686s`
- Therefore:
  - CinderX JIT is slower than its own interpreter on this workload.
  - The gap vs CPython JIT is not explained by pyperformance worker startup cost alone.

## Hypotheses
1. CinderX is compiling many `raytrace` methods, but they remain helper-heavy and boxed on the hot path.
2. Repeated guards or deopts may still be forcing execution off the compiled path in key methods.
3. The benchmark is dominated by object-method/float-heavy code where CPython JIT has a cleaner specialized path.

## Steps
1. Inspect existing remote direct-run artifacts and benchmark source.
2. Re-run a targeted remote `raytrace` sample with CinderX runtime stats and HIR dumps for key methods.
3. Identify the hottest methods and compare their compiled shapes to what the benchmark is structurally doing.
4. Summarize the likely reasons CPython JIT wins and capture evidence in `findings.md`.

## Findings
- This is not mainly a pyperformance startup artifact.
  - Existing direct-run medians on the remote host already show:
    - `cinderx_hot`: about `2.33s`
    - `cinderx_interp`: about `1.74s`
    - `cpython_jit`: about `0.686s`
- CPython also starts from a much faster non-CinderX baseline.
  - Remote direct-run `cpython interp` is about `0.898s`.
  - So even before JIT wins, CinderX is already behind.
- CinderX is overcompiling this benchmark.
  - Existing CinderX direct artifact compiled `58` functions.
  - Remote CPython JIT probing after one run found only `3` valid executors:
    - `Scene.rayColour`
    - `firstIntersection` at two backedges
  - `Vector.dot` and `Vector.scale` have no CPython executors at all.
- The worst CinderX regression is not just "generic code", but massive deopt churn in tiny leaf methods.
  - `compile_immediately` scenario:
    - `Vector.dot`: `489869` + `10001` + `10000` guard failures
    - `Vector.scale`: `144410` + `5333` guard failures
  - `warm_then_compile` scenario:
    - `Vector.dot`: `369869` + `60000` + `60000` + `20002`
    - `Point.__sub__`: `202531`
    - `Sphere.intersectionTime`: `153526`
- The runtime shapes are heavily mixed `int`/`float`, and CinderX specializes these methods too narrowly.
  - `Vector.scale` argument/type distribution in one run:
    - mostly `factor=float`, `self.{x,y,z}=float`
    - but also `factor=int` for a non-trivial tail
  - `Vector.dot` sees multiple coordinate-type mixes:
    - all-float
    - float/float with `z` still int
    - int/float mixes
- HIR evidence shows wrong or partial specialization.
  - `Vector.dot` compiled immediately into all-`LongExact` guards and `LongBinaryOp`.
  - After one warmup run it improves only partially:
    - `x`/`y` become `FloatExact` + `DoubleBinaryOp`
    - `z` still stays on `LongExact` + `LongBinaryOp`
  - `Sphere.intersectionTime` after warmup still mixes:
    - `DoubleBinaryOp`
    - `LongBinaryOp`
    - generic `BinaryOp`
    - `PrimitiveBox` / `PrimitiveUnbox`
- Compiling less helps a lot.
  - Forcing only `Scene.rayColour` gave about `1.495s` with no deopts.
  - That is much better than compile-all CinderX JIT, but still far slower than CPython JIT.

## Conclusion
- CPython JIT wins on `raytrace` for three stacked reasons:
  1. CPython's non-CinderX baseline is already much faster.
  2. CPython JIT compiles a small number of real backedge-hot regions instead of eagerly compiling dozens of tiny helper methods.
  3. CinderX JIT currently over-specializes mixed numeric leaf methods like `Vector.dot`, `Vector.scale`, `Point.__sub__`, and `Sphere.intersectionTime`, causing large GuardType deopt storms and leaving partially boxed/generic arithmetic even after warmup.

## Status
- [x] Inspect artifacts and source
- [x] Remote targeted runs
- [x] Hotspot and HIR analysis
- [x] Compile-granularity prototype
- [x] Ready to summarize and write findings

## Prototype
- Added script:
  - `scripts/arm/bench_pyperf_direct.py`
- Purpose:
  - direct-run a pyperformance benchmark module under selectable CinderX compile strategies:
    - `none`
    - `all`
    - `backedge`
    - `names`

## Prototype results on raytrace
- `compile_strategy=all`
  - before removing numeric exact guards: median about `1.80s`
  - after removing numeric exact guards: median about `1.29s`
  - after removing numeric exact guards: total deopts `0`
- `compile_strategy=backedge`
  - before removing numeric exact guards: median about `1.31s`
  - after removing numeric exact guards: median about `1.56s`
  - after removing numeric exact guards: total deopts `0`
- `compile_strategy=names` with `Scene.rayColour`
  - median about `1.14s`
  - total deopts about `524,282`
- Interpretation:
  - narrowing compile scope is a strong mitigation
  - the specialized numeric exact-guard policy is a separate major cause
  - once those guards are removed, `compile_all` becomes better than `none`
  - but CinderX still remains slower than CPython JIT because the leaf math falls back to generic `BinaryOp` object paths

## Guard-source confirmation
- Confirmed on remote:
  - `Vector.dot` initial HIR previously contained direct `GuardType<LongExact>` before each `BinaryOp`
  - after hard-disabling specialized numeric exact-guard insertion in `builder.cpp`, those guards disappeared from both initial and optimized HIR

## Remaining gap
- With numeric guard deopts removed:
  - `compile_strategy=all`: about `1.29s` in the hard-disable prototype
  - `compile_strategy=all` + `prewarm_runs=1`: about `1.18s` in the hard-disable prototype
  - remaining deopt after warmup+compile-all:
    - `SimpleSurface.colourAt` line 316, `LOAD_ATTR_INSTANCE_VALUE`, count `19285`
- This leaves a clear next target:
  - mixed-numeric fast paths for generic `BinaryOp` leaf math
  - and possibly reducing `LOAD_ATTR_INSTANCE_VALUE` instability in `SimpleSurface.colourAt`

## Final prototype choice
- Keep a narrower policy in `builder.cpp`:
  - for specialized numeric binary/compare opcodes, emit exact int/float guards only when the current code object has a backedge
  - for no-backedge leaf helpers, skip those exact guards
- Reason:
  - this preserves loop-oriented specialization
  - it avoids the raytrace-style mixed numeric deopt storm in tiny helpers

## Final remote results with the narrowed policy
- Minimal mixed-numeric leaf regression:
  - int-seeded `dot(a, b)` then float-heavy calls
  - deopts for `dot`: `[]`
- `raytrace` direct runs:
  - `compile_strategy=all`: median about `0.569s`, deopts `0`
  - `compile_strategy=backedge`: median about `0.662s`, deopts `0`
  - `compile_strategy=none`: median about `0.603s`, deopts `0`
- Interpretation:
  - this narrowed policy removes the catastrophic mixed-type deopt behavior
  - on raytrace it is enough to move CinderX JIT ahead of the previously measured CPython JIT median (`~0.686s`)

## Final validated shape
- Final retained policy:
  - keep specialized-opcode exact int guards only for code objects with a backedge
  - keep float specialized-opcode guards enabled
- Reason:
  - broad numeric-guard removal fixed raytrace but regressed existing float HIR tests
  - the int-only no-backedge policy preserves those tests while still fixing raytrace

## Final validation
- New targeted regression:
  - `ArmRuntimeTests.test_specialized_numeric_leaf_mixed_types_avoid_deopts`
  - pass
- Existing float-path regressions re-run and pass:
  - `test_float_add_sub_mul_lower_to_double_binary_op_in_final_hir`
  - `test_math_sqrt_cdouble_lowers_to_double_sqrt`
  - `test_primitive_unbox_cse_for_float_add_self`
  - `test_primitive_box_remat_elides_frame_state_only_boxes`
- Full remote file:
  - `python cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
  - `Ran 24 tests ... OK`

## Final raytrace numbers
- `compile_strategy=all`, `samples=5`:
  - median about `0.5742s`
  - `total_deopt_count = 0`
- This remains ahead of the previously recorded CPython JIT median (`~0.6861s`) for the same benchmark family.
