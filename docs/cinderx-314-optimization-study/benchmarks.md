# Benchmark 与 Measurement

## 为什么 benchmark 文档重要

2/3/4 月这些优化不是凭空出现的。官方不断补 benchmark，是为了把 JIT 的优化方向从 micro pattern 拉回真实 workload。学习 commit 时，如果不知道对应 workload，很容易只看到“改了一个 pass”，看不到它为什么值得做。

## 2 月 benchmark baseline

`59b89cd0` 添加 `richards.py`，这是早期 CinderX JIT benchmark baseline。Richards 适合观察 object/message/task scheduling 风格的 Python workload。

`67534431` 添加 Static Python richards variants:

- `richards.py`: CinderX JIT
- `richards_static_basic.py`: CinderX JIT + Static Python
- `richards_static.py`: CinderX JIT + Static Python + Unboxed Integers

这个拆分很有价值，因为它把 JIT、Static Python、unboxed integers 的贡献分开观察。

`6e5e3716` 添加三个更有针对性的 benchmark:

- `nbody`: tight floating-point loops、attribute access、`dist_sq ** 0.5`、list iteration。
- `binary_trees`: object allocation、recursive calls、GC pressure。
- `spectral_norm`: nested loops、function call overhead、list operations。

commit message 明确说当时 `nbody` 是 regression，因为 CinderX 还没 targeted floating-point operations。这直接解释了后续 `53f4fc0f`、`d70dcb5a`、`b1945d88`。

## 3 月 benchmark annotations

`fc137cd3`、`a689d5a0`、`7a8308dd` 给 richards/nbody/binary_trees/spectral_norm 添加 type annotations。message 说这些 annotations 不应影响 CPython interpreter performance，但可以帮助 CinderX in specific circumstances。

这说明 annotations 的作用不是“让 Python 自己更快”，而是让 JIT/Static Python 拿到更多 type facts，进而触发 HIR simplify。

`2befa93b` 添加 `fannkuch-redux`。后续 `54cb7a83` 的 commit message 明确提到 fannkuch hot path 中 4/5 个 `StoreSubscr` 被 specialized，所以 fannkuch 是 list store specialization 的目标 workload。

`3f1b6d84` 和 `900f15f3` 围绕 PT2 compile benchmark 和 JIT metrics，补 compilation/perf measurement 维度。

## 4 月 fastmark

`343c8185` vendors Sam Gross 的 fastmark，它跑 pyperformance subset，但避免 pyperformance framework overhead。

`c6fdb7b9` 添加 `--cinderx` option，传入时启用 JIT-auto。这个很适合后续我们做 smoke benchmark：既比单个 microbenchmark 更真实，又比完整 pyperformance 轻。

## workload 与优化映射

- `nbody`: float unbox、sqrt、mixed float/int、attribute access。
- `fannkuch`: list store-subscript、bounds/index checks、tight loops。
- `binary_trees`: allocation、refcount、GC、recursive call overhead。
- `spectral_norm`: function call overhead、list ops、nested loops。
- `richards`: typed object workload、Static Python/unboxed integer comparison。
- `fastmark`: mixed real-world-ish smoke suite。
- JIT compile speed benchmark: compile-time/codegen dispatch/postgen pass overhead。

## 明天学习建议

不要孤立读 commit。建议每篇 commit 都问：

- 它对应哪个 benchmark hot pattern？
- 它是增加 facts、改变 HIR shape，还是改 backend lowering？
- 它的测试是 correctness test、HIR golden test、LIR golden test，还是 benchmark-only signal？
- 如果要验证 ARM64 收益，应选哪个 benchmark？

这样读出来的是优化方法论，而不只是 commit 摘要。
