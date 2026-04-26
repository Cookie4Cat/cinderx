# e9968ea2: Fuse compare + CondBranch

## 元信息

- Commit: `e9968ea2f43cda723b9cd6865f758c3f7c7f7d5d`
- Date: 2026-03-19
- Author: Alex Malyshev
- Reviewer: Alper Yoney
- Layer: LIR postalloc / branch lowering
- Changed file:
  - `cinderx/Jit/lir/postalloc.cpp`

## Commit Message 要点

当 `CondBranch` 的 input 来自同一个 basic block 中的 compare instruction，且中间没有 clobber flags 的 instruction，可以把旧的：

```text
cmp + setcc + test + je
```

改成：

```text
cmp + jcc
```

这减少 materialized boolean 和额外 test。

## 优化形状

post-register-allocation rewrite `doRewriteCondBranch` 会向前扫描，寻找可 fuse 的 compare。找到后，使用已有 `compareToBranchCC()` 基础设施，把 branch condition 直接映射成 conditional branch opcode。

这里选择 postalloc 是合理的：需要知道最终 instruction order 和是否有 flags-clobbering instruction。

## 代码实现 Review

阅读 `postalloc.cpp` 时重点看：

- 如何从 `CondBranch` 往前找 compare；
- 哪些 instruction 会 clobber flags；
- compare kind 如何映射到 branch condition；
- 找不到 fusible compare 时是否保持旧行为。

commit message 提到 `setcc` materialization 仍会 emit，但如果 CBool result 没其他 uses，就变成 dead code。完全删除它需要 liveness 信息确认 output register 不 live-out。

## 测试与 correctness

正确性关键是 flags：

- compare 和 branch 之间不能有 clobber flags；
- branch condition 必须和原 compare+test 完全等价；
- materialized CBool 如果还有其他 use，不能删除；
- basic block 边界不能跨越。

## ARM64 启发

虽然 commit message 用 `jcc` 这类 x86 terminology，这个思路对 ARM64 一样重要。后续 ARM64 branch series 把 compare/branch 进一步变成 `tbnz`、`cbnz`。共同目标都是避免先 materialize bool 再 branch。

## 后续追问

- 能否把 dead `setcc` 删除？需要 regalloc liveness。
- ARM64 上对应 pattern 是否也能在 postalloc 做更多 fusion？
- CBool materialization 是否是其他 guard/branch 的普遍成本？
- benchmark 中 branch-heavy workload 是否能看到收益？
