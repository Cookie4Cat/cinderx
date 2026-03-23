# regex_compile 第一轮归因与优化报告

## 1. 目标

本轮目标是分析 `pyperformance` 的 `regex_compile` benchmark 中，`CinderX JIT` 相对于 `stock CPython 3.14.0 + JIT` 的剩余差距，并判断第一轮最值得下手的优化点。

目标线：

- `CinderX JIT`：约 `96ms`
- `stock CPython 3.14.0 + JIT`：约 `84ms`

## 2. 环境口径

本轮本地验证沿用当前统一口径：

- 项目 `.venv`
- `uv` 管理的隔离环境
- `python3.14` 作为环境底座
- 运行时显式设置 `PYTHONJITHUGEPAGES=0`

benchmark 源码来自本机 `pyperformance` 仓库中的：

- `bm_regex_compile/run_benchmark.py`
- `bm_regex_compile/bm_regex_effbot.py`
- `bm_regex_compile/bm_regex_v8.py`

## 3. benchmark 结构

`regex_compile` 的主计时入口是：

- `bench_regex_compile(loops, regexes)`

其关键结构是：

1. `capture_regexes()`
   - 通过临时替换 `re.compile` / `re.search` / `re.sub`
   - 从 `bm_regex_effbot` 和 `bm_regex_v8` 中收集 regex 与 flags

2. `bench_regex_compile()`
   - 外层按 `loops` 循环
   - 内层遍历所有捕获到的 `(regex, flags)`
   - 每次都 `re.purge()` 后重新 `re.compile(regex, flags)`

本地观察中，`regexes` 数量约为 `4172`。

## 4. 第一轮归因

### 4.1 默认 auto-JIT 的核心现象

在默认 auto-JIT 口径下，本地观察到：

- `bench_regex_compile()` 在少量调用后并不会自动进入 JIT
- 默认执行时间与目标线之间存在明显差距

进一步验证发现：

- 如果显式设置 `jit.compile_after_n_calls(1)`，`bench_regex_compile()` 能很快进入 JIT
- 一旦该函数进入 JIT，本地时间会明显向目标线靠近

这说明第一轮最强信号不是“H​IR 已经很差”，而是：

- 默认 auto-JIT 没有覆盖到这种“调用次数少、但单次调用内部存在明显大循环”的函数

### 4.2 HIR 与函数形状

第一轮抓到的关键结论：

- `bench_regex_compile()` 本体并不算特别重
- `regex_compile` 的 Python 级收益主要来自主计时函数本身被编译
- 这类函数具有典型 backedge / loop-heavy 形状

因此第一轮优化优先级从“steady-state HIR 微调”转向：

- auto-JIT 触发策略

## 5. 第一轮实现

### 5.1 第一版实现思路

在 `jitVectorcall()` 中增加一个窄规则：

- 仅在 `jit.auto()` 默认阈值口径下生效
- 如果当前函数的 code object 含有 backedge
- 则把默认 auto-JIT 的有效触发阈值从 `1000` 下调到 `2`

这样做的目标是：

- 不修改显式 `compile_after_n_calls(...)` 的语义
- 只改善“默认 auto-JIT 对 loop-heavy 函数反应太慢”的问题

### 5.2 第一版问题

第一版实现虽然能让 `bench_regex_compile()` 很快进入 JIT，但在真实 benchmark 脚本中暴露出一个新的风险：

- 过于激进的 backedge 早编译会把其它 loop-heavy 函数也提前拉进 JIT
- 在本地 `.venv` 验证中，这会触发 `HIRBuilder::tryInlineTupleGenexprCall()` 相关的编译期崩溃
- 单元测试之所以最初没有暴露这个问题，是因为测试只覆盖了 `bench_regex_compile()` 的窄路径，没有同时经过 `json` / `statistics` 等 stdlib 调用链

因此第一版结论是：

- “loop-heavy 函数应更早编译”这个方向是对的
- 但直接全局放开并不安全

## 6. 测试与验证

### 6.1 新增测试

新增测试文件：

- `cinderx/PythonLib/test_cinderx/test_jit_regex_compile_experiments.py`

覆盖两个行为：

1. `jit.auto()` 口径下，`bench_regex_compile()` 这类 loop-heavy benchmark 应能在少量调用后自动进入 JIT
2. 显式 `compile_after_n_calls(5)` 的语义不应被破坏

在第一版暴露 stdlib 崩溃后，又新增了第三个回归测试：

3. `jit.auto()` 在经过 `json` / `statistics` 等 stdlib 调用链后，仍应能安全跑完 `regex_compile`，并让 `bench_regex_compile()` 自动进入 JIT

### 6.2 本地测试结果

已验证：

```bash
PYTHONJITHUGEPAGES=0 UV_CACHE_DIR="$PWD/.uv-cache" PYTHONPATH=cinderx/PythonLib \
  .venv/bin/python -m unittest test_cinderx.test_jit_regex_compile_experiments
```

结果：

- `Ran 3 tests ... OK`

### 6.3 行为探针

本地额外确认到：

- `jit.auto()` 默认阈值仍显示为 `1000`
- 但 `bench_regex_compile()` 在少量调用后已经可以自动进入 JIT
- 显式 `compile_after_n_calls(5)` 的 loop 函数仍然表现为第 6 次调用后才进入 JIT

### 6.4 第二版收窄实现

为避免第一版把 stdlib loop-heavy 函数也提前拉进 JIT，第二版把规则进一步收窄为：

- 仍然只在默认 `jit.auto()` 阈值口径下生效
- 仍然要求函数具有 backedge
- 但只对 **非 stdlib 的 Python 代码** 启用“2 次即早编译”策略

涉及文件：

- `cinderx/Jit/pyjit.cpp`

这样做的效果是：

- `bm_regex_compile/run_benchmark.py` 中的 `bench_regex_compile()` 仍能提前进入 JIT
- `json`、`statistics` 等 stdlib loop-heavy 函数不会被同样激进地提前编译
- 第一版暴露的 `tryInlineTupleGenexprCall()` 崩溃不再复现

### 6.5 本地 benchmark 结果

基于当前源码、项目 `.venv`、`PYTHONJITHUGEPAGES=0` 的本地近似结果：

- `default auto`: `79.275ms`
- `compile_after_n_calls(1)`: `79.831ms`
- `force_compile(bench_regex_compile)`: `89.324ms`

这说明：

1. 真正有效的是“让默认 auto 足够早地**自然**编到 `bench_regex_compile()`”
2. 当前默认 auto 路径已经能把本地近似时间压到目标线 `84ms` 以下
3. 单独 `force_compile()` 反而不如默认 auto 路径，说明收益并不来自“手工强编”本身，而来自更贴近真实执行形状的自然触发

### 6.6 当前剩余热点

在当前默认 auto 路径下，本地还能看到一处显著 deopt：

- `re/_parser.py:171`
- `SubPattern.__getitem__`
- `BinaryOp / UnhandledException`

但这条 deopt 并没有阻止本地近似结果达到目标线以下，因此当前优先级低于正式环境复核。

### 6.7 规则影响范围

这轮第一阶段的实现并不是 `regex_compile` 专属特判，而是一条收窄过的通用 auto-JIT 准入规则。

它的实际生效条件是：

1. 当前仍处于默认 `jit.auto()` 阈值口径
   - 即默认 auto 阈值仍为 `1000`
2. 目标函数字节码中存在 backedge
   - 通常对应明显的 `for` / `while` 循环
3. 目标函数不在 stdlib 中

因此，这条规则不会只影响 `regex_compile`，而会影响一类更一般的函数形状：

- 非 stdlib
- 调用次数少
- 但单次调用内部有明显循环

典型潜在影响场景包括：

- benchmark 主入口函数
- 一次性批处理脚本中的主循环
- 命令行工具里“调用不多但单次很重”的 Python 函数
- 第三方纯 Python 库中的 loop-heavy helper

它不会影响的场景包括：

- stdlib 函数
- 没有循环的函数
- 显式调用 `compile_after_n_calls(...)` 的路径
- `force_compile()` 等手工控制路径

因此，这条规则的收益与风险也都具有一定通用性：

- 正面：
  - 能让“少调用但单次很重”的函数更早进入 JIT
- 风险：
  - 可能提前编译本来不一定值得编译的 loop-heavy 函数
  - 会把 `site-packages` 中的纯 Python 第三方库也视为“非 stdlib”处理
  - 可能暴露原先被“晚编译”掩盖的编译器问题

这也是为什么第一轮最终要额外收窄到“非 stdlib”范围，并用独立测试验证：

- 显式 `compile_after_n_calls(...)` 语义不被破坏
- stdlib 调用链不会再次触发此前的崩溃路径

## 7. 当前结论

第一轮已经确认：

1. `regex_compile` 的一个主问题确实是默认 auto-JIT 触发过慢
2. loop-heavy 的函数值得比通用函数更早进入 JIT
3. 这一类优化需要收窄到非 stdlib 代码，才能避免把已知不稳的 stdlib 路径提前拉进 JIT
4. 在当前本地近似口径下，收窄后的实现已经把 `regex_compile` 压到约 `79ms`，优于目标线 `84ms`

## 8. 当前限制

本轮仍有两个限制：

1. 本地时间仍存在一定波动，最终结论仍要以 ARM / Docker 正式复核为准
2. 当前收益已经满足本地目标，但还不能据此直接宣称正式环境也一定优于 `stock CPython 3.14.0 + JIT`

## 9. 下一步建议

下一步建议按这个顺序推进：

1. 在 ARM / Docker 环境复核这轮改动对 `regex_compile` 的正式收益
2. 如果正式收益已经足够，则停止继续做高风险优化
3. 如果正式环境仍未达标，再回到 steady-state 路径，优先看：
   - `re/_parser.py` 相关 deopt
   - `re.compile()` 调用边界
   - 仍可能残留的调用链开销

第二轮的进一步归因已经单独整理在：

- `docs/superpowers/regex_compile/reports/2026-03-23-regex-compile-second-pass-report.md`
