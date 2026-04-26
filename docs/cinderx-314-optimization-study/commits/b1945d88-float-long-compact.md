# b1945d88: Simplify Float BinaryOp Long with compact long checks

## 元信息

- Commit: `b1945d880579f10164048ccd3f3fe84931b841d2`
- Date: 2026-04-13
- Author: Alex Malyshev
- Reviewer: Dino Viehland
- Layer: HIR Simplify + new HIR opcodes + LIR lowering
- Changed files:
  - `cinderx/Common/py-portability.h`
  - `cinderx/Jit/hir/hir_ops.h`
  - `cinderx/Jit/hir/hir.{h,cpp}`
  - `cinderx/Jit/hir/simplify.cpp`
  - `cinderx/Jit/lir/generator.cpp`
  - `cinderx/Jit/lir/instruction.h`

## Commit Message 要点

这个 commit 是 `d70dcb5a` 的自然延伸。`d70dcb5a` 只处理 mixed float/int 中 int 是 compile-time constant 的情况；`b1945d88` 处理 runtime `LongExact`，用 compact long guard 证明它可以 cheap unbox，然后转成 `double`。

commit message 的核心判断是：

- mixed float/int 走 `PyNumber` runtime helper 太 dynamic；
- 如果知道是 float + long，可以把 long 转 float 后走 `FloatBinaryOp`；
- 难点是 long-to-float conversion 必须 cheap 且不能产生 Python error；
- CPython 3.12+ 的 compact long 可以满足这个条件；
- 不尝试 `Long BinaryOp Long`，因为最终 `PrimitiveBox` 仍然不能 DCE，收益不清楚。

## 优化形状

目标形状：

```text
BinaryOp<FloatExact, LongExact>
  -> UseType<FloatExact>
  -> UseType<LongExact>
  -> IsCompactLong(long)
  -> Guard(is_compact)
  -> CompactLongUnbox(long)      # CInt64
  -> IntConvert(CInt64 -> CDouble)
  -> PrimitiveUnbox(float)       # CDouble
  -> DoubleBinaryOp
  -> PrimitiveBox(CDouble)
```

`TrueDivide` 仍然需要 divisor-zero guard。非交换操作保留 operand order，所以 `float / long` 和 `long / float` 的右操作数检查不一样。

## 代码实现 Review

### 新 HIR opcodes

`hir_ops.h` 增加：

- `IsCompactLong`
- `CompactLongUnbox`

这两个 opcode 是优化能成立的关键。`IsCompactLong` 负责把 runtime PyLong shape check 表达为 HIR condition，`CompactLongUnbox` 负责在 guard 之后把 compact long 变成 `CInt64`。

### `simplify.cpp`

新增两个 simplification:

- `simplifyIsCompactLong`: 如果 operand 有 object spec，compile time 直接用 `_PyLong_IsCompact` fold 成 bool；如果 operand 是 `PrimitiveBox(CInt64)`，则把 `IsCompactLong(box(n))` 转成 `IsCompactLong(n)`。
- `simplifyCompactLongUnbox`: 如果 object spec 是 compact long，直接 fold 成 `LoadConst<CInt64>`；如果 operand 来自 `PrimitiveBox(CInt64)`，则直接返回 box 的 value。

这部分很重要：它不只是添加 runtime guard，还让 guard/box 周围继续被 simplify，避免新 opcode 变成优化障碍。

### mixed float/long path

`simplifyBinaryOp` 中新增非 constant mixed float/int 分支。它只在 Python 3.12+ 编译，因为依赖 CPython compact long layout。逻辑是：

- 识别 `FloatExact` + 非 object-spec `LongExact`；
- emit `UseType`；
- emit `IsCompactLong` + `Guard`；
- emit `CompactLongUnbox`；
- emit `IntConvert(..., TCDouble)`；
- unbox float；
- emit `DoubleBinaryOp`；
- box result。

这和 constant int path 的区别是：constant path 在 compile time 用 `PyLong_AsLongAndOverflow`，compact path 在 runtime 用 guard + unbox。

### LIR lowering

`lir/generator.cpp` 增加：

- `IntConvert` 到 `TCDouble` 时 lower 成 `kInt64ToDouble`；
- `CompactLongUnbox` inline `_PyLong_CompactValue` 的核心逻辑：load `lv_tag`、计算 sign、load `ob_digit[0]`、zero extend、multiply sign；
- `IsCompactLong` 对 `CInt64` 和 `PyLongObject` 分别生成 cheap range/tag check。

这说明官方没有用 C helper 来做 compact long check/unbox，而是直接 lower 成 LIR instruction sequence。

## 测试实现 Review

这个 commit 主要应该看 HIR/LIR expected shape：

- HIR 是否出现 `IsCompactLong`、`Guard`、`CompactLongUnbox`、`IntConvert<TCDouble>`；
- constant object-spec long 是否被 fold；
- `PrimitiveBox` 周围是否能继续 simplify；
- `TrueDivide` 是否保留 zero-divisor guard；
- 3.12+ 和 3.14 的 expected output 是否符合 compact long layout 假设。

## 和 CPython 3.14 的关系

compact long 是 CPython object layout 事实。CinderX 利用这个 runtime representation 做 guard，不是引入新的 Python-level semantic。对 3.14 来说，small integer 非常常见，这个 guard 命中率理论上很高。

## ARM64 启发

这个 commit 对 ARM64 很有价值，因为它把 mixed float/int 从 `PyNumber` helper call 变成 primitive sequence。ARM64 后续要看：

- `IsCompactLong` 的 tag/range check 是否生成紧凑 branch；
- `CompactLongUnbox` 的 load/and/sub/mul sequence 是否能简化；
- `Int64ToDouble` 是否映射到合适 FP conversion；
- guard failure 是否低到值得优化 hot path。

## 后续追问

- compact long guard 是否可以和 type guard 合并，减少 branch？
- `CompactLongUnbox` 的 sign 计算是否能在 ARM64 上用更少 instruction？
- 如果后续 `PrimitiveBox` simplification 更强，是否可以重新考虑部分 `Long BinaryOp Long`？
- benchmark 中 mixed float/int 的真实命中率如何统计？

## 分类

- Primary layer: HIR simplify + LIR lowering
- Runtime pattern: float + small runtime int
- Correctness mechanism: `UseType<LongExact>`、`IsCompactLong` guard、zero-divisor guard
- Performance mechanism: avoid `PyNumber` helper and runtime int-to-float object path
- ARM64 impact: 高，能把 common mixed numeric path 转成 primitive instructions
