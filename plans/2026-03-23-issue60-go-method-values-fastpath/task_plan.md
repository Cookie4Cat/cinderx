# Task Plan: Issue 60 go method-with-values fast path regression

## Goal
修复 `8a8da7f` 将 `canUseMethodWithValuesFastPath()` 收窄为“仅 exact receiver”
之后引入的 `go` 回退，同时保持 `raytrace` / polymorphic method receiver
场景不再退回到高频 `LOAD_ATTR_METHOD_WITH_VALUES` deopt。

## Workflow
1. Brainstorming
2. Writing-Plans
3. Test-Driven-Development
4. Verification-Before-Completion

## Remote Test Entry
- 统一远端入口：`scripts/arm/remote_update_build_test.sh`
- Scheduler DB：`plans/remote-scheduler.sqlite3`
- ARM host：`124.70.162.35`
- x86 host：`106.14.164.133`

## Brainstorming
- 当前 gate：
  - `hasStableExactReceiverType(receiver)` 才允许 `LOAD_ATTR_METHOD_WITH_VALUES`
    走 const-descr + fastcall 路径
- 已知负面影响：
  - `go` 中 `self.reference.find(update)` 的 receiver 来自属性加载
  - 运行时单态，但 HIR 类型不精确，导致 fast path / inlining 全部丢失
- 已知正面信号：
  - 这个收窄修掉了 polymorphic `self.fn(...)` / `o.intersectionTime(...)`
    一类错误单态化和 deopt 风暴
- 当前最可能可落地的修复分两档：
  1. 直接接 profile：
     - 若 builder 阶段能读到足够的 per-site receiver profile，就按 monomorphic /
       polymorphic 做 gate
  2. 过渡方案：
     - 如果 builder 暂时拿不到 profile，就恢复一条更窄的非-exact receiver
       允许条件，只覆盖 `go` 这类 attr-derived monomorphic receiver，
       同时保留现有 polymorphic 回归测试

## TDD plan
- 先补一个 attr-derived monomorphic receiver regression：
  - 形如 `self.reference.find(update)`
  - 期望：
    - caller 有 `num_inlined_functions >= 1`
    - 或至少不再退化为 `LoadMethodCached + CallMethod`
- 保留并重跑已有 polymorphic 回归：
  - `test_polymorphic_virtual_method_avoids_method_with_values_guard_deopts`
  - `test_polymorphic_method_load_avoids_method_with_values_deopts`
  - `test_polymorphic_loop_local_method_load_avoids_method_with_values_deopts`

## Verification plan
- ARM targeted tests via remote entry
- ARM direct benchmark focus：
  - `go`
  - `raytrace`
  - `deltablue`
- ARM requested subset smoke：
  - `generators,coroutines,comprehensions,richards,richards_super,float,go,`
    `deltablue,raytrace,nqueens,nbody,unpack_sequence,fannkuch,coverage,`
    `scimark,spectral_norm,chaos,logging`
- 关键结果写入 `findings.md`

## Status
- [completed] Brainstorming
- [completed] Writing-Plans
- [completed] Test-Driven-Development
- [completed] Verification-Before-Completion

## Outcome
- Current heuristic prototypes are not safe to land.
- The best tested variant recovers the issue-specific `Square.find` hot path,
  but the requested broader regression sweep still contains too many suspicious
  regressions.

## 2026-03-23 Final Status

- [completed] Brainstorming
- [completed] Writing-Plans
- [completed] Test-Driven-Development
- [completed] Verification-Before-Completion

## Final Outcome

- Replaced the earlier static heuristic direction with a true call-site
  profile-driven gate based on the interpreter's
  `LOAD_ATTR_METHOD_WITH_VALUES` specialization cache.
- The landed shape is:
  - outer non-exact monomorphic attr-derived receiver:
    - profiled fast branch -> const-descr `VectorCall` -> one recovered inline
  - generic fallback branch:
    - `LoadMethodCached + CallMethod`
  - already-inlined callees:
    - stay on generic method load/call to avoid nested unsafe shapes
- Critical correctness fix:
  - generated fast/fallback call blocks now emit a leading `Snapshot`
  - this prevents `bindGuards()` from seeing a null dominating snapshot after
    the HIR inliner expands the fast-path call into `GuardIs +
    BeginInlinedFunction`
- Verification summary:
  - 5 targeted ARM regressions: all `OK`
  - direct `go / raytrace / deltablue` check with HIR inliner:
    - `go`: flat at coarse pyperformance granularity and improved on the
      issue-specific direct probe
    - `raytrace`: effectively flat
    - `deltablue`: effectively flat
  - requested benchmark subset smoke with HIR inliner:
    - completed with no `Benchmark died`
