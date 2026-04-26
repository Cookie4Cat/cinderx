# CinderX 3.14 官方优化研究

这组笔记只看官方 `meta/main`，时间范围是 `2026-02-01` 到 `2026-04-30`，目标环境是 `CPython 3.14 + CinderX`。主体用中文，关键 compiler/JIT/IR/ARM64 术语保留英文，方便直接对照源码和 commit message。

核心目标：把上游 2/3/4 月的重要优化拆成可以复用的方法论，尤其关注哪些优化虽然不是 ARM64-specific，但能让 ARM64 的 CinderX 变快。

## 推荐阅读路线

1. 先读 [HIR simplify 横向总结](layers/hir-simplify.md)：理解 CinderX 如何把 boxed Python semantics 变成 typed primitive HIR。
2. 再读 [LIR/codegen 横向总结](layers/lir-codegen.md)：看 postalloc/postgen rewrite 如何减少 helper call、scratch register 和多余 instruction。
3. 然后读 [ARM64 backend 横向总结](layers/arm64.md)：把 ARM64 的 immediate、branch、memory operand、scratch register 限制串起来。
4. 最后读 [benchmark 总结](benchmarks.md)：知道这些优化背后的 workload target。

## Commit Review Index

### P0: 必读主线

- [5fec65f4 - Enable specialized opcode support by default](commits/5fec65f4-specialized-opcodes-default.md)
- [53f4fc0f - Specialize float operations further](commits/53f4fc0f-specialize-float-ops.md)
- [d70dcb5a - Unbox float TrueDivide and mixed float/int ops](commits/d70dcb5a-unbox-float-truedivide-mixed-int.md)
- [b1945d88 - Simplify Float BinaryOp Long with compact long checks](commits/b1945d88-float-long-compact.md)
- [54cb7a83 - Specialize list StoreSubscr](commits/54cb7a83-list-store-subscr.md)
- [44e26d22 - Inline StoreArrayItem lowering](commits/44e26d22-store-array-item-direct.md)
- [5029beec - Move frame linking from assembly to LIR](commits/5029beec-frame-linking-lir.md)
- [April postgen/postalloc rewrite series](commits/april-postgen-postalloc-rewrites.md)
- [ARM64 branch simplification series](commits/arm64-branch-simplification-series.md)

### P1: 重要支撑

- [5bfab630 - Enable lightweight frames](commits/5bfab630-lightweight-frames.md)
- [3d414b95 - Enable inline caching for plain instance attributes](commits/3d414b95-instance-attr-inline-cache.md)
- [14b48134 / 8b98266a - subword move/load/store support](commits/14b48134-8b98266a-subword-size.md)
- [659606ab - Move frame loading to dedicated opcode](commits/659606ab-load-frame-opcode.md)
- [8635acf5 - Replace unlink frame generation with LIR](commits/8635acf5-unlink-frame-lir.md)
- [d5fa88c3 - Don't generate Decrefs for immortal types](commits/d5fa88c3-no-decref-immortal.md)
- [e9968ea2 - Fuse compare + CondBranch](commits/e9968ea2-compare-condbranch-fusion.md)
- [3c88c653 - Inline Py_IncRef/Py_DecRef for free-threading](commits/3c88c653-inline-refcount-ft.md)
- [April HIR primitive simplification series](commits/april-hir-primitive-series.md)

### P2: ARM64 enablement 与 measurement

- [d37552a7 - aarch64 support](commits/d37552a7-aarch64-support.md)
- [afc7de79 - Make hot/cold splitting work on ARM](commits/afc7de79-hot-cold-arm.md)
- [59062ec2 - Direct switch dispatch for aarch64](commits/59062ec2-aarch64-dispatch-switch.md)
- [bef6366b / ac92d1fa - load_addr and bl(imm)](commits/arm64-load-addr-bl-series.md)
- [6e5e3716 - nbody/binary-trees/spectral-norm benchmarks](commits/6e5e3716-benchmark-suite.md)
- [benchmark type annotation series](commits/benchmark-type-annotation-series.md)
- [343c8185 / c6fdb7b9 - fastmark support](commits/fastmark-support.md)

## 优化分类

- HIR simplification: typed specialization、unbox、constant fold、compact long guards、primitive box/convert simplification。
- LIR/codegen lowering: 把 helper call 改成 direct instruction，把 hidden scratch register 需求显式化。
- Frame/trampoline: 把 handwritten assembly 移到 LIR，让 regalloc/postalloc 能参与优化。
- ARM64 backend shaping: 围绕 immediate range、branch range、memory operand 限制和 scratch register pressure 调整 IR/LIR 形状。
- Benchmarks: 用 richards、nbody、binary-trees、spectral-norm、fannkuch、fastmark、JIT compile speed benchmark 标定优化方向。
