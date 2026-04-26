# 5bfab630: Enable lightweight frames

## 元信息

- Commit: `5bfab6307856158729e838b10e6d11e5fd23e4b9`
- Date: 2026-02-03
- Author: Jacob Bower
- Reviewer: Dino Viehland
- Layer: frame runtime / frame asm / LIR generator
- Changed files:
  - `cinderx/Jit/codegen/frame_asm.cpp`
  - `cinderx/Jit/codegen/frame_asm.h`
  - `cinderx/Jit/frame.cpp`
  - `cinderx/Jit/lir/generator.cpp`

## Commit Message 要点

这个 commit 启用 lightweight frames。message 说只需要两件事：

- 修 free-threading 下的 incref；
- frame initialization 时把 TLBC 设置为 0。

TLBC 为 0 表示当前运行的是“未修改 bytecode”。只有 deopt 时才需要非 0 TLBC，因为 deopt 会回到解释器语义，需要知道 bytecode mapping。message 还强调，除了初始化和 deopt，在别的时候设置非 0 TLBC 通常是不合法的，因为执行线程可能不是生成该值的线程。

## 优化形状

lightweight frame 不是单条 instruction 优化，而是降低 JIT frame 管理成本。它让 JIT 在 hot path 中少依赖完整 interpreter frame，同时仍保留 deopt/reify 所需的信息。

可以把它理解成：

```text
full interpreter frame protocol
  -> lightweight frame for normal JIT execution
  -> materialize/link full frame only when needed
```

这条线后续继续发展成 frame unlink/link LIR 化。

## 代码实现 Review

`frame_asm.cpp/h` 说明当时 frame 逻辑仍有手写 asm；`frame.cpp` 负责 frame representation/runtime behavior；`lir/generator.cpp` 则说明 lightweight frame 会影响 LIR 生成的 entry/exit shape。

学习时重点看：

- frame 初始化时 TLBC 如何设置；
- free-threading incref path 如何保证安全；
- lightweight frame 和 deopt frame materialization 如何连接；
- `lir/generator.cpp` 是否在 function entry/exit 处少做 full frame work。

## 测试与 correctness

这个 commit 的 correctness 风险比性能风险更高：

- deopt 时是否能恢复正确 bytecode/frame state；
- frame reification 是否还能看到需要的信息；
- free-threading 下 incref 是否符合 ownership/atomic 规则；
- generator/coroutine frame 是否有特殊路径。

后续大量 frame LIR 化 commit 说明这个区域很敏感。

## 和后续 commits 的关系

- `659606ab`: 把 frame loading 变成 dedicated HIR opcode；
- `8635acf5`: 把 unlink frame generation 移到 LIR；
- `5029beec`: 把 frame linking/setup 移到 LIR。

`5bfab630` 是这条 frame optimization series 的前置点。

## ARM64 启发

ARM64 上 prologue/epilogue、callee-saved register、TLS/thread state、frame pointer layout 都更容易受 ABI 影响。lightweight frame 能减少 hot path 的 frame 工作，但真正可维护的方向是把 frame protocol 逐渐显式化到 HIR/LIR。

## 后续追问

- lightweight frame 在哪些 workload 中减少最多 frame overhead？
- ARM64 上 lightweight frame entry/exit 是否仍有多余 spills？
- deopt-heavy workload 下 lightweight frame 是否会因为 reification 抵消收益？
- free-threading 下后续 inline refcount 是否能进一步改善 frame path？
