# MDP Benchmark CinderX JIT 劣化归因报告

## 1. 目标与当前状态

本报告用于分析 `pyperformance` 的 `mdp` benchmark 中，`CinderX JIT` 相对于 `stock CPython 3.14.0 + JIT` 的主要劣化点。

当前阶段完成情况：

- 已打通 `mdp` 的 macOS 本地近似归因入口
- 已能直接导出函数级 HIR opcode 统计
- 已能显式探测 `print_hir`、`get_function_hir_opcode_counts`、`get_and_clear_runtime_stats`
- 已确认当前本地构建不能直接调用 `print_hir()`，需要通过 `PYTHONJITDUMPFINALHIR` 抓取文本 HIR
- 已新增 `scripts/diagnostics/debug_hir_env.py`，统一生成本地 Debug venv 和 `mdp` HIR 抓取命令
- 已完成第一轮本地近似基线与热点白名单归因
- 已完成 ARM Docker 第一轮正式对照，并验证 `stock CPython 3.14.0 @ ebf955df7a8 + JIT` 构建链路
- 已完成前三轮正式优化与第四轮负优化实验复盘

当前尚未完成：

- 下一轮优化点的系统性挖掘与正式复核
- `Battle.getSuccessors` 命中路径与 miss 路径的进一步拆分优化

当前前三轮与第四轮的结论已经明确：

- HIR 形状改善：`BinaryOp 6 -> 4`，`GuardType 5 -> 3`
- 热点白名单本地近似：相对前两轮仅约 `0.25%` 边际改善
- `Battle.getSuccessors` 的中期整函数 helper 路径已经作为实验实现过
- 该实验在本地近似与容器口径下出现过正向信号，但真实环境结果从第三轮 `1.04s` 回退到第四轮 `1.05s`

结论：

- 第三轮更像“结构上更合理，但性能收益不大”的实验
- 第四轮说明 `Battle.getSuccessors` 的异常控制流热点确实值得打，但当前 whole-helper 方案会把命中路径拖重，不能纳入正式收益线

围绕 `Battle.getSuccessors`，目前已经额外确认了一条短期路径与一条中期路径：

- 短期路径：把 `self.successors[statep]` 的 miss 改写为窄 helper，并保持 `KeyError` 语义不变
- 结果：HIR 能从 `BinaryOp<Subscript>` 改成 `CallStatic + CheckExc`，但 `UnhandledException` deopt 计数基本不变，只是从 `BinaryOp` 转移到 `CheckExc`
- 中期路径：通过 `Battle.getSuccessors` 的整函数 helper 直接绕开 `KeyError` 控制流，虽然能把 `BinaryOp<Subscript>` 改成 `CallStatic + CheckExc` 并消除该函数的头部 deopt，但真实环境回退，当前已从主收益线回退

## 2. 环境与口径

### 2.1 正式对照

- `stock CPython 3.14.0 + JIT`
- 基线提交：`ebf955df7a89ed0c7968f79faec1de49f61ed7cb`
- 本地源码：`$HOME/Repo/cpython`

### 2.2 本地近似归因

本地归因使用：

- `pyperformance` 源码：`$HOME/Repo/pyperformance`
- benchmark 文件：`pyperformance/data-files/benchmarks/bm_mdp/run_benchmark.py`
- 本地入口：`scripts/arm/run_local_pyperf_matrix.py`
- 直接运行器：`scripts/arm/bench_pyperf_direct.py`

说明：

- macOS 本地结果仅用于归因和快速迭代
- 正式秒数结论以后续 ARM Docker 结果为准

## 3. ARM Docker 正式对照

### 3.1 基线解释器验证

容器内已从 `$HOME/Repo/cpython` 构建出独立的 stock CPython JIT 解释器：

- 版本：`3.14.0 (tags/v3.14.0:ebf955df7a8, ...)`
- 可执行文件：`/opt/cpython-jit/bin/python3`
- 验证结果：`sys._jit.is_available() == True`
- 验证结果：`PYTHON_JIT=1` 下 `sys._jit.is_enabled() == True`

这一步确认当前 ARM 正式基线口径已经从“官方镜像自带 python3”校正为“官方社区 3.14.0 源码 + experimental JIT + 运行时显式开启”。

### 3.2 `mdp` 正式对照结果

命令：

```bash
docker exec cpython-baseline-test sh -lc 'BENCHMARK=mdp SAMPLES=5 WARMUP=1 /scripts/test-comparison.sh'
```

结果摘要：

- 真实环境基线：`stock CPython 3.14.0 + JIT = 1.04s`
- 真实环境第三轮优化 commit：`1.04s`
- 真实环境第四轮优化 commit：`1.05s`
- 结论上，前三轮已经把 `CinderX JIT` 拉到与 `stock CPython JIT` 持平
- 第四轮 whole-helper 方案在真实环境中没有延续本地/容器里的正向结果，反而约有 `0.96%` 的回退

结论：

- 真实环境的优先级高于本地近似和容器结果，因此正式收益线当前只计入前三轮
- `applyHPChange`、`getCritDist` 与 `Battle.getSuccessors` 的异常控制流都属于真实主差距来源
- 但 `Battle.getSuccessors` 的当前 whole-helper 方案需要视为负优化实验，而不是正式收益点

### 3.3 关于容器中“optimized”一栏的说明

在容器口径里，`ENABLE_OPTIMIZATION=1` 当前分发到 `mdp` 的运行时开关为：

- `PYTHONJIT_ARM_MDP_INT_CLAMP_MIN_MAX=1`
- `PYTHONJIT_ARM_MDP_FRACTION_MIN_COMPARE=1`
- `PYTHONJIT_ARM_MDP_PRIORITY_COMPARE_ADD=1`

说明：

- 第四轮 whole-helper 曾经接入过容器的 `optimized` 路径，并在该口径下表现为正向
- 但真实环境结果已经证明这条路径不能计入正式收益
- 因此主线容器脚本也已回退到只包含前三轮开关

## 4. 本地近似基线

### 4.1 全量候选函数强制编译

命令：

```bash
python3 scripts/arm/run_local_pyperf_matrix.py \
  --pyperformance-root "$HOME/Repo/pyperformance" \
  --benchmark mdp \
  --mode baseline \
  --samples 5 \
  --prewarm-runs 1
```

结果摘要：

- `candidate_count = 17`
- `compiled_count = 17`
- `median_wall_sec = 0.9647443329449743`
- `min_wall_sec = 0.951243375078775`
- `total_deopt_count = 314550`

结论：

- `mdp` 的主要 Python 级函数当前都能进入 `CinderX JIT`
- 问题不像是“编不进去”，更像是“编进去了但某些路径形状仍然偏重”

### 4.2 热点白名单归因

命令：

```bash
python3 scripts/arm/bench_pyperf_direct.py \
  --module-path "$HOME/Repo/pyperformance/pyperformance/data-files/benchmarks/bm_mdp/run_benchmark.py" \
  --bench-func bench_mdp \
  --bench-args-json "[1]" \
  --compile-strategy names \
  --compile-names "Battle.evaluate,Battle.getSuccessors,Battle._getSuccessorsB,getCritDist,topoSort,applyHPChange" \
  --samples 5 \
  --prewarm-runs 1 \
  --specialized-opcodes
```

结果摘要：

- `selected_compile_count = 6`
- `compiled_count = 6`
- `median_wall_sec = 1.0341763750184327`
- `min_wall_sec = 1.0288662919774652`
- `total_deopt_count = 314550`

结论：

- 仅编译 6 个关键热点函数时，本地近似时间从 `0.965s` 恶化到 `1.034s`
- 说明这 6 个函数之外的若干辅助函数也在总时间中贡献了明显收益
- 但这 6 个函数仍然足以代表主劣化类型，适合作为 HIR 主证据

## 5. 头部 deopt 观察

当前本地近似基线中，deopt 头部集中在以下位置：

| Rank | 函数 | 行号 | 描述 | 原因 | Count |
|------|------|------|------|------|-------|
| 1 | `applyHPChange` | 72 | `GuardType` | `GuardFailure` | `272150` |
| 2 | `Battle.getSuccessors` | 186 | `BinaryOp` | `UnhandledException` | `24105` |
| 3 | `getCritDist` | 45 | `GuardType` | `GuardFailure` | `18295` |

初步判断：

- `applyHPChange` 是目前最突出的单点异常来源
- `Battle.getSuccessors` 虽然 HIR 很短，但存在异常路径或缓存访问相关成本
- `getCritDist` 暗示 `Fraction` / 分布路径仍有明显类型守卫压力

前两轮优化落地后，热点白名单近似跑分的剩余头部 deopt 已收敛为：

| Rank | 函数 | 行号 | 描述 | 原因 | Count |
|------|------|------|------|------|-------|
| 1 | `Battle.getSuccessors` | 186 | `BinaryOp` | `UnhandledException` | `14463` |

补充判断：

- 前两轮已经基本消除了 `applyHPChange` 与 `getCritDist` 的高频守卫失败
- 运行时层面当前最集中的剩余问题已经转向 `Battle.getSuccessors`
- 第三轮先转向 `_getSuccessorsB`，是因为它更适合做局部 HIR 减重实验，而不是因为它在运行时统计上超过了 `Battle.getSuccessors`

## 6. 按劣化类型分组的初步结论

### 6.1 对象/容器访问链偏重

代表函数：

- `Battle.evaluate`
- `Battle.getSuccessors`
- `Battle._getSuccessorsB`

主要迹象：

- `Battle.evaluate` 中 `LoadField = 38`、`VectorCall = 18`、`PrimitiveUnbox = 20`
- `Battle._getSuccessorsB` 中 `LoadField = 13`、`LoadAttrCached = 4`、`LoadMethodCached = 3`
- `Battle.getSuccessors` 虽短，但出现 `LoadAttr`、`LoadField`、`DeoptPatchpoint`

初步判断：

- 状态对象与缓存访问链条是主观察对象
- `evaluate()` 中存在较重的对象访问、闭包单元访问与控制流合流
- `getSuccessors()` 可能是“局部很短但极高频”的关键路径

### 6.2 `Fraction` / `defaultdict` 分布路径偏重

代表函数：

- `getCritDist`
- `Battle._getSuccessorsB`
- `applyHPChange`

主要迹象：

- `getCritDist` 中 `VectorCall = 5`、`StoreSubscr = 1`、`InPlaceOp = 2`、`GuardType = 3`
- `Battle._getSuccessorsB` 中 `MakeDict = 1`、`SetDictItem = 1`、`LongBinaryOp = 2`
- `applyHPChange` 的 deopt 头部集中在 `GuardType`

初步判断：

- 概率分布构造路径中仍有较重的对象数值处理
- `applyHPChange` 可能是一个“小函数、高频触发、守卫失败极多”的高收益切入点

### 6.3 高阶调用链偏重

代表函数：

- `topoSort`
- `Battle.evaluate`
- `Battle.getSuccessorsList`

主要迹象：

- `topoSort` 中 `CallMethod = 6`、`LoadMethodCached = 5`
- `Battle.evaluate` 中 `MakeFunction = 4`、`SetFunctionAttr = 4`、`VectorCall = 18`
- `Battle.getSuccessorsList` 中 `CallEx = 1`、`VectorCall = 2`

初步判断：

- `mdp` 不只是数值或字典问题，也有明显的高阶调用与 helper 调用链
- `evaluate()` 里的闭包、局部函数和聚合表达式可能在 HIR 中留下较重痕迹

### 6.4 状态对象流转偏重

代表函数：

- `applyHPChange`
- `_applyActionSide1`
- `Battle._applyActionPair`

主要迹象：

- `_applyActionSide1` 中 `LoadAttrCached = 16`、`MakeTuple = 2`、`StoreSubscr = 1`
- `Battle._applyActionPair` 中 `LoadField = 9`、`StoreSubscr = 1`、`MakeTuple = 1`
- `applyHPChange` 结构短小，但守卫失败极高

初步判断：

- tuple / namedtuple 状态流转很可能以大量短路径的形式累计成本
- 这类问题不一定在单函数 HIR 上看起来最大，但在运行时统计上会被放大

## 7. 关键代表函数 HIR 统计摘要

### 6.1 `Battle.evaluate`

显著指标：

- `Branch = 51`
- `Decref = 68`
- `LoadField = 38`
- `PrimitiveCompare = 21`
- `PrimitiveUnbox = 20`
- `VectorCall = 18`
- `Phi = 25`

解释：

- 这是当前最复杂的 HIR 入口函数
- 其成本更像“高层控制流 + 大量对象/容器访问 + 多个 helper 调用”的混合体

### 6.2 `Battle._getSuccessorsB`

显著指标：

- `Branch = 16`
- `Decref = 34`
- `LoadField = 13`
- `PrimitiveCompare = 9`
- `VectorCall = 6`
- `GuardType = 5`

解释：

- 明显是“分布更新 + 状态转移 + 容器访问”混合热点
- 非常适合对照 `Fraction/defaultdict` 与对象访问链两个劣化类型

### 6.3 `getCritDist`

显著指标：

- `VectorCall = 5`
- `StoreSubscr = 1`
- `InPlaceOp = 2`
- `PrimitiveUnbox = 4`
- `GuardType = 3`

解释：

- 更接近纯分布构造与数值对象路径
- 适合作为 `Fraction` 相关问题的代表函数

### 6.4 `applyHPChange`

显著指标：

- `GuardType = 1`
- `LoadAttrCached = 3`
- `Decref = 4`

解释：

- HIR 体量并不大，但 deopt 数极高
- 这是典型的“局部看不重，运行时频率极高”的候选切入点

## 8. 优化前 HIR 文本片段

说明：

- 当前本地构建直接调用 `cinderjit.print_hir()` 会因非 debug build 触发断言
- 现阶段文本 HIR 统一通过 `PYTHONJITDUMPFINALHIR=1` 的日志路径抓取
- 建议后续统一通过 `python3 scripts/diagnostics/debug_hir_env.py setup` 与 `python3 scripts/diagnostics/debug_hir_env.py mdp-hir` 生成标准命令

### 7.1 `applyHPChange`

节选：

```text
fun bm_mdp:applyHPChange {
  bb 0 {
    v21:Object = LoadArg<0; "hstate">
    v22:Object = LoadArg<1; "change">
    ...
  }

  bb 1 (preds 0, 2) {
    v30:OptObject = LoadGlobalCached<0; "min">
    v31:... = GuardIs<...> v30
    ...
    v48:Object = LoadAttrCached<1; "fixed"> v21
    v49:Object = LoadAttrCached<2; "maxhp"> v48
    Decref v48
```

观察：

- 入口非常短，但一开始就进入 `LoadGlobalCached("min") + GuardIs + LoadAttrCached("fixed") + LoadAttrCached("maxhp")`
- 这与 deopt 头部高度集中在 `GuardType` 的现象一致
- 候选优化方向是减少该小函数中的高频守卫失败或对象路径不稳定性

### 7.2 `getCritDist`

节选：

```text
fun bm_mdp:getCritDist {
  bb 0 {
    v76:Object = LoadArg<0; "L">
    v77:Object = LoadArg<1; "p">
    ...
  }

  bb 9 (preds 0, 10) {
    v104:OptObject = LoadGlobalCached<0; "min">
    v105:... = GuardIs<...> v104
    v107:OptObject = LoadGlobalCached<1; "Fraction">
    v108:... = GuardIs<...> v107
    v110:ImmortalLongExact[1] = LoadConst<ImmortalLongExact[1]>
```

观察：

- `getCritDist` 的前段就暴露出 `min` 与 `Fraction` 的全局加载和守卫
- 这与 opcode 统计中的 `VectorCall`、`GuardType`、`StoreSubscr` 组合高度一致
- 候选优化方向是压低 `Fraction` 相关路径的 guard/call 成本，或者减少分布构造路径中的对象级回退

## 9. 优化迭代报告

本报告只保留 `mdp` 的基线归因、热点分组与优先级结论。真实优化结果已拆分到单独报告：

- 第一轮：`docs/superpowers/mdp/reports/2026-03-19-mdp-applyhpchange-optimization-report.md`
- 第二轮：`docs/superpowers/mdp/reports/2026-03-19-mdp-getcritdist-optimization-report.md`
- 第三轮：`docs/superpowers/mdp/reports/2026-03-19-mdp-getsuccessorsb-optimization-report.md`
- 第四轮 `Battle.getSuccessors` whole-helper 路径已降级为负优化实验，结论保留在本报告中，不再作为主线独立收益报告维护

## 10. 当前优先级排序

基于现有本地证据，第一轮优先级建议如下：

### P1: 高频守卫失败路径

首选观察对象：

- `applyHPChange`
- `getCritDist`

原因：

- 运行时 deopt 证据最强
- HIR 体量不大，便于快速做局部优化验证
- 很可能能用较小改动换来明显收益

### P2: 状态访问与缓存分发路径

首选观察对象：

- `Battle.getSuccessors`
- `Battle._getSuccessorsB`
- `Battle.evaluate`

原因：

- 与主控制流直接相关
- 一旦能打薄，潜在总收益高
- 但实现复杂度明显高于 P1

### P3: 高阶调用链与闭包/聚合表达式

首选观察对象：

- `topoSort`
- `Battle.evaluate`
- `Battle.getSuccessorsList`

原因：

- HIR 里有明显 helper / call 痕迹
- 但是否是主差距来源仍需结合 ARM 正式结果进一步验证

## 11. 下一步

下一阶段要完成的事情：

1. 保留 `applyHPChange` 与 `getCritDist` 这两条已验证正式收益主线，并将第三轮 `_getSuccessorsB` 保持为次优先低收益项
2. 将 `_getSuccessorsB` 的第三轮实验保留为“局部形状变轻但总收益较小”的次优先项
3. 将 `Battle.getSuccessors` 的短期 helper 路径定性为“形状改善但不足以消除 deopt”，避免继续在同一路线上投入
4. 将第四轮 `Battle.getSuccessors` whole-helper 明确定性为“真实环境负优化”，主线保持回退，只在实验线继续深挖
5. 围绕 `Battle.getSuccessors` 重新设计只优化 miss 路径、尽量不增加 hit 固定成本的新方案，例如更细粒度的 `KeyError` lowering 或更窄的 miss helper
