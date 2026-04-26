# CPython 3.14 + CinderX 官方优化研究

这组文档保存 2026 年 2/3/4 月官方 `meta/main` 上和 `CPython 3.14 + CinderX JIT` 性能优化相关的 commit 阅读笔记。它的用途是学习和复盘官方方法论，不是直接提交 upstream PR。

## 阅读入口

- [Commit index](commits/index.md): 按 commit 列出日期、作者、主题、层次和阅读重点。
- [2 月优化](months/2026-02.md): frame、inline cache、LIR opcode、AArch64 bring-up、benchmark 扩展。
- [3 月优化](months/2026-03.md): specialized opcode 默认开启、numeric unbox、container fast path、LIR lowering。
- [4 月优化](months/2026-04.md): postgen rewrite、ARM64 codegen quality、compact long、PrimitiveBox/IntConvert。

## 按 layer 阅读

- [Bytecode intake](layers/bytecode-intake.md): CPython 3.14 specialized opcode / inline cache 如何进入 CinderX。
- [HIR simplify](layers/hir-simplify.md): unbox、compact long、PrimitiveBox、PrimitiveConvert、constant folding。
- [LIR / codegen](layers/lir-codegen.md): postalloc/postgen rewrite、memory input、constant pool、call input。
- [ARM64](layers/arm64.md): AArch64 bring-up、branch/call lowering、hot/cold splitting、scratch register。
- [Benchmarks](layers/benchmarks.md): nbody、binary-trees、spectral-norm、fastmark、pyperformance 关联 workload。

## 和本轮实验分支的对应关系

| 官方方法 | 对应实验分支 |
| --- | --- |
| 消费 CPython 3.14 specialized opcode | `codex/opt-call-py-exact-args-314-20260427`, `codex/opt-for-iter-list-tuple-314-20260427` |
| 调整 guard granularity | `codex/load-global-module-builtin-314-20260426` |
| container fast path 风险验证 | `codex/negative-store-subscr-list-int-314-20260427` |
| ARM64 call/address lowering | `codex/opt-arm64-load-addr-bl-20260427` |
| 系统找未消费 type info | `codex/type-info-coverage-audit-20260426` |

## 推荐阅读顺序

1. 先读 [Commit index](commits/index.md)，建立 commit 地图。
2. 再读 [Bytecode intake](layers/bytecode-intake.md)，理解为什么 CPython 3.14 specialization 是当前 CinderX 优化入口。
3. 读 [HIR simplify](layers/hir-simplify.md)，看官方如何把 type info 转成 primitive/unbox path。
4. 读 [LIR / codegen](layers/lir-codegen.md) 和 [ARM64](layers/arm64.md)，理解后端 rewrite 为什么重要。
5. 最后回到本轮实验分支，对照哪些方法已经被复现，哪些还值得继续试。
