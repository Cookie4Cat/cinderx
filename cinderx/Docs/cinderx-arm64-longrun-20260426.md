# CinderX ARM64 长跑优化实验记录 2026-04-26

## 实验目标

这轮实验围绕 CPython 3.14 + CinderX on ARM64，按“先观察，再小 patch，再 pyperformance 验收”的方式验证官方 4 月优化思路能否在当前 worktree 上带来稳定收益。

远端实验目录：

- `/root/work/cinderx-arm-opt-20260426/base-src`
- `/root/work/cinderx-arm-opt-20260426/opt-src`
- `/root/work/cinderx-arm-opt-20260426/results`
- `/root/work/cinderx-arm-opt-20260426/scripts`

构建环境：

- ARM64 Linux
- GCC 14.2: `/opt/gcc-14.2/bin/gcc`
- CPython 3.14: `/opt/python-3.14/bin/python3.14`
- pyperformance: `/opt/python-3.14/bin/pyperformance`

## JIT 生效 Gate

所有 pyperformance run 前都跑了 smoke script，并且 pyperformance worker 通过 `sitecustomize.py` bootstrap 逐进程验证 JIT 生效。

smoke gate 检查项：

- `import cinderx, cinderx.jit`
- `cinderx.jit.is_enabled() == True`
- `cinderx.jit.force_compile(probe) == True`
- `cinderx.jit.is_jit_compiled(probe) == True`

关键日志：

- `results/jit-smoke-base.log`
- `results/jit-smoke-opt.log`
- `results/jit-smoke-opt-current.log`
- `results/bench-base-fast-jit-bootstrap.log`
- `results/bench-opt-fast-current-jit-bootstrap.log`

## Baseline

baseline 使用当前 worktree HEAD 对应源码构建 wheel，benchmark 命令覆盖：

`richards,deltablue,nbody,spectral_norm,fannkuch,float,json_loads,regex_compile,pathlib`

baseline fast 结果：

| benchmark | base mean |
| --- | ---: |
| deltablue | 17.0 ms |
| fannkuch | 930 ms |
| float | 405 ms |
| json_loads | 61.2 us |
| nbody | 238 ms |
| pathlib | 54.2 ms |
| regex_compile | 411 ms |
| richards | 152 ms |
| spectral_norm | 251 ms |

文件：

- `results/bench-base-fast.json`
- `results/bench-base-fast.log`

## Candidate A: AArch64 load_addr + bl(imm)

来源：

- `ac92d1fa` Use bl(imm) more
- `bef6366b` Add load_addr to aarch64 emitter

优化机制：

- AArch64 direct call target 可以用 `bl(imm)`，避免先把 call target materialize 到 register。
- Object immediate / memory address load 使用 `load_addr` relocation 形式，减少 `movz/movk` 序列和 scratch register 压力。
- postgen 对 AArch64 `Call` immediate input 不再强制 rewrite 到 temporary register。

代码面：

- `cinderx/Jit/codegen/autogen.cpp`
- `cinderx/Jit/lir/postgen.cpp`
- `cinderx/ThirdParty/asmjit/src/asmjit/arm/*`
- `cinderx/ThirdParty/asmjit/src/asmjit/core/codeholder.*`
- `cinderx/RuntimeTests/backend_test.cpp`
- `cinderx/RuntimeTests/lir_postgen_test.cpp`
- `cinderx/ThirdParty/asmjit/test/asmjit_test_patching_a64.cpp`

结果：

- 构建通过。
- JIT smoke 通过。
- `bench-base-fast.json` vs `bench-opt-fast.json`: 全部 benchmark not significant。
- 方向保留为 backend/codegen cleanup，但本轮没有 macro benchmark 级别的稳定收益。

## Candidate B: Compact Long Guards

来源：

- `4c280add` Optimize LongCompare for compact longs
- 适配测试：`0e2820b7` Support IntBinaryOp on CBool arguments

优化假设：

- 对 LongCompare 增加 compact long guard 后，把 compact long unbox 成 primitive compare，减少 generic long compare 路径。
- `CBool & CBool` 直接进入 `IntBinaryOp`，去掉中间 `IntConvert(TCUInt8)`。

结果：

- 构建通过。
- JIT smoke 通过。
- 开启 `PYTHONJITCOMPACTLONGGUARDS=1` 后，`regex_compile` 出现稳定显著回退。

对比：

- `bench-base-fast-compact.json` vs `bench-opt-fast-compact.json`
- `regex_compile`: `414 ms -> 427 ms`, `1.03x slower`, significant

加入 CBool/IntBinaryOp 简化后：

- `bench-base-fast-compact.json` vs `bench-opt-fast-compact-cbool.json`
- `regex_compile`: `414 ms -> 423 ms`, `1.02x slower`, significant

结论：

- 当前树上不保留 compact-long guarded patch。
- 这条优化可能需要更细的 profitability gate，不能简单打开全局 flag。
- 后续如果继续做，需要先 dump `regex_compile` 中 `_compile_info` / `SubPattern.__getitem__` / `Tokenizer.*` 的 HIR，确认 guard 增量、deopt 次数和 code size。

## Candidate C: Rebound Module Global Exact-Type Guard

来源：

- `73246d20` JIT: use exact-type guards for rebound module globals

优化机制：

- 对 module global，如果当前 module 内函数会 `STORE_GLOBAL` rebound 该名字，`LOAD_GLOBAL` 结果不再用 object identity guard。
- 对 heap type global value 改用 exact-type guard：`LOAD_GLOBAL_TYPE: name`。
- 这样可以保留 “同 exact type 的新 object” 场景，避免 rebound global 之后频繁 guard miss。

代码面：

- `cinderx/Jit/hir/builder.cpp`
- `cinderx/PythonLib/test_cinderx/test_cinderjit.py`
- `cinderx/RuntimeTests/hir_test.cpp`

本地适配：

- 只引入 rebound module global 相关测试。
- 没有混入依赖 `392433d1` / `5f955fb8` 的 instance-value attr 测试。

结果：

- 与 Candidate A 一起构建 opt wheel。
- JIT smoke 通过。
- `bench-base-fast.json` vs `bench-opt-fast-current.json`: 全部 benchmark not significant。

对比摘要：

| benchmark | base | opt current | compare |
| --- | ---: | ---: | --- |
| deltablue | 17.0 ms | 16.2 ms | 1.04x faster, not significant |
| fannkuch | 930 ms | 927 ms | not significant |
| float | 405 ms | 408 ms | not significant |
| json_loads | 61.2 us | 61.1 us | not significant |
| nbody | 238 ms | 238 ms | not significant |
| pathlib | 54.2 ms | 54.6 ms | not significant |
| regex_compile | 411 ms | 413 ms | not significant |
| richards | 152 ms | 153 ms | not significant |
| spectral_norm | 251 ms | 253 ms | not significant |

文件：

- `results/bench-opt-fast-current.json`
- `results/bench-opt-fast-current.log`
- `results/compare-base-opt-fast-current.txt`

## 当前保留 Patch

当前本地 staged patch 保留两个 neutral but clean candidates：

1. AArch64 `load_addr` + `bl(imm)` codegen cleanup
2. CPython 3.14 rebound module global exact-type guard

它们都没有显著 pyperformance macro gain，但也没有显著 regression。是否作为最终 patch 保留，要看下一轮是否能补上更针对性的 benchmark 或 micro benchmark。

## 下一步建议

优先级最高的下一轮：

1. 单独构造 rebound module global microbenchmark，验证 `GuardIs` -> `GuardType` 是否真的减少 deopt/guard miss。
2. 继续接入 `392433d1` 和 `5f955fb8`，但要按依赖顺序完整引入 instance-value attr / `LOAD_ATTR_METHOD_WITH_VALUES` 实现和测试。
3. 对 `regex_compile` 收集 selected HIR/LIR/ASM dump，重点看 `SubPattern.__getitem__` 的 `BinaryOp`、`_optimize_charset` 的 `StoreSubscr`、`Tokenizer.match` 的 `GuardType`。
4. 对 AArch64 `load_addr/bl(imm)` 做 code-size/asm count micro validation，因为 pyperformance fast run 太粗，可能看不到 instruction count 变化。

本轮结论：

- compact-long guards 是明确 negative result，不应保留。
- AArch64 codegen cleanup 和 rebound global guard 是 neutral result，能作为下一轮继续叠实验的干净基础。
