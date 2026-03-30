# [arm-opt][pyformance] go: recover monomorphic attr-derived method-with-values fast path (#60)

## Proposal

- Case: `go`
- Symptom: `8a8da7f` 将 method-with-values fast path 收窄到 exact receiver 后，
  `go` 中 attr-derived 但运行时单态的 receiver 无法再进入 fast path，导致
  inlining 消失并显著回退
- Primary hypothesis:
  - 当前 gate 过于保守
  - 需要恢复一条更窄的非-exact receiver 允许路径，至少覆盖
    `self.reference.find(update)` 这类 attr-derived monomorphic receiver
- Planned order: `HIR -> LIR -> codegen`
- Validation:
  - targeted attr-derived receiver regression
  - existing polymorphic regressions
  - ARM `go` / `raytrace` / `deltablue` direct validation
  - requested benchmark subset smoke
- Exit criteria:
  - `go` 恢复
  - polymorphic method-load regressions 仍然为 0
  - requested subset 没有明显大回退

## Current IR

- Before `8a8da7f`:
  - monomorphic attr-derived receiver could lower to const descr + fastcall
  - inliner could see resulting `VectorCall`
- After `8a8da7f`:
  - non-exact receiver falls back to `LoadMethodCached + CallMethod`
  - inliner sees nothing

## Target HIR

- Desired shape on the `go` reproducer:
  - no generic `LoadMethodCached + CallMethod` on the hot `find` call
  - ideally const descr / fastcall and at least one inlined callee

## Repeat-error prevention

- Keep the existing polymorphic method-load regressions green
- Do not remove the issue44 protections blindly
- If the fast path is reopened, tie it to a narrower receiver origin than the old
  owner-has-no-subclasses heuristic

## Implemented fix

- Builder:
  - keep exact-receiver `LOAD_ATTR_METHOD_WITH_VALUES` lowering unchanged
  - for non-exact receivers, carry the interpreter specialization cache
    (`descr`, `type_version`, `keys_version`) forward to the following call
  - only do this in the outer function body (`tc.frame.parent == nullptr`)
- Call site:
  - emit a profiled fast branch guarded by:
    - receiver `tp_version_tag`
    - split-dict `inline_values.valid`
    - heap-type `dk_version`
  - fast branch:
    - const-descr `VectorCall`
    - one recovered HIR inline on the outer attr-derived recursive call
  - fallback branch:
    - generic `CallMethod`
- Safety fix:
  - generated fast/fallback call blocks now start with `Snapshot`
  - this is required because, after the HIR inliner expands the fast-path call
    into `LoadField + GuardIs + BeginInlinedFunction`, `bindGuards()` must see
    a dominating snapshot in the same block

## Validation

- ARM targeted regressions:
  - `test_attr_derived_monomorphic_method_load_restores_inlining`: `OK`
  - `test_attr_derived_polymorphic_method_load_avoids_method_with_values_deopts`: `OK`
  - `test_polymorphic_virtual_method_avoids_method_with_values_guard_deopts`: `OK`
  - `test_polymorphic_method_load_avoids_method_with_values_deopts`: `OK`
  - `test_polymorphic_loop_local_method_load_avoids_method_with_values_deopts`: `OK`
- Direct issue-specific probes with HIR inliner enabled:
  - `Square.find` chain:
    - new: `0.001345984s`
    - base: `0.001318382s`
  - `bm_go.versus_cpu()`:
    - new: `1.693260981s`
    - base: `1.744004352s`
    - about `-2.91%`
- Direct pyperformance `--debug-single-value` with HIR inliner enabled:
  - `go`: `127 ms -> 127 ms`
  - `raytrace`: `357 ms -> 356 ms`
  - `deltablue`: `3.74 ms -> 3.76 ms`
- Requested subset smoke with HIR inliner enabled:
  - `generators,coroutines,comprehensions,richards,richards_super,float,go,`
    `deltablue,raytrace,nqueens,nbody,unpack_sequence,fannkuch,coverage,`
    `scimark,spectral_norm,chaos,logging`
  - completed with no `Benchmark died`
