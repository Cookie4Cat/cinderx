# 5fec65f4: Enable specialized opcode support by default

## 元信息

- Commit: `5fec65f41650505587804c0dbce88ba0fda1cb0d`
- Date: 2026-03-12
- Author: Alex Malyshev
- Reviewer: Dino Viehland
- Layer: config / CPython 3.14 adaptive specialization / HIR builder input facts
- Changed file:
  - `cinderx/Jit/config.h`

## Commit Message 要点

这个 commit 只改了 `config.h` 一行，但影响很大：CinderX JIT 默认启用 specialized opcode support。commit message 用 `nbody.py` 给了非常强的 signal:

```text
PYTHONJITSPECIALIZEDOPCODES=0: 15.774s ± 0.239s
PYTHONJITSPECIALIZEDOPCODES=1:  9.630s ± 0.146s
```

这说明瓶颈不是某一条 ARM64 instruction，而是 JIT 能不能从 CPython adaptive interpreter 拿到足够强的 specialization facts。没有这些 facts，后面的 `FloatExact`、`LongExact`、list exact、method/value specialization 都很难触发。

## 优化形状

这个 commit 的优化形状比较“上游”：

```text
CPython 3.14 adaptive/specialized bytecode
  -> CinderX specialized opcode support enabled by default
  -> HIR builder gets stronger type/value facts
  -> simplify pass can emit primitive/specialized HIR
  -> LIR/backend sees fewer generic PyNumber/PyObject helper calls
```

它本身不添加新的 HIR opcode，不改变某个 lowering rule，但会改变真实 workload 中已有 rules 的命中率。`53f4fc0f` 和 `d70dcb5a` 的 float unbox path 就是典型受益者：只有知道两边是 float，simplifier 才能把 boxed binary op 变成 `DoubleBinaryOp`。

## 代码实现 Review

改动集中在 `cinderx/Jit/config.h`。需要重点看配置项的默认值变化，而不是代码量。这个 commit 也提醒我们：JIT 优化有时不是“新写一个 pass”，而是把已经存在但默认关闭的事实来源打开。

源码阅读时建议顺着这条线看：

- `config.h`: specialized opcode support 的默认值。
- HIR builder 中 CPython opcode 到 CinderX HIR 的映射。
- `simplify.cpp`: 哪些 optimization case 依赖 `TFloatExact`、`TLongExact`、object spec、exact container type。
- benchmark message 中的 `nbody.py`: 为什么 float-heavy workload 对 specialized facts 敏感。

## 测试与验证信号

这个 commit 没有新增 RuntimeTests，因为它是 config default flip。验证主要靠 benchmark 和已有 specialized opcode path 的 tests。对学习来说，最重要的是 commit message 里的 hyperfine 数据：它说明默认开关改变了真实 workload 的优化覆盖面。

如果后续我们自己做实验，应该至少比较：

- JIT off / JIT on
- specialized opcode support off / on
- ARM64 和 x86_64 的相同 benchmark
- HIR dump 中 `FloatBinaryOp`、`DoubleBinaryOp`、specialized load/store 的出现频率

## CPython 3.14 关系

这篇和 `CPython 3.14 + CinderX` 的关系非常直接。CPython 3.14 的 adaptive interpreter 会把许多 generic bytecode 变成 specialized opcode；CinderX 如果不消费这些 specialization，就会丢掉最便宜的类型信息来源。

换句话说：这不是“让 CinderX 发明类型推断”，而是“让 CinderX 尊重 CPython 已经观测到的 runtime facts”。

## ARM64 启发

ARM64 优化不能只在 backend 做。假设 HIR 还是 generic `BinaryOp`，ARM64 backend 最终只能生成 helper call；如果 HIR 已经是 `DoubleBinaryOp`，backend 才能生成 `kFadd`/`kFmul`/`kFdiv`。所以这个 config commit 是 ARM64 performance 的前端入口。

一个可行方法论：

1. 先确认 specialized opcode support 是否打开。
2. 用 HIR dump 看 hot functions 是否拿到了 exact types。
3. 如果没有，先补 builder/specialization consumption。
4. 如果已经有，再看 ARM64 lowering 是否有多余 moves、scratch register、branch sequence。

## 后续追问

- 哪些 CPython 3.14 specialized opcodes 还没有被 CinderX HIR builder 消费？
- specialized opcode support 打开后，deopt/guard 失败率是否上升？
- ARM64 上 `nbody` 的提升来自 HIR shape 改善，还是 backend codegen 本身也有变化？
- 是否应该为常见 specialized opcode 建专门的统计，帮助我们找“CPython 已经知道，但 CinderX 没利用”的 gap？

## 分类

- Primary layer: config / specialization input
- Runtime pattern: all specialized CPython hot bytecode
- Correctness mechanism: existing guards/deopt paths
- Performance mechanism: increase hit rate of typed HIR simplification
- ARM64 impact: 间接但关键，决定 backend 能看到 primitive work 还是 generic helper call
