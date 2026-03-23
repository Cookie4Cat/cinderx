# regex_compile 第二轮归因报告

## 1. 背景

在第一轮实现后，`regex_compile` 已经确认存在一条有效收益线：

- 默认 `jit.auto()` 能让 `bench_regex_compile()` 更早进入 JIT
- 这条改动在本地近似环境中带来了明显收益

但在继续做正式复核和热点下钻时，新的头部热点已经从 benchmark 主函数本体，转移到了 stdlib：

- `re/_parser.py`
- `SubPattern.__getitem__`
- `BinaryOp / UnhandledException`

因此第二轮的目标不再是“让主 benchmark 更早编译”，而是回答：

1. `SubPattern.__getitem__` 是否是当前剩余差距的真实主因
2. 如果是，它的问题更接近“根本不该编”，还是“编进去了，但 HIR 形状不够好”

## 2. 当前观测

### 2.1 本地近似口径

基于当前源码、项目 `.venv`、`PYTHONJITHUGEPAGES=0` 的本地近似脚本：

- 默认 `jit.auto()`：约 `87.8ms`

这说明第一轮收益线仍然存在，但已经不再像最乐观那轮那样明显低于目标线。

### 2.2 正式复核口径

在 ARM 容器中，当前源码版 `cinderx` 已经能够通过降低并行度完成 editable install：

- `CINDERX_BUILD_JOBS=2`

基于当前源码直接在容器里运行 `regex_compile`，得到：

- 当前 CinderX JIT：约 `98.2ms`
- 已知 stock CPython JIT 基线：约 `94.9ms`

这说明：

1. 第一轮“让 benchmark 主函数更早编译”的改动在 ARM 正式环境中不足以达标
2. 剩余差距不能再简单归因于 `bench_regex_compile()` 没编进去

## 3. 新的头部热点

当前 runtime stats 的头部 deopt 为：

- 文件：`re/_parser.py`
- 函数：`SubPattern.__getitem__`
- 行号：`171`
- 原因：`BinaryOp / UnhandledException`
- 计数：约 `125k`

同时确认：

- `bench_regex_compile()` 已经编进 JIT
- `SubPattern.__getitem__` 也已经编进 JIT

所以这不是“热点没编”的问题，而是“热点编进去了，但执行形状仍然偏重”。

## 4. SubPattern.__getitem__ 的实际代码形状

目标函数源码如下：

```python
def __getitem__(self, index):
    if isinstance(index, slice):
        return SubPattern(self.state, self.data[index])
    return self.data[index]
```

这个函数非常小，但调用频率极高。

## 5. HIR 结论

当前 `SubPattern.__getitem__` 的 HIR opcode 统计显示：

- `BinaryOp = 2`
- `DeoptPatchpoint = 3`
- `CheckField = 3`
- `LoadField = 6`

抓取最终 HIR 文本后，可以看到两条热路径的核心都还是：

1. `LoadField<data> -> CheckField("data") -> BinaryOp<Subscript>`
2. `LoadField<data> -> CheckField("data") -> BinaryOp<Subscript>`

也就是说：

- `self.data` 已经被拆成 `LoadField + CheckField`
- 但真正的下标访问仍然停留在 generic `BinaryOp<Subscript>`

## 6. 第二轮实验

### 6.1 实验一：禁止 auto-JIT 编译 stdlib tiny helper

思路：

- 假设 `SubPattern.__getitem__` 根本不该被 auto-JIT 编译
- 仅对小型 stdlib dunder helper 禁止默认 auto 编译

结果：

- 方向错误
- 默认路径显著退化

结论：

- `SubPattern.__getitem__` 不是“不该编”
- 它更像是“应该编，但当前编译形状不够好”

### 6.2 实验二：在 simplifyBinaryOp() 里直接补窄专门化

思路：

- 针对 `SubPattern.__getitem__` 中的 `self.data[index]`
- 尝试把 `CheckField("data") + BinaryOp<Subscript>` 压成更具体的 list 路径

结果：

- 没有得到可持续的 HIR 改善
- 简单的局部 `simplifyBinaryOp()` 规则吃不到真正关键的类型信息

结论：

- 这个问题出现得比 `simplifyBinaryOp()` 更早
- 不是一个“后期 peephole” 级别的问题

## 7. 核心根因

当前最重要的结论是：

`SubPattern.__getitem__` 的问题，不在于“有没有进入 JIT”，而在于：

- 控制流已经知道当前分支对应 `index is slice` 还是 `index is not slice`
- 但这种分支信息没有沿分支继续细化成 `index` 的更具体类型
- 因此后续 `BinaryOp<Subscript>` 仍然只能保持 generic 形态

换句话说：

- 这不是“热点没编”
- 也不是“只差一个小 helper”
- 而是“分支之后缺少足够的类型细化”

## 8. 当前判断

第二轮已经把问题边界收得比较清楚：

1. `SubPattern.__getitem__` 是真实热点
2. 它应该被编译
3. 它的性能问题来自 `BinaryOp<Subscript>` 没有被压成更轻的 specialized path
4. 这个问题的切入点已经超出局部 `simplify` 规则，进入“更早的类型细化 / builder 模式识别”范围

## 9. 后续建议

如果继续推进，下一轮更合理的方向应是：

1. 更早的分支类型细化
   - 让 `isinstance(index, slice)` 之后的两个分支，带上更有价值的类型信息

2. builder 级模式识别
   - 针对 `SubPattern.__getitem__` 这种小而高频的 stdlib helper，识别：
     - `self.data[index]`
     - `self.data[slice]`
   - 在 builder 或更早阶段直接落到 list/list-slice 路径

3. 暂不建议继续在 `simplifyBinaryOp()` 层面堆更多特判
   - 当前证据显示，这一层已经太晚

## 10. 当前结论

`regex_compile` 还有继续优化的空间，但下一步已不再是“小而稳的 peephole 调整”。

如果继续做，应视为一轮新的中等规模优化，而不是第一轮收益线的简单延伸。

第三轮关于“是否继续投入”和“真正技术切入点”的收束，已经单独整理在：

- `docs/superpowers/regex_compile/reports/2026-03-23-regex-compile-third-pass-report.md`
