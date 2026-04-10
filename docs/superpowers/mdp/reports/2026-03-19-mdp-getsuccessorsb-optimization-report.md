# MDP _getSuccessorsB 优化报告

本报告记录 `bm_mdp.Battle._getSuccessorsB` 的第三轮真实优化、HIR 前后对比，以及当前已经确认的正确性与局部结构收益。

## 1. `_getSuccessorsB` 的 priority compare-add 路径

本轮实现：

- 在 `cinderx/Jit/hir/simplify.cpp` 中新增实验开关 `PYTHONJIT_ARM_MDP_PRIORITY_COMPARE_ADD`
- 仅对 `bm_mdp.Battle._getSuccessorsB` 中 `10000 * (action == "...")` 这类 priority bonus 路径做专门化
- 新增回归测试 `cinderx/PythonLib/test_cinderx/test_jit_mdp_get_successors_b_experiments.py`

### 1.1 优化前后 HIR 对比

优化前关键片段：

```text
fun bm_mdp:Battle._getSuccessorsB {
  ...
  v498:Bool = UnicodeCompare<Equal> v280 v279
  v283:Object = BinaryOp<Multiply> v278 v498
  ...
  v502:Bool = UnicodeCompare<Equal> v280 v293
  v297:Object = BinaryOp<Multiply> v292 v502
  ...
  v499:LongExact = LongBinaryOp<Add> v284 v285
  v503:LongExact = LongBinaryOp<Add> v298 v299
}
```

优化后关键片段：

```text
fun bm_mdp:Battle._getSuccessorsB {
  ...
  v498:Bool = UnicodeCompare<Equal> v280 v279
  v5xx:CBool = IsTruthy v498
  ...
  v5yy:LongExact = Phi<...> v278 v_zero
  ...
  v499:LongExact = LongBinaryOp<Add> v284 v5yy
  ...
  v502:Bool = UnicodeCompare<Equal> v280 v293
  v5aa:CBool = IsTruthy v502
  ...
  v5bb:LongExact = Phi<...> v292 v_zero
  v503:LongExact = LongBinaryOp<Add> v298 v5bb
}
```

结论：

- 优化前两段 priority bonus 都通过通用 `BinaryOp<Multiply>` 把 `10000` 与 `Bool` 对象相乘
- 优化后改成 `UnicodeCompare -> IsTruthy -> Phi(10000, 0)`，再进入 `LongBinaryOp<Add>`
- 这使 `_getSuccessorsB` 中与 priority 计算相关的对象算术减少，HIR 更接近纯整数路径

### 1.2 当前已确认的局部收益

`_getSuccessorsB` 单点 HIR opcode 统计：

- baseline: `BinaryOp = 6`，`GuardType = 5`
- 优化后: `BinaryOp = 4`，`GuardType = 3`

`mdp` 热点白名单本地近似跑分：

- 前两轮开关：`median_wall_sec = 6.083905s`
- 前三轮开关：`median_wall_sec = 6.068618s`
- 相比前两轮仅提升约 `0.25%`

判断：

- 这轮已经确认对目标 HIR 形状产生了正向影响
- 但在当前 `3` 样本本地近似口径下，边际收益非常小，尚不足以证明它是值得优先推进的主要性能改进

### 1.3 本轮调试中发现并修复的语义问题

第一次实现时，优化分支直接把 `UnicodeCompare` 返回的 `Bool` 对象作为 `CondBranch` 条件使用，导致：

- `Py_False` 作为非空对象仍被分支当作真值
- `Super Potion` 路径被错误地加上 `10000` priority bonus
- 完整 `mdp` 运行出现 `invalid result`

修复方式：

- 改为先显式 `IsTruthy`，再进入分支
- 同时把测试扩展到 `Dig` 与 `Super Potion` 两种 action，避免再次只覆盖单侧路径

修复后已确认：

- `cinderx/PythonLib/test_cinderx/test_jit_mdp_get_successors_b_experiments.py` 通过
- 三轮实验开关同时开启时，`bench_mdp` 单样本集成验证不再报 `invalid result`

### 1.4 当前判断

- 第三轮优化方向是成立的，但当前证据仍以“HIR 变轻 + 集成正确性恢复”为主
- 当前 `3` 样本本地近似仅观察到约 `0.25%` 的边际改善，仍需要更多样本确认是否超出噪声
- 剩余最显著的运行时头部问题仍然是 `Battle.getSuccessors` 的 `BinaryOp / UnhandledException`
