# HIR Simplify 优化线索

## 主线判断

2/3/4 月官方主线里最值得学习的 HIR 思路是：先从 CPython 3.14 specialization、CinderX type knowledge、object specialization 中拿到更强 facts，再把 boxed Python operation strength reduce 成 primitive HIR。ARM64 不直接出现在这些 commit 里，但它们决定了后端能不能看到 `kFadd`、`kFdiv`、direct store、compact int compare 这种可优化形状。

换句话说，HIR simplify 是 ARM64 性能优化的上游入口。如果 HIR 仍然是 generic `BinaryOp`、`StoreSubscr`、`LongCompare`，后端只能生成 helper call；如果 HIR 已经是 `DoubleBinaryOp`、`StoreArrayItem`、`PrimitiveCompare`，AArch64 backend 才能继续谈 instruction selection。

## 2 月: typed numeric path 的起点

`53f4fc0f` 是 float path 的起点。它把 `FloatExact` binary operations 转成 `FloatBinaryOp`，再在 `simplifyFloatBinaryOp` 中 unbox 成 `DoubleBinaryOp`。特别值得注意的是 `x ** 0.5 -> sqrt(x)`，它说明 CinderX 不只是做类型特化，也识别数值 idiom。

这个 commit 当时“不常触发”，因为需要知道两边都是 float。这个限制直接连接到 3 月的 `5fec65f4`: 默认打开 specialized opcode support，让 CinderX 更容易从 CPython adaptive interpreter 拿到 exact type facts。

## 3 月: specialization 命中率和 container fast path

`5fec65f4` 是 config 层的小改动，但改变了 HIR simplify 的真实命中率。commit message 里的 `nbody` 数据非常关键：打开 specialized opcode support 后，从约 15.774s 到 9.630s。这说明前端 facts 对 numeric workload 是决定性的。

`d70dcb5a` 扩展 float path：

- `FloatBinaryOp<TrueDivide>` 进入 unboxed `DoubleBinaryOp<TrueDivide>`；
- mixed float/constant int 在 compile time 把 int 转成 double；
- true-divide 用 divisor-zero guard 保持 Python `ZeroDivisionError` 语义。

`54cb7a83` 则是 container path：把 `list[int] = value` 从 generic `PyObject_SetItem` 拆成 `IndexUnbox + CheckSequenceBounds + LoadField(ob_item) + StoreArrayItem`。这类优化的关键是 exact list guard 和 old value refcount preservation。

## 4 月: compact long 和 primitive cleanup

`b1945d88` 把 mixed float/runtime long 继续推进：如果 long 是 compact long，就 guard 后 unbox 成 `CInt64`，再 `IntConvert` 成 `CDouble`，最终走 `DoubleBinaryOp`。这比 constant int path 更通用，也更贴近日常 Python 代码。

`4c280add` 对 `LongCompare` 做类似 strength reduction，但只做 comparison，不做 long arithmetic。原因是 comparison 不需要分配 boxed result，而 arithmetic 最后仍可能需要 `PrimitiveBox` 保留 deopt path，收益更复杂。

`229573e7`、`2c247cf7`、`0e2820b7` 是 cleanup 支撑：

- constant fold `IntConvert`；
- simplify `PrimitiveBox`；
- 让 `IntBinaryOp` 支持 `CBool` bitwise operations；
- 帮助 guard combination 和 compact long checks 继续被 simplify。

## Correctness 共同模式

这些 HIR optimizations 都不是“相信类型然后直接替换”。它们有固定 correctness pattern：

- `UseType` 固化 exact type assumption；
- object specialization 只在 compile-time known object 时使用；
- runtime compact long 需要 `IsCompactLong + Guard`；
- division 需要 explicit zero guard；
- list store 需要 bounds check 和 old value refcount handling；
- mutable/subclass 行为不安全时只处理 exact type。

## 测试阅读方法

学习 HIR simplify commit 时，优先看 `RuntimeTests/hir_tests/simplify_test.txt`。不要只看 C++ diff。golden test 会告诉你官方希望 pass 后 IR 长什么样。

建议按这个顺序读：

1. 找 commit 新增的 `--- Test Name ---`。
2. 看 `--- Input ---` 里原始 HIR。
3. 看 `--- Expected 3.14 ---`。
4. 标出新增的 `UseType`、`Guard`、`PrimitiveUnbox`、`DoubleBinaryOp`、`StoreArrayItem`。
5. 再回到 `simplify.cpp` 找 emit 顺序。

## 对 ARM64 的意义

ARM64 后端优化前，先问三个问题：

- hot path 是否已经从 boxed operation 变成 primitive HIR？
- guards 是否足够便宜，且失败率足够低？
- boxing/unboxing 是否还能跨 basic block 消除？

如果答案是否定的，先补 HIR facts 和 simplify；如果答案是肯定的，再看 AArch64 lowering、postgen、postalloc。
