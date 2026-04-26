# 53f4fc0f: Specialize float operations further

## 元信息

- Commit: `53f4fc0f1944ea8dc0893ca3c06626e2b84be448`
- Date: 2026-02-25
- Author: Alex Malyshev
- Reviewer: Jacob Bower (`jbower-fb`)
- Layer: HIR Simplify + LIR lowering + JIT runtime helper
- Changed files:
  - `cinderx/Jit/hir/simplify.cpp`
  - `cinderx/Jit/jit_rt.cpp`
  - `cinderx/Jit/jit_rt.h`
  - `cinderx/Jit/lir/generator.cpp`
  - `cinderx/RuntimeTests/hir_tests/simplify_test.txt`

## Commit Message 要点

这个 commit 做了两件事：

1. 让更多 float operation 进入 unboxed path，使 simplifier 能继续优化。
2. 增加 `x ** 0.5` 的 specialization，把它 lower 成 `sqrt(x)`。

commit message 还特别说明：这个优化当时“不常触发”，因为它依赖 CinderX 知道 `BINARY_OP` 两边都是 float；但如果启用 `PYTHONJITSPECIALIZEDOPCODES=1`，adaptive interpreter 的信息可以让它触发。这和后续 `5fec65f4` 默认打开 specialized opcode support 是连续主线。

## 优化形状

普通 float add/sub/mul 的目标形状：

```text
BinaryOp / InPlaceOp with FloatExact operands
  -> FloatBinaryOp
  -> PrimitiveUnbox<CDouble>
  -> DoubleBinaryOp<Add/Subtract/Multiply>
  -> PrimitiveBox<CDouble>
```

`x ** 0.5` 的目标形状：

```text
FloatBinaryOp<Power>(x, 0.5)
  -> PrimitiveUnbox<CDouble>(x)
  -> LoadConst<CDouble[0.5]>
  -> DoubleBinaryOp<Power>
  -> LIR generator recognizes exponent 0.5
  -> call JITRT_SqrtDouble(x)
  -> PrimitiveBox<CDouble>
```

这不是“所有 power 都变快”。只有右侧 exponent 带 object specialization 且值正好是 `0.5`，才会走 sqrt path。其他 power 仍然走 `JITRT_PowerDouble`。

## 代码实现 Review

### `simplifyBinaryOp`

原先 float exact binary op 的 simplify 范围有限。这个 commit 扩展逻辑：当 `lhs` 和 `rhs` 都是 `TFloatExact`，并且 op 是 `Power` 或者存在 `FloatBinaryOp::slotMethod(op)`，就 emit `FloatBinaryOp`。

这里的 `UseType<TFloatExact>` 很重要：优化依赖 exact float type，不能对 float subclass 随意套用 CPython float slot 行为。

### `simplifyInPlaceOp`

新增对 float inplace op 的转换。因为 Python float 是 immutable，`x += y` 可以安全地当作 `x = x + y` 的 binary op 来 simplify。代码把 `InPlaceOpKind` 映射到 `BinaryOpKind`，再 emit `FloatBinaryOp`。

这个点很有学习价值：不是所有 inplace op 都能这么处理，必须依赖对象 immutable 的语义。

### `simplifyFloatBinaryOp`

新增核心 unbox 逻辑：

- add/sub/mul 直接 `PrimitiveUnbox -> DoubleBinaryOp -> PrimitiveBox`；
- power 检查右操作数是否有 float object specialization，且值为 `0.5`；
- `0.5` path emit `DoubleBinaryOp<Power>`，让 LIR generator 再把它转成 sqrt helper。

为什么不是直接在 HIR 里 emit `Sqrt`？因为当时已有 `DoubleBinaryOp<Power>` 这条表达路径，LIR generator 可以根据右侧 double spec 决定调用 `JITRT_SqrtDouble`。

### `jit_rt.cpp/h` 和 `lir/generator.cpp`

runtime 侧新增 `JITRT_SqrtDouble(double)`，实现是 `sqrt(x)`。LIR generator 中 `DoubleBinaryOp<Power>` 会检查 right operand 的 `doubleSpec()` 是否是 `0.5`，如果是则 append call 到 `JITRT_SqrtDouble`，否则 append call 到 `JITRT_PowerDouble`。

## 测试实现 Review

`simplify_test.txt` 增加/更新大量 golden tests，重点不是 behavioral result，而是 HIR shape：

- `FloatBinaryOp<Add/Subtract/Multiply>` 是否变成 `PrimitiveUnbox + DoubleBinaryOp + PrimitiveBox`；
- `InPlaceOp` float case 是否先转成 `FloatBinaryOp`；
- power `0.5` case 是否保留右侧 double spec，供 LIR 降成 sqrt；
- 对 3.12/3.14/3.15 expected output 保持一致。

这类 tests 是 compiler optimization 最可靠的学习材料：它们告诉你官方希望 IR 长什么样。

## CPython 3.14 关系

这个 commit 明确依赖 specialized opcode 的信息来源。CPython 3.14 adaptive interpreter 知道 binary op 的 operand 类型时，CinderX 才更容易把 generic `BINARY_OP` 转成 `FloatBinaryOp`。所以阅读顺序上应该先看本 commit，再看 `5fec65f4`，再看 `d70dcb5a`。

## ARM64 启发

ARM64 受益点在于减少 generic helper call：

- `PyNumber_*` / CPython float slot call 消失；
- hot path 变成 FP register operation 或 single runtime `sqrt` helper；
- backend 可以优化 FP instruction 和 call sequence；
- nbody 这类 workload 的大量 `dist_sq ** 0.5`、multiply、add 才有机会走 primitive path。

但它也暴露下一层问题：如果每个 primitive op 之后马上 `PrimitiveBox`，boxing/unboxing 仍可能吞掉收益。后续优化可以看是否能让 value 在多个 basic block 中保持 unboxed。

## 后续追问

- `x ** 0.5` 是否应该在 HIR 层有独立 `Sqrt` opcode，而不是复用 `DoubleBinaryOp<Power>`？
- ARM64 下 `sqrt` helper call 是否可以进一步映射到硬件 `fsqrt`？
- specialized opcode support 默认打开后，这个 path 在 `nbody` 中命中率是多少？
- 对 float floor-div/modulo 是否存在类似可 guard 的 primitive path？

## 分类

- Primary layer: HIR simplify
- Runtime pattern: float arithmetic, inplace float arithmetic, square root idiom
- Correctness mechanism: exact type guard, object specialization for exponent
- Performance mechanism: unboxed double op, sqrt helper instead of generic power
- ARM64 impact: 间接但高价值，给 backend 提供 primitive FP work
