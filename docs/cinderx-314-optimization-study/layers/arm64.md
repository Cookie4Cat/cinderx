# ARM64 Backend 优化线索

## 主线判断

2 月是 ARM64 bring-up，3 月开始修 correctness 和 handwritten asm 冲突，4 月进入真正的 backend shaping：branch patching、direct branch、constant/address loading、hot/cold allocation range、scratch register removal。

读 ARM64 commit 时要先分类：是 enablement、correctness、code size、instruction selection、register-pressure reduction，还是 benchmark/CI 支撑。不能把所有 “Fix ARM” 都当同一类性能优化。

## 2 月: make it run

`d37552a7` 让 AArch64 通过 CinderX JIT architecture check，是 ARM64 JIT 路径真正打开的点。随后一串 commit 修 large stack frame immediate、subword register size、cmp large immediate、FP register encoding、stack alignment 等问题。

这些多数是 correctness enablement。它们的性能意义是：如果 backend 因 invalid immediate 或 register encoding 失败，函数根本不会 JIT，真实 workload 就退回解释器。

## 3 月: handwritten asm 与 scratch register

`3e2494ed` 调整 ARM64 `reg_scratch`，避免和手写 asm 冲突。`fcf5a54a` 避免 aarch64 上使用 xor-ing pattern。`fabd3377` 修 large frame 下 `linkLightWeightFunctionFrame` SIGSEGV。

这阶段的问题说明 handwritten asm 与固定 scratch register 会不断制造架构细节 bug。因此 3/4 月 frame LIR 化和 postgen rewrite 是自然演进。

## 4 月: branch patching 和 direct branch

4 月 8 日的 branch patching 系列让 ARM64 codegen 能使用更短 branch form：

- `mov/blr` -> `bl`
- `cmp/b` -> `tbnz`
- `cmp/b_eq` -> `cbnz`

这些优化减少 instruction count、scratch register use 和 code size。它们依赖 asmjit 的 patching/relocation 能力，所以正确顺序是先补 patching，再改 instruction selection。

## 4 月: address materialization

`bef6366b` 添加 `load_addr`，根据距离选择 `adr`、`adrp+add`、`ldr`，避免默认 `movz/movk` 四指令序列。`ac92d1fa` 进一步使用 `bl(imm)`，避免先 load address 再 branch。

这类优化是 ARM64 特有的高频问题：地址和大常量 materialization 是 code size hotspot。

## 4 月: hot/cold layout

`afc7de79` 修 hot/cold splitting 在 ARM 上的 displacement 问题。hot/cold splitting 本来是 layout 优化，但如果 cold page 太远，branch displacement 不够，反而导致 `InvalidDisplacement`，函数无法 JIT。

这提醒我们：code layout optimization 必须同时考虑 branch reachability。

## 4 月: operand constraints 和 scratch register

postgen/postalloc series 是 ARM64 backend 质量提升的核心：

- immediate 不能 encode -> `Move Imm -> vreg`
- FP guard 需要 GP -> rewrite
- LEA 需要 temp -> `MAdd`
- type guard load -> explicit `Move Ind`
- call target -> explicit vreg 或 direct `bl`
- memory input 不支持 -> load into register

这条线的目标是让 regalloc 看见 temporary，而不是 emitter 偷偷占 scratch。

## 学习顺序

建议按这个顺序读 ARM64 文档：

1. `d37552a7-aarch64-support.md`: 知道起点。
2. `april-postgen-postalloc-rewrites.md`: 理解 operand constraint 方法论。
3. `arm64-branch-simplification-series.md`: 理解 branch patching 后的 instruction selection。
4. `arm64-load-addr-bl-series.md`: 理解 address materialization。
5. `afc7de79-hot-cold-arm.md`: 理解 code layout 和 branch range。

## 我们后续可做的实验

- 统计 generated ARM64 code 中 `movz/movk` 数量；
- 统计 helper call target 是否仍通过 register branch；
- 统计 postgen/postalloc rewrite 前后 spill 数；
- 用 fastmark/nbody/fannkuch 对比 code size 和 runtime；
- 找出仍在 emitter 内部使用 scratch register 的路径。
