# Notes: Issue 60 go method-with-values fast path regression

## Problem summary
- `8a8da7f` 删除了旧逻辑：
  - `receiverIsNamedSelfArg()`
  - `methodDescrOwnerHasNoSubclasses()`
- 改成：
  - `canUseMethodWithValuesFastPath() == hasStableExactReceiverType(receiver)`

## Immediate consequence
- 好处：
  - polymorphic virtual-call receiver 不再被错误地单态化成
    `LOAD_ATTR_METHOD_WITH_VALUES`
- 坏处：
  - attr-derived receiver 即使运行时单态，只要 HIR 类型不精确，就完全进不了
    fast path，`go` 明显回退

## Existing useful regressions
- `test_polymorphic_virtual_method_avoids_method_with_values_guard_deopts`
- `test_polymorphic_method_load_avoids_method_with_values_deopts`
- `test_polymorphic_loop_local_method_load_avoids_method_with_values_deopts`

## Constraints discovered
- 解释器 `LOAD_ATTR_METHOD_WITH_VALUES` cache 目前只暴露：
  - type version
  - keys version
  - cached descr
- 没有现成的 per-site multi-type histogram 直接给 builder 用
- `LoadMethodCache` 自身有 `FixedTypeProfiler<4>`，但那是 JIT 运行时 cache，
  不是 builder 在初次编译时天然就能读到的输入

## Practical implication
- 完整的“基于 inline cache type profile 驱动 builder 决策”需要额外 plumbing
- 本轮更现实的目标：
  - 先做一个窄且有测试保护的过渡修复，恢复 `go` 所需的单态 attr-derived
    receiver fast path
  - 同时用已有 polymorphic 回归测试守住 `raytrace` 类场景

## What the experiments showed
- `attr-derived + owner-has-no-subclasses` 仍然过宽
  - polymorphic field values can still trigger method-with-values deopts
- `recursive same-method only` is much safer
  - it restores the exact `Square.find -> reference.find` hotspot
  - but broader pyperformance sampling still shows suspicious regressions

## Updated local conclusion
- The issue-specific diagnosis is correct
- A narrow heuristic can recover the target path
- But the branch is not ready to land until the broader regressions are either
  eliminated or convincingly explained away

## Hybrid attempt note
- I also tried a call-site hybrid lowering that uses the existing
  `LOAD_ATTR_METHOD_WITH_VALUES` interpreter specialization as a profile signal
  and falls back to generic `CallMethod` on guard miss.
- That version still failed to recover an actual `VectorCall` / inliner-visible
  call on the `Square.find` regression, so it is not yet the real fix.
