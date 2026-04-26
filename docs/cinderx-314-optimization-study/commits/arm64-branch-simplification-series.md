# ARM64 branch simplification series

## 元信息

这篇合并 review 三个 2026-04-08 的 ARM64 branch simplification commits：

- `e0575b44e903bba153e3225245cda14ceddd42cb`, Kevin Newton, `Replace mov/blr with bl`
- `0f89ad81b371d745eccdf1c59c977919508c8102`, Kevin Newton, `Replace cmp/b with tbnz`
- `abef616d9a6266236eaaecc9f765ce00c71d9d74`, Kevin Newton, `Replace cmp/b_eq with cbnz`

主要 changed files:

- `cinderx/Jit/codegen/frame_asm.cpp`
- `cinderx/Jit/codegen/gen_asm.cpp`
- `cinderx/Jit/codegen/gen_asm_utils.cpp`
- `cinderx/Jit/codegen/autogen.cpp`

## 背景

这组三个 commit 都依赖 asmjit 新增的 ARM64 branch patching 能力。没有 branch patching，codegen 往往要先把目标地址 materialize 到 register，然后通过 register branch/call；或者用更通用的 compare + branch 组合。patching 能力成熟后，codegen 可以放心使用更短、更符合 ARM64 idiom 的 branch instruction。

## `e0575b44`: `mov/blr` -> `bl`

旧形状：

```asm
mov  scratch, target
blr  scratch
```

新形状：

```asm
bl   target
```

收益：

- 少一次 address materialization；
- 少用 scratch register；
- instruction count 更少；
- call target 对 branch predictor 更直接；
- code size 更小。

这个 commit 改到 `frame_asm.cpp`、`gen_asm.cpp`、`gen_asm_utils.cpp`，说明它影响的不只是普通 function body，也包括 trampoline/frame 相关 call sites。

## `0f89ad81`: `cmp/b` -> `tbnz`

`tbnz` 是 ARM64 的 test-bit-and-branch 指令。某些模式下原本要：

```asm
cmp  reg, mask/zero-like condition
b.ne label
```

现在可以：

```asm
tbnz reg, bit, label
```

这减少 compare instruction，并把 test + branch 融成一个更表达 intent 的 branch form。这个 commit 只改 `autogen.cpp`，说明它是 instruction translation pattern 的替换。

## `abef616d`: `cmp/b_eq` -> `cbnz`

`cbnz` 是 compare-and-branch-if-nonzero。某些原本的 compare/equal branch 可以改成：

```asm
cbnz reg, label
```

而不是：

```asm
cmp  reg, #0
b.ne label
```

这个 commit 改动非常小，但意义很明确：用 ARM64 原生 compact branch forms 替代通用 sequence。

## 和 postgen rewrite 的关系

这组三个 commit 和 `april-postgen-postalloc-rewrites.md` 是互补关系：

- postgen/postalloc series 解决 operand shape、scratch register visibility；
- branch simplification series 解决具体 ARM64 instruction selection。

先让 branch target/condition 的表达合法、可 patch，再选择更短 branch instruction。否则直接替换成 `bl`/`tbnz`/`cbnz` 可能会遇到 relocation/range 问题。

## 测试与 correctness

这类 commit 的 correctness 重点不是 Python semantic，而是：

- branch target 是否可 patch；
- range 超出时是否有 fallback/relaxation；
- relocation 是否正确；
- branch condition 是否完全等价；
- frame/trampoline call sites 是否和普通 call sites 一样安全。

如果测试只跑 x86 是看不出问题的。必须有 ARM64 backend/codegen tests 或实际 ARM64 CI。

## ARM64 方法论

学习这个 series 时可以提炼出一条规则：

> 先建立 patching/relocation 能力，再把通用 branch sequence 替换成 ARM64 原生 branch form。

这比在每个 call site 手工判断距离更稳，也让未来 `load_addr`、`bl(imm)` 这类优化有基础。

## 后续追问

- 这些 direct branch forms 的命中率如何统计？
- `bl(imm)` range 不够时 asmjit 如何 fallback？
- `tbnz/cbnz` 替换是否影响 flags live range？
- 是否还有 `tbz`、`cbz`、`b.cond` 等 pattern 没覆盖？

## 分类

- Primary layer: ARM64 codegen instruction selection
- Runtime pattern: calls, guard branches, zero/nonzero checks, bit checks
- Correctness mechanism: asmjit branch patching / relocation
- Performance mechanism: fewer instructions, fewer scratch registers, smaller branch sequences
- ARM64 impact: 直接性能/code size 优化
