# MDP getCritDist 优化报告

本报告记录 `bm_mdp.getCritDist` 的第二轮真实优化、HIR 前后对比与本地近似收益。

## 1. `getCritDist` 的 `Fraction min` 路径

本轮实现：

- 在 `cinderx/Jit/hir/simplify.cpp` 中新增实验开关 `PYTHONJIT_ARM_MDP_FRACTION_MIN_COMPARE`
- 仅对 `bm_mdp.getCritDist` 中的 `min(p, Fraction(1))` 走 compare-select 路径，避免错误落入 float `min` 专门化
- 回归测试继续放在 `cinderx/PythonLib/test_cinderx/test_jit_mdp_experiments.py`

### 1.1 优化前后 HIR 对比

优化前关键片段：

```text
fun bm_mdp:getCritDist {
  ...
  v307:Object = VectorCall<1> v108 v110 {
    ...
  }
  v315:FloatExact = GuardType<FloatExact> v77 {
    ...
  }
  v316:FloatExact = GuardType<FloatExact> v307 {
    ...
  }
  v319:CBool = PrimitiveCompare<LessThanUnsigned> v318 v317
}
```

优化后关键片段：

```text
fun bm_mdp:getCritDist {
  ...
  v307:Object = VectorCall<1> v108 v110 {
    ...
  }
  v316:CBool = CompareBool<LessThan> v307 v77 {
    ...
  }
}
```

结论：

- 优化前 `Fraction(1)` 的结果和参数 `p` 被错误推向 `FloatExact` 守卫
- 优化后这段直接改为对象级 `CompareBool<LessThan>` 选择路径，相关 `FloatExact` 守卫消失

### 1.2 本地近似验证

`getCritDist` 单点回归测试：

- baseline: `GuardType = 3`，`CompareBool = 0`，`deopt = 5000`
- 优化后: `GuardType = 1`，`CompareBool = 1`，`deopt = 0`

两轮实验都开启后的 `mdp` 热点白名单近似跑分：

- 仅编译 `applyHPChange,getCritDist` 时，`median_wall_sec` 从 `1.112593s` 降到 `1.076996s`，总提升约 `3.20%`
- 同时 `total_deopt_count` 从 `183909` 降到 `9642`，下降约 `94.76%`

- 编译 `Battle.evaluate,Battle.getSuccessors,Battle._getSuccessorsB,getCritDist,topoSort,applyHPChange` 时，`median_wall_sec` 从 `1.112126s` 降到 `1.030816s`，总提升约 `7.31%`
- 同时 `total_deopt_count` 从 `188730` 降到 `14463`，下降约 `92.34%`

判断：

- 第二轮优化比第一轮更接近 `mdp` 的主差距来源
- 当前本地近似剩余头部问题已经明显转向 `Battle.getSuccessors`
- 下一轮如果继续做，应优先检查 `Battle.getSuccessors` 的 `BinaryOp / UnhandledException` 路径
