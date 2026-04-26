# d37552a7: aarch64 support

## 元信息

- Commit: `d37552a7be6f8f75d84ef19929c2e49978656a2c`
- Date: 2026-02-18
- Author: Kevin Newton
- Reviewers: Jacob Bower, Dino Viehland
- Layer: ARM64 enablement / architecture detection / JIT startup gating
- Changed files:
  - `cinderx/Jit/codegen/arch/detection.h`
  - `cinderx/Jit/pyjit.cpp`
  - `cinderx/TestScripts/3.12-opt-arm64-failures.txt`

## Commit Message 要点

这个 commit 让 AArch64 通过 CinderX JIT 的初始 architecture check。message 很短，但意义很大：从这个点开始，ARM64 不再只是 build target，而是 CinderX JIT 的可运行 target。

## 优化形状

这不是性能优化，而是 enablement：

```text
previous JIT arch gate rejects non-x86 or incomplete ARM64
  -> detection.h / pyjit.cpp allow aarch64
  -> ARM64 JIT path starts running
  -> failure list records remaining known gaps
```

它打开了后续所有 correctness 和 performance 工作。

## 代码实现 Review

`arch/detection.h` 负责 architecture detection。`pyjit.cpp` 是 JIT startup gate，决定当前 build/runtime 是否允许启用 JIT。`3.12-opt-arm64-failures.txt` 记录已知失败测试。

学习时要特别注意 failure list：它提醒我们 ARM64 support 初期不是“全部稳定”，而是“允许跑，并系统性修失败”。

## 时间线意义

2 月后续紧跟了一串 ARM64 fixes：

- large stack frame immediate；
- subword register sizes；
- cmp large immediate；
- double overflow args；
- FP register encoding；
- stack alignment；
- `getIP`；
- frame asm large frame SIGSEGV。

这些都说明 `d37552a7` 是 bring-up 起点，而不是优化终点。

## 测试与 correctness

ARM64 enablement 的测试策略不同于普通 optimization：

- 先维护 failure list；
- 跑 RuntimeTests/backend/regalloc；
- 修 invalid immediate/register encoding；
- 再逐步打开 CI 和 wheels。

到 4 月 `f9c0ce93` 才添加 ARM CI 和 ARM wheels，这说明官方也是逐步推进。

## ARM64 启发

做 ARM64 优化前必须区分：

- function 是否真的 JIT 了；
- 是否因为 invalid displacement/immediate fallback；
- 是否因为 failure list 跳过；
- 是否只是解释器在跑。

否则 benchmark 结果会误导。

## 后续追问

- 当前 main 上 ARM64 failure list 是否已经清空或缩小？
- 哪些 tests 是 JIT enabled 的 ARM64 failures，哪些是 JIT disabled 也失败？
- JIT startup gating 是否记录了禁用原因？
- benchmark 前是否能打印 compiled function count？
