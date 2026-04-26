# 8635acf5: Replace unlink frame generation with LIR

## 元信息

- Commit: `8635acf51a5221f1a3e8f7893d6412e68707da50`
- Date: 2026-03-16
- Author: Dino Viehland
- Reviewer: Alex Malyshev
- Layer: frame unlink / LIR generation / codegen
- Changed files:
  - `cinderx/Jit/codegen/frame_asm.cpp/h`
  - `cinderx/Jit/codegen/gen_asm*.{cpp,h}`
  - `cinderx/Jit/lir/blocksorter.cpp`
  - `cinderx/Jit/lir/generator.cpp`
  - `cinderx/Jit/lir/instruction.{h,cpp}`
  - `cinderx/Jit/lir/postalloc.cpp`
  - `cinderx/RuntimeTests/lir_test.cpp`

## Commit Message 要点

原先 unlink frame code 由 hand-generated assembly 生成，非常 fiddly。这个 commit 改成 LIR generation，并新增少量 custom generated instruction，例如 `EndEpilogue`。同时需要 `YieldExitPoint`，让 generated code 知道 yield exit 时跳哪里。

## 优化形状

旧形状：

```text
frame unlink semantics hidden in frame_asm
architecture-specific hand assembly
limited LIR/regalloc visibility
```

新形状：

```text
LIR generator emits unlink frame sequence
custom instruction handles epilogue boundary
block sorter / postalloc can see more structure
tests assert LIR behavior
```

## 代码实现 Review

`frame_asm.cpp/h` 仍存在，但部分 unlink generation 被搬走。`lir/instruction.h` 新增/调整 instruction，`generator.cpp` 负责生成 sequence，`postalloc.cpp` 处理 lowering 后的细节。

`YieldExitPoint` 很值得注意：yield/generator 不是普通 return，frame unlink 必须知道 exit target。这说明 frame optimization 不能只考虑 normal function return。

## 测试实现 Review

`RuntimeTests/lir_test.cpp` 更新说明这个 commit 主要用 LIR-level test 固化。阅读时建议找：

- generated unlink sequence；
- `EndEpilogue` 的 expected position；
- yield exit target；
- normal return 和 generator/yield return 是否不同。

## 和后续 commits 的关系

这是 `5029beec` 的前置：先把 unlink 移进 LIR，再把 frame linking/setup 移进 LIR。二者合起来减少 handwritten frame assembly。

## ARM64 启发

ARM64 下 handwritten frame asm 容易因为 ABI、stack alignment、callee-save、branch range 出问题。把 unlink 逻辑进 LIR 后，后端只处理指令选择，不再承担 frame protocol 语义。

## 后续追问

- unlink sequence 中是否还有 architecture-specific hidden register use？
- generator yield exit 是否还能进一步统一？
- `EndEpilogue` 是否只是过渡 instruction，未来能否普通化？
- ARM64 上 unlink path 是否有 code size 或 branch layout 问题？
