# April HIR primitive simplification series

## 元信息

- `4c280addd77a4d9b587e0147d56b8ee488f8546b`, 2026-04-22, Alex Malyshev, `Optimize LongCompare for compact longs`
- `229573e7f46a901395de1a61c4fd47484f50d477`, 2026-04-22, Alex Malyshev, `Constant fold IntConvert for constant ints`
- `2c247cf7267a35142cc437d319328923b4aa0d92`, 2026-04-22, Alex Malyshev, `Add simplification cases for PrimitiveBox`
- `0e2820b72fae53f1f2afb0755de841b65a9cf0ac`, 2026-04-22, Alex Malyshev, `Support IntBinaryOp on CBool arguments`
- Layer: HIR simplify / primitive cleanup / compact long guards

## 总体主线

这组 commit 都在为 boxed-to-unboxed strength reduction 铺路。`b1945d88` 引入 compact long checks 后，HIR 里会出现更多 guard、unbox、convert、box 的组合。如果这些小节点不能继续 simplify，整体优化收益会被 IR 噪音吃掉。

## `4c280add`: LongCompare for compact longs

`LongCompare` 可以被 strength reduce 成：

```text
guard both operands are compact longs
CompactLongUnbox(left/right)
PrimitiveCompare(unboxed values)
```

commit message 说这个功能 gated by runtime option，默认关闭，仍在实验。它不扩展到 long arithmetic，因为 arithmetic 最后通常要 boxed result，deopt path 也需要那个 box，收益不如 comparison 明确。

这个边界很重要：官方优先优化“不需要分配结果对象”的路径。

## `229573e7`: constant fold IntConvert

之前 `IntConvert` 只处理 constant doubles。这个 commit 支持 constant ints，并调整 `UseType` 用法。它看起来小，但能让 compact-long / primitive-int path 里的 convert 不留到 LIR。

典型收益：

```text
IntConvert(CInt constant -> target type)
  -> LoadConst(converted value)
```

## `2c247cf7`: PrimitiveBox simplification

commit message 说是为 strength reduce boxed operations into unboxed ones 做准备。很多优化会生成：

```text
PrimitiveUnbox
operation
PrimitiveBox
```

如果后续又马上 unbox 或 compare，`PrimitiveBox` simplification 能避免无意义 box/unbox 往返。

## `0e2820b7`: IntBinaryOp on CBool arguments

这个 commit 只支持 bitwise operations，目的是把 cheap boolean checks 做 bitwise and。compact long guards 经常需要组合多个 boolean conditions，如果 CBool 不能走 `IntBinaryOp`，就会卡在更笨的路径。

它还加入 constant folding，因为常见场景是 guard 一个 constant integer 是否 compact。

## 测试实现 Review

主要看 `simplify_test.txt`：

- LongCompare 是否出现 compact guards；
- IntConvert constant 是否 fold；
- PrimitiveBox simplification 是否消掉 box/unbox；
- CBool bitwise 是否被接受并 fold。

这组 test 的价值是让你看到 strength reduction 后的“清理阶段”。

## ARM64 启发

ARM64 上 branch/guard 多了会有成本。`CBool` bitwise 和 constant fold 可以帮助组合 guard，减少 materialization。PrimitiveBox cleanup 可以减少 object allocation/refcount，也间接减少 ARM64 memory traffic。

## 后续追问

- LongCompare compact mode 默认关闭的原因是性能不稳定还是 correctness 风险？
- CBool bitwise combination 是否能进一步 lower 成 branchless ARM64 sequence？
- PrimitiveBox simplification 是否足够支持 Long arithmetic 的下一步优化？
- compact long guards 的失败率是否低到值得默认打开？
