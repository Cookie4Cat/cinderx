# 659606ab: Move frame loading to dedicated opcode

## 元信息

- Commit: `659606ab0973849d652e0e6700cc54746860ecc4`
- Date: 2026-02-17
- Author: Dino Viehland
- Reviewer: Kevin Newton
- Layer: HIR opcode / frame loading / LIR generation
- Changed files:
  - `cinderx/Jit/hir/builder.cpp`
  - `cinderx/Jit/hir/hir.{h,cpp}`
  - `cinderx/Jit/hir/hir_ops.h`
  - `cinderx/Jit/hir/parser.cpp`
  - `cinderx/Jit/hir/printer.cpp`
  - `cinderx/Jit/hir/ssa.cpp`
  - `cinderx/Jit/lir/generator.cpp`

## Commit Message 要点

之前 function entry point 中有 custom code 把 interpreter frame load 到 register。x64 上可工作，但 ARM 上 regalloc 不知道这段 custom code 与 incoming arguments 的关系，可能把 temporary 分配到会 clobber input 的 register。

这个 commit 把 frame loading 变成 explicit HIR instruction，并放在 `LoadArg` ops 后面。

## 优化形状

旧形状：

```text
entry custom code loads frame
regalloc does not see this side effect
LoadArg appears later
ARM temporary may clobber input
```

新形状：

```text
LoadArg
LoadFrame  # explicit HIR opcode
normal SSA/LIR pipeline
regalloc sees dependencies
```

这不是单纯性能优化，而是让 IR 正确建模 hidden state。正确建模后才有后续优化空间。

## 代码实现 Review

这个 commit touched 几乎所有 HIR infrastructure 文件，说明新增的是一等 opcode：

- `hir_ops.h`: opcode registry；
- `hir.h/cpp`: instruction class/behavior；
- `instr_effects.cpp`: side effects；
- `parser/printer`: textual HIR 支持；
- `ssa/pass`: pass pipeline 能识别它；
- `builder.cpp`: 生成位置；
- `lir/generator.cpp`: lowering。

学习时重点看 `builder.cpp` 中 `LoadFrame` 相对 `LoadArg` 的位置，这是 commit message 里指出的 bug 根因。

## 测试与 correctness

测试应关注 HIR expected output 中 `LoadFrame` 的出现位置。这个位置不只是美观问题，而是 regalloc/liveness 正确性的前提。

## ARM64 启发

这篇是 ARM64 bug 推动 IR 设计改进的好例子。遇到 ARM64 register clobber，不要马上换 scratch register；如果根因是 compiler pipeline 看不见某个 side effect，就应该把它建模成 HIR/LIR。

## 后续追问

- 还有哪些 entry/prologue side effects 没有进入 HIR/LIR？
- `LoadFrame` 后续在 `5029beec` 中如何展开成 frame linking LIR？
- ARM64 下 incoming arguments 和 frame loading temporary 的 live range 是否还有冲突？
- 是否能用 HIR verifier 检查 `LoadFrame` 必须在 `LoadArg` 后？
