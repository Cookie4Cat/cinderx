# d70dcb5a: Unbox float TrueDivide and mixed float/int ops

## 元信息

- Commit: `d70dcb5a4b070a57db13f840516efa63a5ca39b5`
- Date: 2026-03-17
- Author: Alex Malyshev
- Reviewer: Jacob Bower (`jbower-fb`)
- Layer: HIR Simplify
- Scope: CPython 3.14 + CinderX；对应的 HIR expected output 同时覆盖 3.12/3.15
- Changed files:
  - `cinderx/Jit/hir/simplify.cpp`
  - `cinderx/RuntimeTests/hir_tests/simplify_test.txt`
  - `cinderx/benchmarks/nbody.py`

## Commit Message 要点

这个 commit 做了两个相关的 simplification:

1. 当 `FloatBinaryOp<TrueDivide>` 的两个 operand 都是 `FloatExact` 时，直接 lowering 到 unboxed `DoubleBinaryOp<TrueDivide>`，不再走 boxed CPython float division slot。
2. 当 `BinaryOp` 的一边是 `FloatExact`，另一边是带 object specialization 的 constant `LongExact` 时，在 compile time 把 int constant 转成 `double`，然后直接生成 unboxed `DoubleBinaryOp`。

mixed float/int fast path 支持 add、subtract、multiply、true-divide 和 power。

## 优化形状

在这个 commit 之前，CinderX 已经能把 float add/subtract/multiply unbox 成 primitive double operation。`TrueDivide` 之前没有走这条路，原因是 Python 语义要求除以 0 时抛 `ZeroDivisionError`，裸 `fdiv` 本身不能表达这个语义。

新的 IR 形状是：

```text
FloatExact/LongExact knowledge
  -> UseType guards
  -> PrimitiveUnbox to CDouble
  -> optional divisor != 0.0 Guard for TrueDivide
  -> DoubleBinaryOp
  -> PrimitiveBox back to FloatExact
```

这是 CinderX 很典型的一类优化：先用 guard 保住 Python semantics，然后把 hot path 从 boxed object dispatch 挪到 primitive operation。

## 代码实现 Review

### Float TrueDivide

核心改动在 `simplifyFloatBinaryOp`。`TrueDivide` 被加成 add/sub/mul 后面的独立 case:

- 用 `PrimitiveUnbox(..., TCDouble)` unbox 左右两个 `FloatExact` operand；
- 用 `LoadConst(Type::fromCDouble(0.0))` materialize 一个 `0.0`；
- 用 `PrimitiveCompare<NotEqual>` 比较右操作数是否非零；
- 对比较结果 emit `Guard`；
- 生成 `DoubleBinaryOp<TrueDivide>`；
- 最后用 `PrimitiveBox<CDouble>` box 回 `FloatExact`。

当前源码位置：`cinderx/Jit/hir/simplify.cpp` 里的 `simplifyFloatBinaryOp`。

这里最关键的是 divisor-zero guard。没有这个 guard，unboxed path 会退化成 IEEE floating-point 的 infinity/NaN 行为，而 Python 需要抛 `ZeroDivisionError`。

### Constant mixed float/int

另一个核心改动在 `simplifyBinaryOp`，新增 fast path 覆盖：

- `FloatExact op LongExact[constant]`
- `LongExact[constant] op FloatExact`

实现步骤大致是：

- 先限制 op 必须是 add、subtract、multiply、true-divide 或 power；
- 识别哪边是 float，哪边是 int；
- 要求 int 侧有 `objectSpec()`，也就是 compile time 已知具体整数对象；
- 用 `PyLong_AsLongAndOverflow` 把 integer object 转成 C `long`；
- 如果 overflow，就放弃这个优化；
- 对两边 emit `UseType`；
- 把 float unbox 成 `CDouble`；
- 把 int constant 作为 `CDouble` constant emit 出来；
- 对非交换操作保留 operand order，比如 `1 / x` 和 `x / 1` 不能交换；
- 对 `TrueDivide` 加同样的 divisor-zero guard；
- 生成 `DoubleBinaryOp`，再 `PrimitiveBox` 回 Python float。

这里的 object specialization 要求很重要：这个 commit 只处理 compile-time constant int，因此 rewrite 非常直接，不需要引入 runtime `PyLong` shape check。

## LIR / Codegen 影响

`DoubleBinaryOp` 在 `cinderx/Jit/lir/generator.cpp` 里已经有 lowering:

- add -> `kFadd`
- subtract -> `kFsub`
- multiply -> `kFmul`
- true-divide -> `kFdiv`
- power -> runtime helper；其中 `x ** 0.5` 会走 `sqrt`

所以这个 commit 本身不需要写 ARM64-specific code。它对 ARM64 的价值在于：把原本的 generic Python C API call 变成 primitive floating-point operation，让现有 AArch64 backend 有机会生成更直接的 FP instruction sequence。

换句话说，这不是 “ARM64 后端优化 commit”，但它是 ARM64 能变快的前置条件之一。后续真正要在 ARM64 上继续看的点是：`kFdiv` lowering、double constant materialization、guard branch、boxing/unboxing sequence 有没有多余指令和 register pressure。

## 测试实现 Review

测试落在 `cinderx/RuntimeTests/hir_tests/simplify_test.txt`，属于 HIR simplification golden tests。

新增用例包括：

- `BinaryOpMulFloatExactAndConstIntToUnboxed`
- `BinaryOpTrueDivideConstIntAndFloatExactToUnboxed`
- `FloatBinaryOpTrueDivideToUnboxed`

这些 expected output 重点验证了 3.14 下会出现下面这串 IR:

- `UseType<FloatExact>`
- constant int 场景下的 `UseType<ImmortalLongExact[...]>`
- `PrimitiveUnbox<CDouble>`
- `LoadConst<CDouble[...]>`
- true-divide 场景下的 `PrimitiveCompare<NotEqual>` + `Guard`
- `DoubleBinaryOp<...>`
- `PrimitiveBox<CDouble>`

这种测试比普通 behavioral test 更适合 compiler optimization：它不仅证明结果对，还证明 optimizer 确实生成了目标 primitive HIR。

## Benchmark 关联

`cinderx/benchmarks/nbody.py` 也有小改动：

```python
class Body(object):
```

改成：

```python
class Body:
```

同时 `advance` 加了 type annotations:

```python
def advance(bodies: list[Body], dt: float, n_bodies: int) -> None:
```

`nbody` 很适合观察这类优化，因为它包含 tight floating-point loops、重复 attribute access、multiply/divide，以及类似 `dist_sq ** 0.5` 的数值模式。前面引入 `nbody` benchmark 的 commit message 也明确提到：CinderX 当时对 floating-point-heavy workloads 还没有明显优势。这个 commit 就是在补这块短板。

## 和 CPython 3.14 的关系

对我们当前目标来说，重点是 CPython 3.14 的 specialization 信息能不能更多地帮助 CinderX 证明 `FloatExact` 和 constant `LongExact`。

如果 HIR builder 能从 CPython adaptive interpreter 或 object specialization 中拿到更强的类型/常量信息，这个 simplification 就能更频繁触发。

这类优化即使不是 ARM64-specific，也很值得跟：

- 它减少 boxed CPython dispatch；
- 它减少 runtime int-to-float conversion；
- 它把热路径暴露成 `kFdiv`/`kFmul`/`kFadd`/`kFsub`；
- 它给 ARM64 backend 提供了可以继续优化的 primitive FP path。

## 对 ARM64 优化的启发

这个 commit 给我们的 ARM64 方法论很明确：

1. 先从 workload hot pattern 出发，比如 `dt / 3`、`x * 2`、`dist_sq ** 0.5`。
2. 先确认 HIR 能把它表达成 typed primitive work。
3. 先用 HIR golden test 固化 rewrite。
4. 再看 AArch64 LIR/codegen 生成的 primitive sequence。
5. 最后才去做 ARM64-specific instruction selection 或 register-use tuning。

也就是说，不要一上来就盯汇编。先让 Python 高层语义尽可能稳定地塌缩成 primitive HIR，后端才有足够空间优化。

## 后续追问

- 当前 `meta/main` 里，这条路径在真实 CPython 3.14 specialized bytecode 下触发频率如何？还是主要只在 hand-written HIR tests 里能看到？
- numeric loop 里的 true-divide guard branch 在 ARM64 上成本如何？branch predictability 能不能从 profiling 里看出来？
- 这个 rewrite 后，boxing/unboxing 是否仍然占主要开销？如果是，下一步应该考虑让更多相邻 basic blocks 保持 unboxed value。
- mixed float/int 非 constant 场景能不能用便宜 guard 做？当前 `meta/main` 后面已经有 follow-up: `b1945d88`，它用 compact-long checks 继续简化 float/long。

## 分类

- Primary layer: HIR simplify
- Runtime pattern: float arithmetic, mixed float/int arithmetic
- Correctness mechanism: `UseType`, object specialization, overflow bail-out, divisor-zero guard
- Performance mechanism: avoid boxed CPython numeric dispatch and runtime int-to-float conversion
- ARM64 impact: 间接但重要；把高层数值操作转成 AArch64 backend 可优化的 primitive FP operations
