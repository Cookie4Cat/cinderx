# bef6366b / ac92d1fa: ARM64 load_addr and bl(imm)

## 元信息

- `bef6366b1ff0bf553d964be63491711fa449a7d8`, 2026-04-22, Kevin Newton, `Add load_addr to aarch64 emitter`
- `ac92d1fabc45fa258c9d0412838f8fd3427a0399`, 2026-04-22, Kevin Newton, `Use bl(imm) more`
- Layer: ARM64 address materialization / call lowering / asmjit patching
- Changed files:
  - `cinderx/Jit/codegen/autogen.cpp`
  - `cinderx/Jit/lir/postgen.cpp`
  - `cinderx/RuntimeTests/backend_test.cpp`
  - `cinderx/RuntimeTests/lir_postgen_test.cpp`
  - `cinderx/ThirdParty/asmjit/src/asmjit/arm/*`
  - `cinderx/ThirdParty/asmjit/test/asmjit_test_patching_a64.cpp`

## Commit Message 要点

`bef6366b` 解决 address loading 的 code size 问题：以前很多地方用 `mov` 把 address 放进 register。对 ARM64 来说，这几乎总是 4 条 `movz/movk` 组合。新的 `load_addr` 根据 target distance 选择：

- very close: `adr`
- mildly close: `adrp + add`
- far: `ldr`

commit message 说无论哪种，通常都是 2 条 instruction，而不是 4 条。

`ac92d1fa` 接着更激进地使用 `bl(imm)`：关闭 aarch64 上部分 `rewriteCallInput` for immediate，并补更多“先 load address 再 branch”的地方。

## 优化形状

旧形状：

```asm
movz/movk/movk/movk  reg, absolute_address
blr                 reg
```

或：

```asm
movz/movk/movk/movk  reg, absolute_address
; later use reg as address
```

新形状：

```asm
adr      reg, near_target
```

或：

```asm
adrp     reg, page(target)
add      reg, reg, pageoff(target)
```

或：

```asm
ldr      reg, literal_pool_slot
```

对 call:

```asm
bl       target
```

## 代码实现 Review

### asmjit 扩展

`bef6366b` 修改 vendored asmjit 的 AArch64 emitter 和 codeholder，并新增 `asmjit_test_patching_a64.cpp` 大量测试。这说明 CinderX 不是只在自己 codegen 上做 pattern hack，而是补了底层 assembler/linker 能力。

这种改法更稳：上层 autogen 可以表达“load address”，底层根据距离和 relocation 决定具体形式。

### `autogen.cpp`

CinderX codegen 中原本直接用 `mov` 的地方改用 `load_addr`。这把“我要一个地址”从“用 mov 拼出来”升级成“让 AArch64 emitter 选最优序列”。

### `postgen.cpp`

`ac92d1fa` 调整 aarch64 上的 call input rewrite。之前 `16c708f8` 会把 imm call target 改成 `Move -> vreg -> Call vreg`，这是为了避免 hidden scratch；但有了 `bl(imm)` 和 branch patching 后，某些 immediate call 直接 `bl` 更好。因此这里不是推翻 `16c708f8`，而是在 ARM64 能直接 branch 时走更优路径。

## 测试实现 Review

测试分两层：

- asmjit 层：验证 AArch64 patching、ADR/ADRP/LDR 选择、range/relocation。
- CinderX 层：`backend_test.cpp`、`lir_postgen_test.cpp` 验证 LIR/codegen expected shape。

这是 ARM64 优化常见结构：底层 assembler 能力先补齐，上层 JIT 才能安全使用更短 sequence。

## 和 branch simplification series 的关系

4 月 8 日的 branch simplification 用 `bl`、`tbnz`、`cbnz` 替代更长序列；4 月 22 日这组进一步补 address materialization 和 more `bl(imm)`。两者共同目标都是减少：

- register target branch；
- scratch register pressure；
- 4-instruction address materialization；
- branch/call sequence code size。

## ARM64 启发

ARM64 上 address 是一等优化对象。x86_64 经常可以用 RIP-relative addressing 或 large immediate support 掩盖问题；AArch64 必须在 `adr`、`adrp+add`、literal load、movz/movk 之间做选择。

后续我们做 ARM64 优化时，应主动找：

- 频繁 materialize helper address 的地方；
- call target 先 load 再 `blr` 的地方；
- repeated constants/address literals；
- near target 但没有用 `adr`/`bl` 的地方。

## 后续追问

- `load_addr` 的选择策略是否能暴露统计，用于看 near/mid/far target 分布？
- literal pool placement 是否会和 hot/cold splitting 互相影响？
- `bl(imm)` 更多使用后，是否减少了 register pressure 或 spills？
- 还有哪些 runtime helper call 没有走 direct branch？

## 分类

- Primary layer: ARM64 emitter / asmjit / postgen
- Runtime pattern: address loading, helper calls, trampoline calls
- Correctness mechanism: relocation and branch patching tests
- Performance mechanism: fewer movz/movk, more direct branches, less scratch use
- ARM64 impact: 直接，属于 code size + call sequence 优化
