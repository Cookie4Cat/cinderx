# fc137cd3 / a689d5a0 / 7a8308dd: benchmark type annotation series

## 元信息

- `fc137cd3eef62e304b6a74ef809fc87294710d11`, 2026-03-17, Alex Malyshev, `Add types to the base richards benchmark`
- `a689d5a0e9132442e00f535e4379a943592cc0a0`, 2026-03-24, Alex Malyshev, `Add types to the nbody benchmark`
- `7a8308dd500d1c7e0ab5e17929a0a29c07667e02`, 2026-03-25, Alex Malyshev, `Add types to binary_trees and spectral_norm benchmarks`
- Layer: benchmark / type annotations / JIT facts
- Changed files:
  - `cinderx/benchmarks/richards.py`
  - `cinderx/benchmarks/nbody.py`
  - `cinderx/benchmarks/binary_trees.py`
  - `cinderx/benchmarks/spectral_norm.py`

## Commit Message 要点

这些 commit 给 benchmark 加 type annotations。`a689d5a0` 明确说 annotations 不应影响 CPython interpreter performance，但在特定情况下可以帮助 CinderX。`fc137cd3` 还解释 richards variants 的用途：

- `richards.py`: CinderX JIT
- `richards_static_basic.py`: CinderX JIT + Static Python
- `richards_static.py`: CinderX JIT + Static Python + Unboxed Integers

## 优化形状

annotations 本身不执行优化。它们提供 facts：

```text
benchmark source annotations
  -> Static Python / CinderX sees more type info
  -> HIR builder emits more precise types
  -> simplify pass can trigger typed/unboxed paths
```

这说明官方在做两件事：一方面优化 compiler，另一方面让 benchmark 能暴露 compiler 在 typed code 上的潜力。

## 代码阅读点

### `richards.py`

看 class fields、method argument、return types。Richards 适合观察 object dispatch 和 integer-heavy control flow。

### `nbody.py`

看 `advance(bodies: list[Body], dt: float, n_bodies: int)` 这类 annotations。它直接支持 float exact、list element、int loop bound 等 facts。

### `binary_trees.py`

annotations 帮助区分 node object、depth integer、recursive return value。适合观察 allocation/recursion 下 type facts 是否能留住。

### `spectral_norm.py`

annotations 对 nested numeric loop 和 list operations 有帮助，可能影响 call specialization 和 list indexing。

## 测试与 measurement

这些是 benchmark changes，不是 compiler tests。验证方式应是：

- CPython interpreter performance 基本不变；
- CinderX JIT HIR dump 更 typed；
- benchmark runtime 或 JIT stats 改善；
- compiled function count 和 deopt rate 没异常。

## ARM64 启发

ARM64 backend 只能优化它看到的 typed HIR。annotations 是让 benchmark 更容易进入 typed HIR 的方式之一。后续如果某个 ARM64 optimization 只在 annotated benchmark 上有效，就要判断真实业务代码是否也有同等 type facts。

## 后续追问

- benchmark annotations 是否过度理想化，和真实 Python code 差距多大？
- unboxed integer variant 是否应该变成 feature flag，而不是多个文件？
- type annotations 对 CPython 3.14 specialized opcode support 的关系是什么？
- HIR stats 能否显示 annotations 前后 type precision 变化？
