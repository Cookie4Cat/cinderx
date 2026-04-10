# MDP Benchmark CinderX JIT 劣化归因与优化设计

## 1. 背景与目标

当前 `pyperformance` 的 `mdp` benchmark 中，`CinderX JIT` 实测约为 `1.29s`，而对照基线 `stock CPython 3.14.0 + JIT` 约为 `1.04s`。本项目的目标不是修改 benchmark 本身，而是仅通过优化 `CinderX JIT`，将 `mdp` 的表现提升到持平乃至超过对照基线。

本项目的第一阶段不直接实现优化，而是先做系统性归因，明确 `CinderX JIT` 相对于 `stock CPython JIT` 的主要劣化点在哪里，并为后续实现提供一套可复用、可验证、可解释的证据链。

约束条件如下：

- 只优化 `CinderX JIT`，不修改 `pyperformance` 中的 `bm_mdp`
- 官方对照固定为 `$HOME/Repo/cpython` 中的 `Python 3.14.0` 提交 `ebf955df7a89ed0c7968f79faec1de49f61ed7cb`
- 基线与最终结果验证统一放在 `ARM Docker` 容器中
- 调试、局部实验、快速迭代统一在 `macOS 本地编译` 环境中完成
- 报告与文档统一使用中文
- 报告中必须给出优化前后的 HIR 对比

## 2. 问题定义

我们要回答的核心问题不是“`mdp` 慢”，而是：

1. `CinderX JIT` 在 `mdp` 中到底慢在哪些热点函数和热点路径上
2. 这些慢点应当归属于哪些劣化类型
3. 对比 `stock CPython 3.14 JIT`，`CinderX JIT` 的 HIR 或运行时行为有哪些额外成本
4. 哪些劣化点最值得优先优化，且最可能解释 `1.29s -> 1.04s` 的差距

第一阶段产出是一份中文分析报告，而不是实现补丁。报告只需要做到：

- 给出 `CinderX JIT vs stock CPython JIT` 的定量对照
- 按劣化类型分组，而不是只按函数罗列热点
- 每类问题提供代表函数与优化前后 HIR 对比
- 给出收益优先级排序

第二阶段才是执行计划与具体实现。

## 3. 现有上下文

`bm_mdp` 的主要结构由以下几部分组成：

- 图遍历：`topoSort()`
- 概率分布构造：`getCritDist()`、`getDamages()`
- 状态转移：`_applyActionSide1()`、`_applyAction()`、`Battle._applyActionPair()`
- 后继状态展开：`Battle._getSuccessorsB()`、`Battle._getSuccessorsC()`、`Battle.getSuccessors()`
- 主迭代入口：`Battle.evaluate()`

从代码形状上看，`mdp` 是一个混合型 workload，兼具：

- 容器访问与状态缓存
- `Fraction` 和 `defaultdict` 驱动的概率分布更新
- `namedtuple` / tuple 状态流转
- 排序、生成器表达式、`sum()` 等高阶调用链

因此它不太可能只有一个单点瓶颈，而更可能是多类 JIT 劣化同时叠加。

## 4. 总体策略

本项目采用“归因优先”的双环境分析架构，而不是直接试改。

### 4.1 正式基线层

在 `ARM Docker` 中固定采集以下三类结果：

- `stock CPython 3.14.0 + JIT on`
- 当前 `CinderX JIT`
- 优化后的 `CinderX JIT`

这一层只负责正式时间结论和最终验收，不承担高频实验。

### 4.2 本地归因层

在 `macOS 本地` 编译 `CinderX`，直接加载 `bm_mdp/run_benchmark.py` 做快速试验。这里不把绝对秒数当最终结论，而是作为近似归因工具，重点提取：

- 热点函数集合
- JIT 编译覆盖情况
- runtime stats / deopt 分布
- 关键热点函数的 HIR 文本
- 关键热点函数的 HIR opcode 统计

### 4.3 优化决策层

把函数级证据整理成“劣化类型分组”，每一组都要求具备：

- 代表函数
- 定量证据
- HIR 证据
- 与 `stock CPython JIT` 的差异解释
- 潜在收益排序

只有进入这个层的根因，才进入后续实现阶段。

## 5. 劣化类型分组

初始分析阶段优先按以下四类问题组织证据。

### 5.1 对象/容器访问链偏重

重点观察形状包括：

- `statep[0]`
- `state[0].stats.speed`
- `self.successors[statep]`
- `dist[newstatep] += ...`

怀疑点：

- `LoadAttr` / `LoadField` / `LoadSubscr` / `CallMethod` 残留过多
- guard 链过长
- 结构化对象访问未被压成足够轻的 HIR

首批代表函数：

- `Battle.evaluate()`
- `Battle.getSuccessors()`
- `Battle._getSuccessorsB()`

### 5.2 Fraction / defaultdict 驱动的概率分布路径偏重

重点观察形状包括：

- `Fraction(...)`
- `dist[x] += mult`
- `dist[newstatep] += p * pmult`
- 字典累加、合并、过滤

怀疑点：

- 通用 helper 调用太多
- 数值对象路径未能形成足够轻的专门化
- 分布构造中对象创建与更新成本偏高

首批代表函数：

- `getCritDist()`
- `Battle._getSuccessorsB()`
- `Battle._getSuccessorsC()`

### 5.3 高阶调用链与聚合表达式偏重

重点观察形状包括：

- `sorted(dist.items(), key=lambda ...)`
- `sum(...)`
- 生成器表达式
- `list(zip(*temp))[0]`

怀疑点：

- 调用边界多
- 内联不足
- builtins / helper lowering 不够薄

首批代表函数：

- `Battle.getSuccessors()`
- `Battle.getSuccessorsList()`
- `Battle.evaluate()`

### 5.4 状态对象流转与 tuple/namedtuple 更新偏重

重点观察形状包括：

- `namedtuple._replace()`
- 多层 tuple 状态拆装
- `state` / `statep` / `newstatep` 构造与传播

怀疑点：

- 高频、小成本、难以从整体时间直接看出的对象路径累计
- HIR 中存在大量看似零散但总量很高的对象操作

首批代表函数：

- `applyHPChange()`
- `_applyActionSide1()`
- `Battle._applyActionPair()`

## 6. 实验设计

### 6.1 macOS 本地快速归因

本地环境的目标不是复现最终 ARM 秒数，而是做方向正确、收敛快的分析。

计划在本地对 `bm_mdp` 做以下实验：

- 直接运行 `bench_mdp()` 及其热点函数链
- 收集强制编译后成功进入 JIT 的函数列表
- 聚合 runtime stats / deopt 数据
- 导出关键热点函数的初始 HIR / final HIR
- 对关键热点函数做 HIR opcode 统计

本地结论只用于：

- 排序热点
- 划分劣化类型
- 判断 HIR 改动是否命中
- 为 ARM 复核提供候选点

### 6.2 ARM Docker 正式复核

ARM Docker 用于：

- 固定 `stock CPython 3.14.0 + JIT` 正式基线
- 固定当前 `CinderX JIT` 正式基线
- 验证本地归因是否同向
- 做优化后的正式复测

ARM 环境不承担大规模探索型试错，只承担复核与最终验收。

## 7. 数据产物

本项目需要产出以下几类中间结果：

### 7.1 时间与运行时结果

- `stock CPython 3.14.0 + JIT` 正式时间
- 当前 `CinderX JIT` 正式时间
- 本地近似时间与中位数
- runtime stats / deopt 聚合

### 7.2 函数级热点结果

- 热点函数列表
- 已成功进入 JIT 的函数
- 候选热点函数的优先级排序

### 7.3 HIR 证据

- 优化前关键函数 HIR
- 优化后关键函数 HIR
- 必要时的 HIR pass 间变化
- HIR opcode 统计对照

### 7.4 分组与判断

- 劣化类型分组
- 每组代表函数
- 每组潜在收益判断
- 每组相对 `stock CPython JIT` 的差异解释

## 8. 报告结构

最终中文报告只需要覆盖以下内容：

### 8.1 目标与环境

- benchmark 名称
- 对照解释
- `stock CPython 3.14.0` 提交说明
- 本地与 ARM 的职责划分

### 8.2 热点总览

不是按源码顺序列函数，而是按劣化类型分组汇总。

### 8.3 每类劣化的证据链

每一类问题统一包含四部分：

- 现象：哪里慢
- 证据：时间、热点函数、deopt 或其他运行时数据
- HIR：代表函数的优化前后对比
- 判断：为什么这类问题会让 `CinderX JIT` 落后于 `stock CPython JIT`

### 8.4 优先级排序

按以下三个维度综合排序：

- 收益潜力
- 证据清晰度
- 实现可控性

### 8.5 结论

聚焦回答：

- 哪 1 到 2 类问题最可能解释主要差距
- 后续先打哪些点最划算

## 9. 风险与控制

### 9.1 本地近似误导正式结论

控制方式：

- 本地只用于归因，不用于正式秒数结论
- 核心判断必须由 ARM Docker 做方向复核

### 9.2 HIR 变轻但总性能不变

控制方式：

- 每个候选优化都必须绑定代表函数的局部收益证据
- 不能只凭 HIR 变化判断优先级

### 9.3 报告失焦

控制方式：

- 主报告按劣化类型分组
- 每组只保留 1 到 3 个代表函数做 HIR 主证据

### 9.4 改动面过大导致回归风险上升

控制方式：

- 后续实现阶段第一轮只挑 1 到 2 类最高收益问题
- 每步都要求 HIR 前后对比和正式复核

## 10. 验证标准

### 10.1 归因阶段验收

满足以下条件视为归因完成：

- 已完成 `stock CPython JIT` 与当前 `CinderX JIT` 的正式基线采集
- 已识别主要热点函数集合
- 已完成按劣化类型分组
- 每类问题都有代表函数与 HIR 证据
- 已形成收益优先级排序

### 10.2 后续优化阶段验收

后续每个优化点都必须满足：

- 代表函数 HIR 前后变化符合预期
- 本地近似验证出现同向收益
- ARM Docker 正式复测无反向退化

### 10.3 最终目标验收

最终目标为：

- `CinderX JIT` 在 `mdp` 上持平或超过 `stock CPython 3.14.0 + JIT`
- 能用 HIR 前后对比解释收益来源

## 11. 不做的事情

本项目第一阶段明确不做以下事项：

- 不修改 `pyperformance` 的 `bm_mdp`
- 不直接进入 JIT 代码实现
- 不在报告中混入与 `mdp` 无关的广泛性能结论
- 不把 macOS 本地绝对时间作为正式结论引用

## 12. 后续阶段

在本设计文档经确认后，下一阶段将产出一份独立执行计划，内容包括：

- 归因阶段的具体实验清单
- HIR 导出与对比方式
- 劣化类型排序规则的量化方法
- 后续优化实现的阶段切分
- 每一步的验证与回退策略
