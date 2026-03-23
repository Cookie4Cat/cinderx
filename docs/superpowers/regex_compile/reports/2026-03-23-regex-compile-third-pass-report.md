# regex_compile 第三轮设计边界报告

## 1. 背景

前两轮已经把 `regex_compile` 的问题边界收得比较清楚：

- 第一轮确认了一条真实有效的收益线：
  - 默认 `jit.auto()` 对 `bench_regex_compile()` 的触发过慢
  - 通过 loop/backedge 感知型早编译，默认路径已经能稳定让主 benchmark 函数进入 JIT
- 第二轮确认：
  - ARM 正式环境下当前源码仍未追平 `stock CPython 3.14.0 + JIT`
  - 新的主热点已经转移到 stdlib：
    - `re._parser.SubPattern.__getitem__`
    - `BinaryOp / UnhandledException`

因此第三轮的目标不再是继续做小型 peephole，而是回答两个问题：

1. 如果继续优化，真正值得投入的切入点是什么
2. 当前是否已经进入“中等规模实现”门槛，而不是再做一轮低风险局部调整

## 2. 当前已知事实

### 2.1 本地近似结果

在当前源码、项目 `.venv`、`PYTHONJITHUGEPAGES=0` 口径下：

- 默认 `jit.auto()`：约 `87.8ms`

这说明第一轮 loop/backedge 早编译策略仍然有效，但它已经不能单独保证正式环境达标。

### 2.2 ARM 正式复核结果

在 ARM 容器里，基于当前源码安装 editable `cinderx` 后，`regex_compile` 的正式结果约为：

- 当前 `CinderX JIT`：`98.2ms`
- 已知 `stock CPython 3.14.0 + JIT`：`94.9ms`

这说明当前还存在剩余差距，而且这部分差距已经不再来自 `bench_regex_compile()` 本体没有编进去。

### 2.3 当前主热点

runtime stats 头部仍然集中在：

- 文件：`re/_parser.py`
- 函数：`SubPattern.__getitem__`
- 原因：`BinaryOp / UnhandledException`
- 计数：约 `125k`

同时已经确认：

- `bench_regex_compile()` 已经编进 JIT
- `SubPattern.__getitem__` 也已经编进 JIT

因此当前问题是：

- 热点已经编译
- 但编译后的执行形状仍然偏重

## 3. 第三轮关键观察

目标函数源码如下：

```python
def __getitem__(self, index):
    if isinstance(index, slice):
        return SubPattern(self.state, self.data[index])
    return self.data[index]
```

它的 HIR 关键信号是：

- `BinaryOp = 2`
- `DeoptPatchpoint = 3`
- `CheckField = 3`
- `LoadField = 6`

最终 HIR 文本显示，两个分支里的热路径都还是：

1. `LoadField<data> -> CheckField("data") -> BinaryOp<Subscript>`
2. `LoadField<data> -> CheckField("data") -> BinaryOp<Subscript>`

这意味着：

- `self.data` 已经被部分结构化
- 但真正的下标访问仍然是 generic `BinaryOp<Subscript>`

## 4. 已验证不可行的方向

### 4.1 禁止 stdlib tiny helper 被 auto-JIT 编译

结论：

- 方向错误
- 会让默认路径退化

原因：

- `SubPattern.__getitem__` 是真实热点
- 它不是“不该编”，而是“应该编，但要编得更轻”

### 4.2 在 `simplifyBinaryOp()` 里补局部专门化

结论：

- 不够用

原因：

- `BinaryOp<Subscript>` 出现时已经太晚
- 关键问题不是缺一个后期 peephole
- 而是分支后的类型信息没有被继续沿用

## 5. 真正的切入点

第三轮最重要的结论是：

`SubPattern.__getitem__` 的性能问题，本质上是 **分支后类型未细化**。

更具体地说：

1. 控制流已经知道当前走的是：
   - `index is slice`
   - 或 `index is not slice`
2. 但这种事实没有继续沉淀为：
   - slice 分支中的更具体 slice 类型
   - 非 slice 分支中的更具体非-slice / int-like 下标类型
3. 所以后续的 `self.data[index]` 只能继续走 generic `BinaryOp<Subscript>`

这意味着下一轮如果继续做，真正合理的技术方向只有两类：

### 5.1 更早的分支类型细化

目标：

- 在 `isinstance(index, slice)` 之后，让两个分支各自携带更有价值的 `index` 类型信息

潜在收益：

- 后续 `BinaryOp<Subscript>` 可以有机会落到更轻的 list/list-slice 路径

代价：

- 会碰 builder 或 branch refinement 逻辑
- 已经超出局部 `simplify` 规则范围

### 5.2 builder 级模式识别

目标：

- 针对 `SubPattern.__getitem__` 这种小而高频的 stdlib helper
- 更早识别：
  - `self.data[index]`
  - `self.data[slice]`

潜在收益：

- 可以直接绕开当前 generic `BinaryOp<Subscript>` 形态

代价：

- 模式更具体
- benchmark / stdlib 形状依赖更强

## 6. 当前决策门槛

第三轮要解决的不是“怎么立刻继续写代码”，而是“是否值得继续投入”。

我建议把继续推进的门槛定义成下面两条：

1. 愿意接受一轮中等规模实现
   - 不是一个小 helper
   - 也不是一条简单 `simplify` 规则
   - 而是 builder / 类型细化层面的改动

2. 愿意接受更高的回归与验证成本
   - 改动影响面比前两轮更大
   - 需要更严格的 HIR、行为和正式环境复核

如果这两条不能接受，那么当前更合理的结论是：

- 第一轮有效收益线已经拿到
- 第二、三轮已经把剩余差距的根因说清楚
- 此时停止继续优化是合理的工程决策

## 7. 第三轮穿刺数据

为了判断这条线是否值得继续保留为“下一轮主攻优化点”，本轮额外做了三组穿刺采样。

### 7.1 真实 benchmark 中的调用频次

对 `bench_regex_compile(1, regexes)` 做轻量包装统计后，得到：

- `SubPattern.__getitem__` 总调用次数：约 `124,981`
- 其中：
  - `slice` 路径：`2,292`
  - 非 `slice` 路径：`122,689`

这说明：

- 该函数的确是高频热点
- 但热点主体几乎全部集中在非 `slice` 路径
- 如果继续做，这条线真正值得优化的是普通下标访问，不是 `slice` 分支

### 7.2 纯函数微基准：解释器 vs 当前 JIT

对 `SubPattern.__getitem__` 做独立微基准后，得到：

- 非 `slice` 路径：
  - 解释器：约 `26.4ms`
  - 当前 JIT：约 `27.7ms`
- `slice` 路径：
  - 解释器：约 `93.4ms`
  - 当前 JIT：约 `87.9ms`

这说明：

1. 当前 JIT 对 `slice` 路径有一定收益
2. 但对占绝大多数的非 `slice` 路径，当前 JIT 并没有明显优于解释器

### 7.3 上限判断

结合真实 benchmark 中的调用分布，可以得到一个粗略判断：

- `SubPattern.__getitem__` 的问题是真实存在的
- 但以当前观测量级来看，这条线更像是“可以继续榨出一些 steady-state 收益”
- 它不像第一轮那样，存在一个一上来就能吞掉主要差距的大头

换句话说：

- 这条线不是没有价值
- 但它已经不足以自然担任下一轮主攻点，除非我们愿意投入一轮中等规模实现，并接受收益不一定足够大的风险

## 8. 当前建议

第三轮建议分成两个选项：

### 选项一：先停

适用条件：

- 当前主要目标是收束这轮 `regex_compile` 工作
- 不想再进入一轮中等规模 JIT 改动

结论表达：

- 已经拿到一条有效收益线
- 剩余差距主要在 stdlib 高频 helper 的分支类型细化问题
- 当前不继续做高风险优化

### 选项二：进入第四轮设计与实现

适用条件：

- 希望继续逼近或超过 `stock CPython JIT`
- 接受更高复杂度的 JIT 基础设施改动

推荐优先顺序：

1. 先设计“`isinstance(index, slice)` 后的分支类型细化”
2. 仅当这条线不可行，再考虑 builder 级模式识别

## 9. 当前结论

第三轮已经确认：

1. `regex_compile` 还有优化空间
2. 剩余空间不再是低风险的局部 peephole
3. 真正的切入点是 `SubPattern.__getitem__` 的分支后类型细化
4. 如果继续推进，应视为一轮新的中等规模优化，而不是第一轮收益线的简单延长
5. 从穿刺数据看，这条线目前更适合标记为“可选中期方向”，而不是“下一轮默认主攻点”

因此，当前最合理的工程结论是：

- 要么在此收束，并把剩余差距解释清楚
- 要么明确进入第四轮，更早地处理 branch/type refinement

## 10. 本轮收束结论

结合最新真实环境结果：

- 当前 `CinderX JIT`：约 `84.3ms`
- `stock CPython 3.14.0 + JIT`：约 `83.8ms`

两者差距已经收敛到约 `0.5ms`，量级约为 `0.6%`。

在这个前提下，再结合第三轮穿刺数据，可以得到更明确的工程判断：

1. 第一轮 loop/backedge 早编译已经拿到了这次 `regex_compile` 的主要收益
2. 剩余差距主要集中在 stdlib 高频 helper 的分支类型细化问题
3. 这条线如果继续做，已经是中等规模实现，风险和验证成本都明显上升
4. 以当前剩余差距量级来看，没有再发现“收益足够大且风险足够低”的后续优化点

因此，本用例当前建议正式收束：

- 保留第一轮有效优化
- 保留第二、三轮的归因与边界结论
- 不继续进入第四轮实现

如果后续再回到 `regex_compile`，更合适的前提应是：

- 已有更强的正式环境信号表明这条线重新成为主要性能瓶颈
- 或 branch/type refinement 本身在更广泛场景下出现复用价值
