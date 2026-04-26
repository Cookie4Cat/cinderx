# HIR Simplify

这一层关注如何把 object-level Python operation 收窄成 primitive / unboxed / constant-folded path。

## 重点 commits

- `53f4fc0f` Specialize float operations further
- `d70dcb5a` Unbox float TrueDivide and mixed float/int ops to DoubleBinaryOp
- `b1945d88` Simplify "Float BinaryOp Long" with compact long checks
- `4c280add` Optimize LongCompare for compact longs
- `229573e7` Constant fold IntConvert for constant ints
- `2c247cf7` Add simplification cases for PrimitiveBox
- `0e2820b7` Support IntBinaryOp on CBool arguments

## 典型形状

- `GuardType` 后接 primitive unbox。
- `PrimitiveBox` / `PrimitiveConvert` 被 simplify 消掉。
- constant int / bool 直接 fold。
- compact long guard 允许在小整数场景跳过 generic long helper。

## 风险点

- guard 成本可能吃掉 unbox 收益。
- compact long path 对 `regex_compile` 这类 workload 可能不稳定。
- mixed numeric 需要特别小心 Python 语义和 fallback。

## 实验建议

先用 micro 验证 HIR 形状，再跑 selected pyperformance。只要出现宏观 regression，就回到 HIR/LIR dump 看 guard 数量、deopt stats 和 code size。
