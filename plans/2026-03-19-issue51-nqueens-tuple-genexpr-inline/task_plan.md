# Task Plan: Issue 51 tuple(genexpr) inline for bm_nqueens

## Goal
在 ARM `124.70.162.35` 上继续优化 `pyperformance` `bm_nqueens`，把
`permutations()` 热路径里的 `tuple(genexpr)` 从生成器协议开销改写为平坦
collector 循环，同时不引入 `generators`、`coroutines`、`comprehensions`、
`richards`、`richards_super`、`float`、`go`、`deltablue`、`raytrace`、
`nqueens`、`nbody`、`unpack_sequence`、`fannkuch`、`coverage`、`scimark`、
`spectral_norm`、`chaos`、`logging` 的明显性能回退或功能回归。

## Workflow
1. Brainstorming
2. Writing-Plans
3. Test-Driven-Development
4. Verification-Before-Completion

## Remote Test Entry
- 统一远端入口: `scripts/arm/remote_update_build_test.sh`
- 所有 ARM smoke / targeted tests / direct benchmark / pyperformance subset
  都通过该入口上的 `EXTRA_TEST_CMD`、`EXTRA_VERIFY_CMD`、`POST_PYPERF_CMD`
  注入，不直接在远端裸跑独立命令。

## Scheduler
- Shared DB: `plans/remote-scheduler.sqlite3`
- Local lease helper: `C:/work/code/generators/scripts/remote_scheduler.ps1`
- ARM host: `124.70.162.35`
- x86 host: `106.14.164.133`

## Brainstorming
- 已知 Issue #36 / commit `c3ac4a6f` 已把 `set(genexpr)` 降成 builder-time
  inline collector，并用 `MakeFunctionConstFold` 清掉 simple no-closure case
  的残余 `MakeFunction`。
- `bm_nqueens` 下一热点在 `permutations()`，尤其是两个
  `yield tuple(pool[i] for i in indices...)`。
- 重要纠偏:
  - 在当前 3.14 字节码里，`tuple(genexpr)` 已被 Python 编译器改写为
    `BUILD_LIST -> MAKE_FUNCTION -> CALL 0 -> FOR_ITER/LIST_APPEND ->
    LIST_TO_TUPLE`
  - 所以真正还要干掉的是:
    - generator function allocation
    - generator object creation
    - `YIELD_VALUE/RESUME` 往返
- 最可能的安全实现:
  - 复用 issue36 的 nested genexpr builder rewrite
  - 把 collector 从 `MakeSet/SetSetItem` 切成 `MakeList/ListAppend`
  - 在 inline exit 处显式 `MakeTupleFromList`
  - 继续复用现有 `MakeFunctionConstFold` 清 simple case 的 dead
    `MakeFunction`
- 最大风险:
  - closure/freevar genexpr 的 frame state 或异常语义被破坏
  - 误把 shadowed `tuple`、非目标 bytecode 形状、或跨块变体也吃进去
  - 为了追求 HIR 变短而牺牲广义 correctness

## TDD Plan
- 先补 ARM runtime 定位测试:
  - `tuple(genexpr)` simple case 消除 generator call
  - `tuple(genexpr)` closure case 消除 generator call
  - simple / closure 的异常行为保持不变
- 再补一个最小 HIR 计数信号，确保目标 shape 至少移除
  `CallMethod`，并出现 `MakeList + ListAppend + MakeTupleFromList`。
- 本地测试先过，再申请远端 compile / verify / benchmark lease。

## Verification Plan
- ARM:
  - 远端入口 smoke
  - `test_arm_runtime.py` 新增的 tuple(genexpr) targeted tests
  - `bm_nqueens` direct benchmark
  - 用户列出的回归敏感 benchmark subset
- x86:
  - 仅在 ARM 结果稳定后做匹配验证，确认没有功能差异
- 关键结果统一写入 `findings.md`

## Stage Plan
- Round 1 / HIR:
  - 先做 builder-time `tuple(genexpr)` inline
  - 不碰 LIR / codegen，除非 HIR 方案证据明确不足
- Round 1 / LIR:
  - 仅在 HIR 之后仍残留多余 collector/runtime helper 时再进入
- Round 1 / codegen:
  - 仅在 LIR 证据明确指出指令选择仍是主瓶颈时再进入

## Repeat-Error Prevention
- 不要把这轮优化描述成“outer tuple call elimination”；当前 3.14 真实目标是
  `CALL 0` 生成 generator object 和 `YIELD/RESUME` 协议。
- 没有新增 guardrail 前，不重复尝试之前已经被否掉的广义 range
  specialization 思路。
- 不把 direct benchmark 和 pyperformance subset 数字混成一个结论。

## Status
- [completed] Brainstorming: 复用 issue36 路线并纠正当前 3.14 bytecode 形状
- [completed] Writing-Plans: case-local 文件已创建
- [completed] Test-Driven-Development: tuple(genexpr) simple/closure/exception/yield tests 已落地并在 ARM 上通过
- [completed] Verification-Before-Completion: ARM clean build、direct `bm_nqueens`、以及用户指定子集 smoke 已完成
