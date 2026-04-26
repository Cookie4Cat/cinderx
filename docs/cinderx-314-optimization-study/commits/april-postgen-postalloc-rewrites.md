# April postgen/postalloc rewrite series

## 元信息

这篇合并 review 4 月一组高度相关的 LIR rewrite commits：

- `aca150d2bc9a78438a92966350687410fba02d16`, 2026-04-02, Dino Viehland, `Use re-writes to avoid scratch register usage w/ immediates`
- `8b158d2578fab1a7083d09ccf50704de57bd7626`, 2026-04-02, Dino Viehland, `Rewrite guard instructions on floating point instructions`
- `47e3a8debb0781ad553d1e455685f1ecbcc70147`, 2026-04-03, Dino Viehland, `Rewrite lea that requires a temporary to an explicit madd instruction`
- `791c7dccbccd7bdb98aecfa6ac318dacf49b5e63`, 2026-04-03, Dino Viehland, `Rewrite kHasType guard to use postgen type load`
- `16c708f85f964da661975a9b9e95e5503033aaba`, 2026-04-03, Dino Viehland, `Add postgen rewrite for Call instruction inputs`
- `3a8600fba747d64e3a135983a7ad089f4117edc8`, 2026-04-07, Dino Viehland, `Add MovConstPool postgen pass for large duplicate constants`
- `8aa963d43cf1c01fe0e092c0d49d7fb24917e585`, 2026-04-15, Dino Viehland, `Re-write memory inputs to registers`

主要文件集中在：

- `cinderx/Jit/lir/postgen.cpp`
- `cinderx/Jit/lir/postalloc.cpp`
- `cinderx/Jit/codegen/autogen.cpp`
- `cinderx/Jit/lir/instruction.h`
- `cinderx/RuntimeTests/lir_abi_test.cpp`
- `cinderx/RuntimeTests/lir_postgen_test.cpp`
- `cinderx/RuntimeTests/lir_postalloc_test.cpp`

## 总体主线

这组 commit 的共同目标是：把 ARM64 codegen 里隐式使用 scratch register 的情况，改成显式 LIR rewrite，让 register allocation 管理 temporary。

旧模式：

```text
TranslateFoo sees operand shape ARM64 cannot encode
  -> emitter grabs arch::reg_scratch_*
  -> emits hidden load/move/temp sequence
```

新模式：

```text
postgen/postalloc sees illegal or expensive operand shape
  -> inserts explicit Move / MAdd / MovConstPool / vreg
  -> regalloc sees temporary live range
  -> codegen emits simple legal instruction
```

这个变化非常关键：它把 backend limitation 从“emitter 内部技巧”提升为“LIR 中可测试、可 review、可分配寄存器的结构”。

## `aca150d2`: immediates avoid scratch register

ARM64 很多 instruction 不能直接 encode 任意 immediate。以前 codegen 遇到这种 immediate 时要用 temporary。这个 commit 把 immediate rewrite 放到 postgen：

```text
op(..., Imm(too large or illegal))
  -> Move Imm -> vreg
  -> op(..., vreg)
```

changed files 显示 `autogen.cpp` 删除特殊逻辑，`postgen.cpp` 增加 155 行 rewrite，`lir_abi_test.cpp` 更新 expected output。学习重点是：哪些 immediate shape 被 rewrite，哪些仍可直接 encode。

## `8b158d25`: FP guard inputs

ARM guard code 对 floating-point guarded value 原本有特殊 temporary。这个 commit 改成 rewrite：先把 FP result 转/搬到 general purpose register，再让 guard 处理 GP value。

它说明 guard 不是抽象 bool 那么简单。到了 backend，guard condition 的 register class 很重要：FP register 和 GP register 不能随意互用。

## `47e3a8de`: LEA temporary to explicit `MAdd`

ARM64 的 address calculation 没有 x86 `lea` 那么灵活。原来某些 `lea` 需要 temporary；这个 commit 新增 `MAdd` instruction，并在 postgen 中把需要 temporary 的 `lea` 改成 explicit multiply-add shape。

这很适合 ARM64：`madd` 是架构原生 instruction，明确表达 `base + index * scale` 类形状，比临时在 emitter 中拼指令更清楚。

## `791c7dcc`: `kHasType` guard type load

`kHasType` guard 原本在 `TranslateGuard` 中用 scratch register load `obj->ob_type`。这个 commit 的 rewrite 会插入：

```text
Move Ind{obj, ob_type_offset} -> vreg
Guard<kIs>(vreg, expected_type)
```

这样 type load 的 temporary 由 regalloc 分配，而不是固定占 `arch::reg_scratch_0`。这类 guard 在 Python JIT 中非常常见，所以它对 register pressure 很重要。

## `16c708f8`: Call instruction inputs

ARM64 `translateCall` 原来用 `reg_scratch_br` 加载 Imm 和 Stack call targets，再 `blr`。这个 commit 在 postgen 中把 Call 的 Imm/Stack input rewrite 成 `Move -> vreg`：

```text
Call Imm(target)
  -> Move Imm(target) -> vreg
  -> Call vreg
```

注意 commit message 说 fallback 仍保留，因为 direct-invocation tests 和 postalloc-created Call 可能绕过 postgen。这是一个工程上很稳的过渡：主路径清理，边界路径保留。

## `3a8600fb`: MovConstPool

ARM64 materialize 64-bit large immediate 常常需要多条 `movz/movk`。这个 commit 增加 postgen pass：如果同一个 large constant 出现多次，并且每次都需要超过 2 条 mov 指令，就 rewrite 成 `kMovConstPool`，从 PC-relative constant pool 里 `ldr`。

关键新增：

- `instruction.h`: `kMovConstPool`
- `environ.h`: constant pool tracking
- `postgen.cpp`: rewrite pass
- `autogen.cpp`: translate rule
- `gen_asm.cpp`: pool emission after deopt exits

这是 code size 优化，也是 I-cache 优化。它不一定减少 latency，但减少重复 constant materialization。

## `8aa963d4`: memory inputs to registers

这个 commit 处理 ARM64 不支持某些 memory input form 的问题。message 提到 IG startup 中缺 `Add rm` 支持；即使移除了 stack arguments，仍可能出现 non-stack memory argument。

postalloc 增加大块 rewrite：把 memory input load 到 register，再执行原 instruction。它是 postalloc 而不是 postgen，因为此时 register allocation 后的 physical/memory placement 更明确。

## 测试实现 Review

这组 commit 的测试分三类：

- `lir_abi_test.cpp`: ABI-sensitive shape，尤其 call、guard、immediate。
- `lir_postgen_test.cpp`: postgen rewrite 是否插入 expected `Move`/`Call`/`MAdd`。
- `lir_postalloc_test.cpp`: postalloc 后 memory input rewrite 是否正确。

学习时要对照 test name 看 rewrite 前后的 LIR，不要只读 C++。

## ARM64 方法论

这组 commit 的核心方法论：

1. 不在 emitter 里偷偷用 scratch register。
2. 把非法 operand shape 改写成合法 LIR。
3. 让 regalloc 看见 temporary。
4. 用 LIR tests 固化 rewrite。
5. 保留 fallback，避免绕过 pass 的路径 crash。

这比“为每个 case 手写 ARM64 特例”更可维护，也更容易跨 x86/ARM64 比较。

## 后续追问

- 这些 rewrite 是否增加 vreg 数量并导致 spill？需要 benchmark + regalloc stats。
- `MovConstPool` 的阈值“>2 movz/movk 且重复出现”是否适合所有 ARM cores？
- `MAdd` rewrite 是否可以进一步覆盖更多 address calculation pattern？
- `Call Imm -> bl(imm)` 后，`16c708f8` 的 rewrite 是否在某些场景又被 `ac92d1fa` 反向优化？

## 分类

- Primary layer: LIR postgen/postalloc
- Runtime pattern: all generated code with illegal/expensive ARM64 operand forms
- Correctness mechanism: explicit vregs, regalloc-visible temps, tests for rewritten LIR
- Performance mechanism: less hidden scratch use, smaller constants, legal ARM64 instruction forms
- ARM64 impact: 直接且高，是 4 月 ARM64 codegen 质量提升主线
