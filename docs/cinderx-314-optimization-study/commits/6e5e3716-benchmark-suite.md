# 6e5e3716: Add nbody, binary-trees, spectral-norm benchmarks

## 元信息

- Commit: `6e5e3716f6cb916dfad95225f1daef0f0eaea723`
- Date: 2026-02-25
- Author: Alex Malyshev
- Reviewer: Jacob Bower
- Layer: benchmark / workload coverage
- Changed files:
  - `cinderx/benchmarks/binary_trees.py`
  - `cinderx/benchmarks/nbody.py`
  - `cinderx/benchmarks/spectral_norm.py`

## Commit Message 要点

这个 commit 新增三个 benchmark，每个瞄准不同性能维度：

- `nbody`: N-body gravitational simulation，覆盖 tight numerical loops、floating-point arithmetic、repeated attribute access。
- `binary-trees`: binary tree construction/traversal，覆盖 allocation pressure、recursive calls、GC paths。
- `spectral-norm`: compute-bound nested loops，覆盖 function call overhead 和 list operations。

message 还明确说：这些 benchmark 当时并没有展示明显 JIT wins。`binary-trees` 小幅提升；`nbody` 是 regression，因为 JIT 还没 targeted floating point operations。

## 为什么这个 commit 重要

这不是普通“加 benchmark”。它给后续优化提供了问题定义：

- `nbody` 暴露 float path 弱；
- `binary_trees` 暴露 allocation/refcount/GC pressure；
- `spectral_norm` 暴露 nested loop/function call/list ops；
- 后续 `53f4fc0f`、`d70dcb5a`、`b1945d88` 都能和 `nbody` 对上。

## benchmark 代码阅读点

### `nbody.py`

关注：

- `dx * dx + dy * dy + dz * dz`
- `dist_sq ** 0.5`
- `dt / (dist_sq * dist)`
- repeated `body.x`/`body.vx` attribute access

它是 float unbox、sqrt、mixed float/int、attribute cache 的集合。

### `binary_trees.py`

关注：

- 高频 object allocation；
- recursion；
- tree traversal；
- temporary object lifetime。

它适合观察 refcount insertion、allocator、frame overhead。

### `spectral_norm.py`

关注：

- nested loops；
- function call overhead；
- list indexing/list construction；
- numeric operations。

它介于 nbody 和 richards 之间，既有 numeric，又有 Python-level call overhead。

## 和后续 commits 的关系

- `53f4fc0f`: 针对 float operations；
- `5fec65f4`: specialized opcode support 默认打开，message 用 nbody 给数据；
- `d70dcb5a`: true-divide 和 mixed float/constant int；
- `a689d5a0`、`7a8308dd`: 给这些 benchmarks 加 annotations；
- `b1945d88`: runtime compact long mixed float/int。

## ARM64 启发

ARM64 优化要避免只看 microbench。`nbody` 可以作为 float path probe，`binary_trees` 作为 refcount/allocation probe，`spectral_norm` 作为 call/list/numeric mixed probe。

后续如果要比较 ARM64 优化，建议每次至少记录：

- runtime；
- compiled functions count；
- JIT bailout/failure count；
- generated code size；
- helper call frequency。

## 后续追问

- `nbody` regression 在启用 specialized opcode 后是否完全消失？
- ARM64 上 `nbody` 是否仍受 FP conversion/boxing 限制？
- `binary_trees` 的小幅 win 来自 frame、allocation 还是 call overhead？
- 这些 benchmark 是否需要 warmup/iteration 控制以适配 JIT？
