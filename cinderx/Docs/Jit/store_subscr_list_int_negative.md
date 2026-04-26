# STORE_SUBSCR_LIST_INT 优化实验记录

## 目标

这一轮把 `STORE_SUBSCR_LIST_INT` 当成 `CALL_PY_EXACT_ARGS` 之后的第二个 type-info coverage gap 来跑完整闭环。目标是验证：CPython 3.14 已经在 bytecode site 上证明了 `list[int] = value`，CinderX 是否可以消费这个信息，跳过 generic `PyObject_SetItem` dispatch。

结论先放前面：这条在当前 pinned baseline 上不建议继续作为可合入 patch。它证明了 gap 真实存在，HIR/LIR 机制也能打通，但 ARM microbench 是负收益，selected pyperformance 也有 `nqueens` 回退；另外 out-of-range exception message 和 baseline 不完全一致。

## CPython 3.14 证据

focused micro workload：

```python
def store_list(lst, index, value):
    lst[index] = value
    return lst
```

在服务器 `/opt/python-3.14/bin/python3.14` warm up 后，`dis.get_instructions(adaptive=True, show_caches=True)` 看到：

```text
RESUME_CHECK
LOAD_FAST_BORROW_LOAD_FAST_BORROW
LOAD_FAST_BORROW
STORE_SUBSCR_LIST_INT
LOAD_FAST_BORROW
RETURN_VALUE
```

这说明 CPython tier-1 已经观察到 container 是 exact list、index 是 exact int，并把普通 `STORE_SUBSCR` specialized 成 `STORE_SUBSCR_LIST_INT`。

## CinderX baseline gap

在 pinned `ff2105b8` baseline 中：

- `BytecodeInstruction::specializedOpcode()` 没有保留 `STORE_SUBSCR_LIST_INT`，intake 会把它 `unspecialize()`。
- `HIRBuilder::emitStoreSubscr()` 只消费 `STORE_SUBSCR_DICT`，会给 dict path 插 `GuardType<TDictExact>`。
- `simplifyStoreSubscr()` 只 special-case `TDictExact`，其他 container 都保持 generic `StoreSubscr`。

focused dump 里，baseline 即使 Python bytecode 已经是 `STORE_SUBSCR_LIST_INT`，JIT optimized HIR 仍然是：

```text
StoreSubscr v6 v7 v8
```

## 实验 patch

实验 patch 分两层：

第一层是 type-info intake + HIR simplify：

- 在 `specializedOpcode()` whitelist 保留 `STORE_SUBSCR_LIST_INT`。
- 在 `emitStoreSubscr()` 中对该 opcode 插入 `GuardType<ListExact>` 和 `GuardType<LongExact>`。
- 在 `simplifyStoreSubscr()` 中把 `StoreSubscr(list, long, value)` lower 成：

```text
UseType<ListExact>
UseType<LongExact>
IndexUnbox
IsNegativeAndErrOccurred
CheckSequenceBounds
LoadField<ob_item>
LoadArrayItem old_value
StoreArrayItem
```

第二层是 LIR enabler：

- 把 `StoreArrayItem` 从 `JITRT_Set*_InArray` helper call 改成直接 memory store：

```text
[%base + %idx * scale] = Move value
```

这个组合基本等价于官方后续 `54cb7a83` 和 `44e26d22` 的思路。

## HIR/LIR 证据

opt initial HIR：

```text
v0 = GuardType<ListExact> v0
v1 = GuardType<LongExact> v1
StoreSubscr v0 v1 v2
```

opt optimized HIR：

```text
v15:ListExact = GuardType<ListExact> v6
v16:LongExact = GuardType<LongExact> v7
v17:CInt64 = IndexUnbox<IndexError> v16
v19:CInt64 = CheckSequenceBounds v15 v17
v20:CPtr = LoadField<ob_item@24, CPtr, borrowed> v15
v21:Object = LoadArrayItem v20 v19 v15
StoreArrayItem v20 v19 v8 v21
```

opt LIR after direct-store lowering：

```text
# StoreArrayItem v20 v19 v8 v21
[%32:Object + %30:64bit * 8]:Object = Move %7:Object
```

机制上已经达到预期：baseline 是 generic `StoreSubscr`，opt 是 guarded list/int path + direct array store。

## Correctness 观察

正向 list store 和 negative index 都正确：

```text
positive [0, 1, 99, 3]
negative [0, 1, 2, 42]
fallback True [(1, 'value')]
```

但 out-of-range exception message 不同：

```text
baseline: IndexError: list assignment index out of range
opt:      IndexError: list index out of range
```

原因是实验 patch 复用了 `CheckSequenceBounds`，它更接近 list read 的 error path；list assignment 的 generic path 会给不同 message。这里 type 正确，但 message 不完全等价，所以不能直接当作无风险 correctness patch。

## ARM microbench

microbench 使用一个 compiled loop：

```python
def store_loop(n):
    values = [0] * 16
    total = 0
    for i in range(n):
        idx = i & 15
        values[idx] = i
        total += values[idx]
    return total
```

JIT gate：

```text
jit_enabled True
force_compile True
compiled True
STORE_SUBSCR_LIST_INT present
```

只做 HIR specialization、`StoreArrayItem` 仍然 helper call 时：

```text
base median: 124.86 ns/iter
opt  median: 143.61 ns/iter
```

加上 direct `StoreArrayItem` LIR lowering 后：

```text
base median: 125.10 ns/iter
opt  median: 141.53 ns/iter
```

direct store 生效了，但整体仍然慢。核心原因不是最后那一次 store，而是 hot loop 每轮新增了：

- `GuardType<ListExact>`
- `GuardType<LongExact>`
- `IndexUnbox`
- `CheckSequenceBounds`
- `LoadArrayItem old_value`
- refcount pass 插入的 old/new value incref/decref

这些成本没有被 `PyObject_SetItem` dispatch elimination 抵消。

## Selected pyperformance

非 `--fast` 跑了：

```text
fannkuch,nqueens,deltablue,raytrace,nbody,float
```

compare 结果：

```text
deltablue: 17.3 ms -> 17.4 ms, not significant
fannkuch:  915 ms  -> 916 ms,  not significant
float:     430 ms  -> 428 ms,  not significant
nbody:     244 ms  -> 238 ms,  1.02x faster, significant
nqueens:   300 ms  -> 308 ms,  1.03x slower, significant
raytrace:  1.79 s  -> 1.78 s,  not significant
```

`nbody` 改善大概率不是这条 store path 的直接收益，因为它不是 list store-heavy workload；`nqueens` 回退更值得警惕。`fannkuch` 没复现官方 commit message 里的明显收益，可能和 pinned commit、JIT threshold、selected workload shape、或者官方后续其他 simplification 叠加有关。

## Keep / Revert Decision

本轮决定：不保留这条 patch 作为推荐优化。

原因：

- focused microbench 稳定负收益。
- selected pyperformance 有显著 `nqueens` 回退。
- out-of-range exception message 不完全一致。
- 它需要更窄的触发条件，不能只因为 CPython bytecode specialized 就直接把 generic store 改成 guarded HIR fast path。

## 后续更值得试的方向

- 针对 `STORE_SUBSCR_LIST_INT` 做更窄 fast path：只在 index 已经是 known compact/non-negative int 时触发，避免每轮 `IndexUnbox` helper。
- 新增 assignment-specific bounds check helper，保持 `list assignment index out of range` message。
- 先做动态 execution-weighted sampling，确认真正 hot 的 store site，而不是只看 code-object/site count。
- 把下一轮 P0 转向 `FOR_ITER_LIST/TUPLE/RANGE` 或 call-family，因为这些在 selected workload 中更接近 steady-state hot loop。
