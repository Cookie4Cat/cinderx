# 54cb7a83: Specialize list StoreSubscr

## 元信息

- Commit: `54cb7a83a5fc0a484da2dde4e86813824eba68d8`
- Date: 2026-03-23
- Author: Alex Malyshev
- Reviewer: Matt Page (`mpage`)
- Layer: HIR Simplify / list operation specialization
- Changed files:
  - `cinderx/Jit/hir/simplify.cpp`
  - `cinderx/RuntimeTests/hir_tests/simplify_test.txt`

## Commit Message 要点

这个 commit 优化 `list[int] = value`。原来 `StoreSubscr` 会走 generic `PyObject_SetItem`，里面要做 container type dispatch、index conversion、mapping/sequence protocol 选择。现在 JIT 在已知 container 是 `ListExact`、index 是 `LongExact` 时，直接拆成：

```text
IndexUnbox
CheckSequenceBounds
LoadField(ob_item)
LoadArrayItem(old value)
StoreArrayItem(new value)
```

commit message 还给了 fannkuch benchmark 信号：hot path 里 5 个 `StoreSubscr` 有 4 个被 specialized，剩下一个缺少 container parameter 的 `ListExact` type guard。

## 优化形状

旧路径：

```text
StoreSubscr(list, idx, value)
  -> PyObject_SetItem(list, idx, value)
  -> CPython generic dispatch
```

新路径：

```text
UseType<ListExact>(container)
UseType<LongExact>(index)
IndexUnbox(index)
IsNegativeAndErrOccurred
CheckSequenceBounds(container, index)
LoadField(container.ob_item)
LoadArrayItem(old_value)
StoreArrayItem(ob_item, index, value, old_value)
```

注意这里还没有完全去掉 helper call 的所有成本，因为 `StoreArrayItem` 的 LIR lowering 在这个 commit 当时仍然可能走 helper；真正 direct memory store 是后续 `44e26d22`。

## 代码实现 Review

核心函数是 `simplifyStoreSubscr`。这个 commit 先把原来的 operands 命名成：

- `container`
- `index`
- `value`

然后保留原有 dict exact path，再新增 list exact path。

list path 的关键点：

- `container->isA(TListExact)` 保证是精确 list，不处理 subclass；
- `index->isA(TLongExact)` 后 emit `IndexUnbox`；
- `IsNegativeAndErrOccurred` 保持 Python index conversion 的 error semantics；
- `CheckSequenceBounds` 处理负索引调整和越界；
- `LoadField(..., ob_item)` 直接拿 list backing array；
- `LoadArrayItem` 先取 old value；
- `StoreArrayItem` 写入新 value。

最值得注意的是 old value。注释说：load old value 是为了让 refcount insertion pass 能在 store 后 DECREF old value；同时把 old value 作为 `StoreArrayItem` 的 container operand 以避免 DCE 把它删掉。这是 compiler pass 之间配合的典型细节。

## 测试实现 Review

`simplify_test.txt` 增加 expected HIR。学习时应看 expected output 中是否出现：

- `UseType<ListExact>`
- `UseType<LongExact>`
- `IndexUnbox`
- `CheckSequenceBounds`
- `LoadField ob_item`
- `LoadArrayItem`
- `StoreArrayItem`

这类 test 比 behavioral test 更关键，因为它证明 generic `StoreSubscr` 真的被拆开了。

## 和 CPython 3.14 的关系

CPython 3.14 specialization 能帮助 CinderX 更容易知道 container/index type。如果 HIR builder 能从 specialized bytecode 或 type profile 知道 list exact + long index，这条 path 就能命中更多。

## ARM64 启发

这个 commit 本身不是 ARM64-specific，但它减少了最贵的 generic C API dispatch。ARM64 后续优化重点变成：

- `IndexUnbox` 和 bounds check 的 branch sequence；
- `LoadField ob_item` 的 address mode；
- `StoreArrayItem` 是否 direct store；
- old value load/store 对 register pressure 的影响。

这就是从 Python operation 优化到 backend 优化的链条：先拆语义，再优化机器形状。

## 后续追问

- fannkuch 剩下那个未 specialized `StoreSubscr` 缺什么 type guard？
- `StoreArrayItem` direct lowering 后，ARM64 是否还会因为 memory operand 限制插入额外 move？
- old value 的 lifetime 设计是否能被更明确的 refcount IR 表达替代？
- list store 是否能和 CPython 3.14 list store specialized opcode 对齐？

## 分类

- Primary layer: HIR simplify
- Runtime pattern: `list[int] = value`
- Correctness mechanism: exact list guard, index unbox error check, bounds check, old-value refcount preservation
- Performance mechanism: avoid `PyObject_SetItem` generic dispatch
- ARM64 impact: 间接高价值，给后续 direct store lowering 提供前置 HIR shape
