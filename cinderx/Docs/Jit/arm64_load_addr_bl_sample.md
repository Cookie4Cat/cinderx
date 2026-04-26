# ARM64 load_addr / bl(imm) 实验快照

## 目标

这条分支只保存 AArch64 backend/codegen cleanup：

- call target 是 immediate 时，尽量保留到 codegen，用 `bl(imm)` 交给 asmjit relaxation 选择 direct branch 或 address-table fallback。
- object pointer / absolute memory address load 使用 `load_addr` relocation 形式，减少手写 `movz/movk` materialization 和 scratch register 压力。
- AArch64 `rewriteCallInput()` 不再把 immediate call target 预先 rewrite 到 temporary register。

## 代码范围

- `cinderx/Jit/codegen/autogen.cpp`
- `cinderx/Jit/lir/postgen.cpp`
- `cinderx/ThirdParty/asmjit/src/asmjit/arm/*`
- `cinderx/ThirdParty/asmjit/src/asmjit/core/codeholder.*`
- `cinderx/ThirdParty/asmjit/test/asmjit_test_patching_a64.cpp`
- 相关 runtime / postgen tests

## ARM64 长跑结论

在 `/root/work/cinderx-arm-opt-20260426` 的 combined experiment 中，这条方向：

- build 通过
- JIT smoke 通过
- selected pyperformance fast run 没有显著 macro benchmark 变化

它更像 backend/codegen cleanup 和后续 ARM64 instruction-count 优化基础，不是当前 pyperformance 上已有强收益的 standalone optimization。
