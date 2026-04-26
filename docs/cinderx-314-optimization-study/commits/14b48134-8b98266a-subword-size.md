# 14b48134 / 8b98266a: subword move/load/store support

## 元信息

- `14b48134fb3292845e65e0d1c34b248bb1150cfd`, 2026-02-13, Dino Viehland, `Add postalloc rewrite for mov instructions`
- `8b98266a617dda3b56b1ccb371eeb165f6cdcedd`, 2026-02-13, Dino Viehland, `Use opcodes to load/store specific size`
- Layer: LIR postalloc / codegen autogen / ARM64 operand-size support
- Changed files:
  - `cinderx/Jit/lir/postalloc.cpp`
  - `cinderx/Jit/codegen/autogen.cpp`

## Commit Message 要点

`14b48134` 说 autogen 可以处理 mov instructions，但不能处理 8-bit/16-bit registers，所以新增 postalloc rewrite，把 register-to-register 和 immediate-to-register moves promote 到 32-bit。

`8b98266a` 则添加 8-bit/16-bit memory load/store variants。它把 size 信息从隐式类型推断变成 opcode/translation 明确表达。

## 优化形状

这组不是“快多少”的优化，而是 backend shape 的基础建设：

```text
subword value appears in LIR
  -> register move cannot use 8/16-bit GP register form on ARM64
  -> postalloc promotes move to legal 32-bit form
  -> memory load/store uses explicit 8/16-bit variant when needed
```

如果没有这类 rewrite，ARM64 codegen 容易在后端最后阶段失败，或者用不正确的 register width。

## 代码实现 Review

### `postalloc.cpp`

postalloc 发生在 register allocation 后，因此它能看到最终 register classes 和 sizes。`14b48134` 在这里 rewrite mov，说明问题是“最终 physical/register operand shape 不合法”，不是 HIR 层语义问题。

### `autogen.cpp`

`8b98266a` 在 autogen translation 中添加 specific size load/store。学习时要看它如何区分 byte/halfword/word/dword load store，以及 signed/unsigned extension 是否由其他 instruction 负责。

## 测试与 correctness

要关注两类 correctness：

- value width: 8/16-bit value move promote 到 32-bit 后，高位是否会影响后续 use；
- memory width: load/store 是否真的按 element type 的 size 访问内存。

如果后续看到 odd subword bug，比如 bool、int8 array、uint16 field，应该回到这组 commit 的思路。

## ARM64 启发

ARM64 没有 x86 那种自由的 8/16-bit general register 操作模型。很多 subword 操作需要通过 32-bit register form、load/store variant、extend/truncate 组合表达。

所以 ARM64 优化不是只“少指令”，也包括“把 type width 正确显式化”。显式之后，后续 pass 才能安全消除 redundant extend/move。

## 后续追问

- subword promote 是否引入多余 zero/sign extension？
- 8/16-bit load/store variant 在 ARM64 autogen 中是否覆盖所有 HIR type？
- `StoreArrayItem` direct lowering 后是否复用这些 sized store 能力？
- bool/CBool path 是否还能进一步利用 32-bit canonicalization？
