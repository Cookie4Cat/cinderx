# 5029beec: Move frame linking from assembly to LIR

## 元信息

- Commit: `5029beecc5a8a40986dadc93370112b5a3413fec`
- Date: 2026-04-09
- Author: Dino Viehland
- Reviewer: Alex Malyshev
- Layer: frame setup / LIR generation / codegen / regalloc
- Changed files:
  - `cinderx/Jit/codegen/frame_asm.cpp/h`
  - `cinderx/Jit/codegen/register_preserver.cpp/h`
  - `cinderx/Jit/codegen/gen_asm.cpp/h`
  - `cinderx/Jit/codegen/tls.cpp/h`
  - `cinderx/Jit/lir/generator.cpp/h`
  - `cinderx/Jit/lir/regalloc.cpp`
  - 大量 HIR expected output tests

## Commit Message 要点

这是 4 月非常重要的一次 structural optimization。commit message 说得很清楚：把 interpreter frame allocation/linking 从 handwritten assembly 移到 LIR generation，让 register allocator 能管理 frame setup 中的 registers。

主要变化包括：

- `generator.cpp` 新增大约 300 行 `emitLoadFrame()`，处理 normal frames、generator frames、lightweight frames 等；
- 新增 `kLoadThreadState` LIR instruction，用 TLS fast path load `tstate`；
- `regalloc.cpp` 为 thread-state loading 预留/处理 register；
- callee-saved register save/restore 从 SP-relative push/pop 改成 FP-relative fixed-offset `mov/stp/ldp`；
- 所有版本都 emit `LoadFrame` HIR；
- generator frame storage swap 时用 spill copy 保存 spilled register values；
- 删除 `frame_asm.cpp/h` 和 `register_preserver.cpp/h`，对应测试也移除；
- 20 多个 HIR expected tests 更新，加入 `LoadFrame`。

## 优化形状

旧形状：

```text
HIR/LIR knows function body
frame allocation/linking hidden in handwritten frame_asm
register allocator cannot see all frame setup temporaries
architecture-specific asm owns too much semantic logic
```

新形状：

```text
HIR emits LoadFrame
LIR generator emits explicit frame setup sequence
regalloc sees temporaries and reserved registers
codegen only lowers explicit LIR instructions
tests assert frame setup appears in HIR/LIR shape
```

这是“把隐式 runtime protocol 显式化”的典型优化。它不只是减少代码行，还把 frame setup 从 backend 特例变成 compiler pipeline 的一部分。

## 代码实现 Review

### 删除 handwritten assembly

删除 `frame_asm.cpp/h` 和 `register_preserver.cpp/h` 是一个强信号：官方不想让 frame linking 继续停留在手写汇编层。手写汇编的问题是：

- 每个架构需要维护一份特殊逻辑；
- regalloc 不知道 hidden register use；
- frame layout、generator resume、deopt、spill slots 之间的依赖难以测试；
- ARM64 ABI 差异会不断暴露 corner case。

### `emitLoadFrame()`

`emitLoadFrame()` 是新实现核心。它在 LIR generator 中处理：

- normal interpreter frame allocation/linking；
- lightweight frame；
- generator frame；
- spilled register values 在 generator storage 切换时的保存；
- thread state 获取；
- frame pointer / stack layout 相关细节。

学习时不建议一上来逐行读完。更好的顺序是：先看 HIR expected output 中 `LoadFrame` 的位置，再看 `emitLoadFrame()` 如何把这个单个 HIR concept 展开成 LIR sequence。

### `kLoadThreadState`

新增 `kLoadThreadState` 的意义是把 TLS/thread state loading 也变成明确 LIR instruction。这个和 ARM64 很相关，因为 TLS access 往往需要特定 register 或 ABI-specific sequence。把它显式化后，regalloc 和 codegen 能更清楚地协作。

### callee-saved register handling

commit message 提到从 SP-relative push/pop 变成 FP-relative fixed-offset save/restore。这类改动通常是为了让 frame layout 更稳定，也便于在 frame setup 中访问固定位置。对 ARM64 来说，`stp/ldp` pair 和 FP-relative layout 更符合 ABI-friendly codegen。

## 测试实现 Review

这个 commit 的测试覆盖非常广：

- `hir_frame_state_test.cpp`
- `hir_test.cpp`
- 许多 `RuntimeTests/hir_tests/*.txt`
- 删除旧 `register_preserver_test.cpp`

为什么这么多 expected output 变化？因为 `LoadFrame` 是每个 compiled function 的入口级概念。只要 HIR pipeline 打印函数，就会看到 frame loading/linking 的形状变化。

学习时可以挑三类 test：

- simple function 的 `LoadFrame` expected output；
- generator/yield 相关 expected output；
- refcount insertion 后 `LoadFrame` 与 frame state/deopt 的关系。

## 和前后 commits 的关系

- `5bfab630` 先启用 lightweight frames；
- `659606ab` 把 frame loading 建模成 dedicated opcode；
- `8635acf5` 把 unlink frame generation 移到 LIR；
- `5029beec` 把 linking/setup 也移到 LIR；
- 后续 `4a563280`、`1f50e895`、`0d150eb5`、`68e3fe80` 继续把 resume/trampoline/return box/deopt pieces 移进 LIR。

这是一条很明确的官方路线：减少 handwritten asm，把 runtime transition protocol 纳入 LIR。

## ARM64 启发

ARM64 上这类改动价值很高：

- frame setup register pressure 更可控；
- hidden scratch register 使用减少；
- ABI-specific code 更集中；
- tests 更容易覆盖；
- 后续 postalloc/postgen rewrite 可以处理 frame setup 中的 LIR。

如果我们要优化 ARM64 CinderX，frame/prologue/epilogue 一定要看这条线，而不是只盯 hot loop body。

## 后续追问

- `emitLoadFrame()` 生成的 ARM64 LIR 是否还有冗余 moves？
- `kLoadThreadState` 的 TLS fast path 在 ARM64 上是否最佳？
- generator frame 的 spill copy 是否在某些 workload 中可避免？
- fixed FP-relative layout 是否能帮助更多 stack slot addressing optimization？

## 分类

- Primary layer: LIR generation / frame runtime protocol
- Runtime pattern: function entry, frame allocation/linking, generator frame setup
- Correctness mechanism: explicit `LoadFrame`, frame state tests, spill preservation
- Performance mechanism: remove hidden assembly protocol, let regalloc manage temporaries
- ARM64 impact: 高，减少 ABI/scratch/register-pressure 风险
