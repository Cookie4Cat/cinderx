# 343c8185 / c6fdb7b9: fastmark support

## 元信息

- `343c8185dbb7843ab58085ec760b373e2a99cb37`, 2026-04-22, Matt Page, `Add fastmark to benchmarks`
- `c6fdb7b90264ad64bf4a5f3bcbc8622ad85ce207`, 2026-04-22, Matt Page, `Add cinderx JIT support to fastmark`
- Reviewer: Alex Malyshev
- Layer: benchmark / pyperformance subset / JIT measurement
- Changed file:
  - `cinderx/benchmarks/fastmark.py`

## Commit Message 要点

`343c8185` vendors Sam Gross 的 fastmark。fastmark 跑 pyperformance subset，但避免 pyperformance framework 的 overhead。`c6fdb7b9` 添加 `--cinderx` option，传入时启用 JIT-auto。

## 为什么重要

单个 microbenchmark 容易过拟合。fastmark 提供一个更接近真实 Python workload mix 的轻量 benchmark suite。对 CinderX 这种 JIT，既要看 targeted benchmark，也要看 mixed benchmark 防 regression。

## 代码实现 Review

阅读 `fastmark.py` 时重点看：

- benchmark subset 如何选择；
- runner overhead 是否低；
- `--cinderx` 是否只负责启用 JIT-auto；
- JIT warmup 和 measurement iteration 是否清晰；
- 是否有方式输出 per-benchmark results。

`--cinderx` 不应混入额外行为，否则很难判断性能差异来自 JIT 还是 runner config。

## 测试与 measurement

fastmark 不是 correctness test。它适合作为：

- smoke performance suite；
- regression detector；
- ARM64/x86_64 横向比较；
- JIT on/off 快速对比。

它不替代 targeted benchmarks。比如 float path 仍要看 `nbody`，list store 仍要看 `fannkuch`。

## ARM64 启发

ARM64 优化尤其需要 fastmark 这类 mixed suite。某个 ARM64 rewrite 可能让 nbody 变快，却让 branch-heavy 或 allocation-heavy workload 变慢。fastmark 能更早暴露这种 tradeoff。

## 后续追问

- fastmark subset 里哪些 benchmark 对 CinderX 最敏感？
- `--cinderx` 是否记录 compiled function count？
- ARM64 上 fastmark 的 variance 如何？
- 是否应加 per-benchmark JIT stats 输出，帮助定位收益来源？
