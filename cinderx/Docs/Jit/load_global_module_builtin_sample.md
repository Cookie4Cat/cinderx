# LOAD_GLOBAL_MODULE / LOAD_GLOBAL_BUILTIN 优化样例

## 目标

这条样例聚焦 CPython 3.14 的 `LOAD_GLOBAL_MODULE` / `LOAD_GLOBAL_BUILTIN`。第一轮结论是：CinderX 不是完全没有 global fast path，当前 `emitLoadGlobal()` 已经通过 preloader + `LoadGlobalCached` 接入 global cache；真正可优化的点在 guard granularity。

## CPython 3.14 specialization 证据

典型 micro warm-up 后可以观察到：

- module global: `LOAD_GLOBAL_MODULE`
- builtin global: `LOAD_GLOBAL_BUILTIN`

`LOAD_GLOBAL_MODULE` 的高价值信息是 module dict version / index / 当前 value shape。CinderX 当前不用 CPython inline cache payload，而是用自己的 `GlobalCacheManager` 监听 globals / builtins dict key 更新。

## Baseline CinderX 形状

baseline HIR 对 module 和 builtin 都是：

```text
LoadGlobalCached<...; "name">
GuardIs<LOAD_GLOBAL: name>
```

这个形状对 stable global 很强，但对 deltablue 这类 “module global rebound 到同 exact heap type 新对象” 的模式不友好：global cache 已经能拿到新对象，`GuardIs` 却会因为 identity 改变触发 deopt。

## Patch 形状

只对非常窄的 `LOAD_GLOBAL_MODULE` 风格场景放宽 guard：

- value 不是 immortal object。
- value 的 type 是 heap type。
- 同 module 的 Python function 中存在对该 name 的 `STORE_GLOBAL`。
- 满足这些条件时，`LoadGlobalCached` 后使用 `GuardType(exact)`。
- 其他情况继续使用 `GuardIs`。

新的 HIR 形状：

```text
LoadGlobalCached<...; "planner">
GuardType<LOAD_GLOBAL_TYPE: planner, PlannerExact>
```

`LOAD_GLOBAL_BUILTIN` 暂不改：`len` / `range` / builtin function identity 对后续 call specialization 很重要，当前仍保持 `GuardIs`。

## Correctness 边界

- 同 exact type rebound：继续走 compiled path，语义保持。
- 不同 type rebound：`GuardType` deopt，回到解释器语义。
- stable module global：仍是 `GuardIs`，不降低 guard 强度。
- builtin global：仍是 `GuardIs`，不误放宽 builtin target identity。

## 测试覆盖

新增 Python JIT test：

- `ReboundGlobalGuardTests.test_rebound_heap_global_keeps_python_semantics`

新增 HIR tests：

- `ReboundGlobalUsesExactTypeGuard`
- `StableGlobalKeepsIdentityGuard`
- `BuiltinGlobalKeepsIdentityGuard`

## ARM64 验证计划

1. 用 CPython 3.14 dis smoke 确认 micro 产生 `LOAD_GLOBAL_MODULE` / `LOAD_GLOBAL_BUILTIN`。
2. dump baseline / patch HIR，确认 `planner` 从 `GuardIs` 变为 `GuardType`，`len` 仍是 `GuardIs`。
3. 跑 focused tests。
4. 跑 rebound-global microbench，重点看同 exact type rebound 后 deopt 是否减少。
5. 跑 selected pyperformance：`deltablue`、`richards`、`unpack_sequence`、`nbody`、`regex_compile`、`float`。

## ARM64 验证结果

远端目录：

- `/root/work/cinderx-load-global-20260426`
- base: `3c88c653`
- opt: base + 当前 patch
- Python: `/opt/python-3.14/bin/python3.14`
- GCC: `/opt/gcc-14.2/bin/gcc`

JIT gate：

- `jit.is_enabled() == True`
- `jit.force_compile(probe) == True`
- `jit.is_jit_compiled(probe) == True`

CPython 3.14 dis smoke：

```text
get_value_opcodes      ['RESUME_CHECK', 'LOAD_GLOBAL_MODULE', 'LOAD_ATTR_INSTANCE_VALUE', 'RETURN_VALUE']
get_builtin_len_opcodes ['RESUME_CHECK', 'LOAD_GLOBAL_BUILTIN', 'LOAD_FAST_BORROW', 'CALL_LEN', 'RETURN_VALUE']
```

HIR dump：

baseline `get_value`：

```text
LoadGlobalCached<0; "planner">
GuardIs<...> {
  Descr 'LOAD_GLOBAL: planner'
}
```

opt `get_value`：

```text
LoadGlobalCached<0; "planner">
GuardType<ObjectUser[Planner:Exact]> {
  Descr 'LOAD_GLOBAL_TYPE: planner'
}
```

opt `get_builtin_len` 保持 identity guard：

```text
LoadGlobalCached<0; "len">
GuardIs<...> {
  Descr 'LOAD_GLOBAL: len'
}
```

Microbench：

| case | base median | opt median | result |
| --- | ---: | ---: | --- |
| stable global | 87.32 ms | 86.92 ms | neutral |
| rebound same-type global | 211.39 ms | 139.95 ms | 1.51x faster |

Deopt stats：

- base rebound: `840000` 次 `GuardFailure`, description `LOAD_GLOBAL: planner`
- opt rebound: `0` 次 deopt

Selected pyperformance, normal mode：

| benchmark | result |
| --- | --- |
| `deltablue` | `16.3 ms +- 2.2 ms -> 15.4 ms +- 2.3 ms`, `1.06x faster`, significant |
| `float` | not significant |
| `nbody` | not significant |
| `regex_compile` | not significant |
| `richards` | not significant |
| `unpack_sequence` | not significant |

## 预期收益

这不是一个稳定 global 的 steady-state load 加速；它针对的是 “global cache value 已更新，但 identity guard 过强导致 deopt” 的场景。最可能命中的 benchmark 是 `deltablue` 一类会 rebound module-level planner / current state object 的 workload。
