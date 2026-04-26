# 44e26d22: Inline StoreArrayItem LIR lowering

## 元信息

- Commit: `44e26d22c0c2eedcc06fd29407c496aa3af99537`
- Date: 2026-03-23
- Author: Alex Malyshev
- Reviewer: Matt Page (`mpage`)
- Layer: LIR lowering / runtime helper removal
- Changed files:
  - `cinderx/Jit/jit_rt.cpp`
  - `cinderx/Jit/jit_rt.h`
  - `cinderx/Jit/lir/generator.cpp`

## Commit Message 要点

这个 commit 把 `StoreArrayItem` 的 LIR lowering 从 runtime helper call 改成 direct memory store。原来每种 element type 都有一个 helper，例如 `JITRT_SetObj_InArray`、`JITRT_SetI8_InArray` 等，它们本质上只做一次 array store。

旧路径：

```text
StoreArrayItem
  -> call JITRT_Set*_InArray(arr, val, idx)
```

新路径：

```text
StoreArrayItem
  -> kMove value -> OutInd{base, idx, scale, offset, data_type}
```

如果 index 在 compile time 已知，还能折叠成 `OutInd{base, constant_offset}`。

## 代码实现 Review

### runtime helper 删除

`jit_rt.cpp/h` 删除了一组 `JITRT_Set*_InArray` helper。它们包括 I8/U8/I16/U16/I32/U32/I64/U64/Object variants。删除这些 helper 是这个 commit 的信号：官方确认这类 store 不需要 C helper 包装。

### `lir/generator.cpp`

`Opcode::kStoreArrayItem` 的 lowering 改成：

- 从 HIR operand 拿 `ob_item`、`idx`、`value`；
- 根据 HIR type 算 `sizeBytes`；
- 用 `hirTypeToDataType` 得到 LIR data type；
- 构造 `OutInd{ob_item, idx, sizeBytes, 0, dt}`；
- 如果 `idx` 有 int spec，提前计算 `scaled_offset`；
- append `kMove` 到 memory output。

这和 `LoadArrayItem` 的 lowering 对齐：load 是 `Move Ind -> reg`，store 是 `Move value -> OutInd`。

## 优化收益

这个优化消掉了 helper call 的完整成本：

- call/ret；
- argument marshalling；
- caller-save register spills；
- helper symbol/address materialization；
- indirect call 相关 branch predictor 成本；
- helper 内部的一次 trivial store。

对 tight list/array update loop，这类 call removal 往往比单条指令优化更大。

## 测试与 correctness

这个 commit 没有大规模新增 HIR test，因为 HIR shape 已由前序 `54cb7a83` 覆盖。这里重点在 LIR lowering correctness：

- element size 是否正确；
- signed/unsigned store 是否只关心 bit width；
- object pointer store 的 data type 是否正确；
- compile-time index offset 是否按 `idx * sizeBytes` 计算；
- ARM64/x86 memory operand 是否都能合法 encode。

## 和 CPython 3.14 的关系

CPython 3.14 specialization 帮助前端产生更多 `StoreArrayItem`。这个 commit 则让已经产生的 `StoreArrayItem` 真正变便宜。前端和后端是串联关系：只有 HIR specialize + LIR direct lowering 都在，完整收益才出现。

## ARM64 启发

ARM64 上 direct memory store 未必总是“一条指令”，因为 addressing mode 没有 x86 丰富。即便如此，避免 C helper call 仍然非常值得。后续 `8aa963d4` 的 memory input rewrite 就是在补 ARM64 operand shape 限制。

学习时可以特别看：

- `OutInd` 在 AArch64 后端能 encode 哪些 base/index/scale；
- 不能 encode 时是否需要 temporary register；
- store 的 data type 是否触发 subword store variants；
- direct store 是否增加 register pressure。

## 后续追问

- 对 object store，refcount insertion 是否总能在 store 前后放对 INCREF/DECREF？
- 如果 ARM64 需要 address materialization，是否还有机会 fuse index scaling？
- known constant index 的 fast path 在 benchmark 中命中率如何？
- 是否可以把更多 tiny helper calls 用同样方法 direct lower？

## 分类

- Primary layer: LIR lowering
- Runtime pattern: array/list backing-store write
- Correctness mechanism: HIR type controls store width; refcount handled by surrounding IR
- Performance mechanism: helper call removal, direct memory store
- ARM64 impact: 高，但依赖 AArch64 addressing mode 和 postalloc rewrite 支撑
