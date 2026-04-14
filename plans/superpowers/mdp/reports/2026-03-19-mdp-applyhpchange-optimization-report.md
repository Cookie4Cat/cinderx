# MDP applyHPChange 优化报告

本报告记录 `bm_mdp.applyHPChange` 的第一轮真实优化、HIR 前后对比与本地近似收益。

## 1. `applyHPChange` 整数 clamp 路径

本轮实现：

- 在 `cinderx/Jit/hir/simplify.cpp` 中新增实验开关 `PYTHONJIT_ARM_MDP_INT_CLAMP_MIN_MAX`
- 仅对 `bm_mdp.applyHPChange` 中的二参 `min/max` 专门化改走整数 clamp 路径
- 新增回归测试 `cinderx/PythonLib/test_cinderx/test_jit_mdp_experiments.py`，比较 baseline 与开关开启后的 HIR / deopt 差异

### 1.1 优化前后 HIR 对比

优化前关键片段：

```text
fun bm_mdp:applyHPChange {
  ...
  v35:OptObject = LoadGlobalCached<3; "max">
  ...
  v38:ImmortalLongExact[0] = LoadConst<ImmortalLongExact[0]>
  ...
  v54:Bottom = GuardType<FloatExact> v38 {
    ...
  }
  Unreachable
}
```

优化后关键片段：

```text
fun bm_mdp:applyHPChange {
  ...
  v54:LongExact = GuardType<LongExact> v40 {
    ...
  }
  v56:CBool = CompareBool<GreaterThan> v54 v38 {
    ...
  }
  ...
  v58:LongExact = GuardType<LongExact> v49 {
    ...
  }
  v60:CBool = CompareBool<LessThan> v57 v58 {
    ...
  }
}
```

结论：

- 优化前 HIR 在 `max(0, hstate.hp + change)` 这一段把整数 `0` 错误推向了 `FloatExact` 守卫，直接形成 `Unreachable`
- 优化后 HIR 改为整数 `GuardType<LongExact> + CompareBool` 形状，不再出现该 `FloatExact` 守卫失败路径

### 1.2 本地近似验证

`applyHPChange` 单点回归测试：

- baseline: `GuardType = 1`，`CompareBool = 0`，`deopt = 20000`
- 优化后: `GuardType = 2`，`CompareBool = 2`，`deopt = 0`

`mdp` 热点白名单近似跑分：

- 仅编译 `applyHPChange,getCritDist` 时，`median_wall_sec` 从 `1.112593s` 降到 `1.106793s`，提升约 `0.52%`
- 同时 `total_deopt_count` 从 `183909` 降到 `20619`，下降约 `88.79%`

- 编译 `Battle.evaluate,Battle.getSuccessors,Battle._getSuccessorsB,getCritDist,topoSort,applyHPChange` 时，`median_wall_sec` 从 `1.112126s` 降到 `1.104848s`，提升约 `0.65%`
- 同时 `total_deopt_count` 从 `188730` 降到 `25440`，下降约 `86.52%`

判断：

- 这轮优化已经证明 `applyHPChange` 的劣化点判断是正确的
- 但总收益仍然有限，说明 `applyHPChange` 只是高频异常点，不是唯一主瓶颈
- 下一轮最应该继续打的是 `getCritDist`
