# 3c88c653: Inline Py_IncRef/Py_DecRef for free-threading

## 元信息

- Commit: `3c88c653a9b07dc64b250ca3f84545c3386c8301`
- Date: 2026-04-16
- Author: Jacob Bower
- Reviewer: Alex Malyshev
- Layer: LIR generator / refcount / free-threading CPython
- Changed files:
  - `cinderx/Jit/lir/generator.cpp`
  - `cinderx/Jit/lir/generator.h`

## Commit Message 要点

free-threading CPython 中，`Py_IncRef` / `Py_DecRef` 通常使用昂贵 atomic read-modify-write。JIT 已经持有 `tstate`，可以检查当前线程是否拥有对象。如果 `ob_tid == tstate->thread_id`，common case 可以用 cheap non-atomic local refcount operation；否则 fallback 到 CPython helper。

message 也很诚实：这最初是 AI 在实现 deferred reference counting 时做出来的，不一定是 scaling 的必要条件，但 reviewer 认为实现合理，而且本身是想要的优化。

## 优化形状

Incref fast path:

```text
load ob_ref_local
check immortal sentinel
check ob_tid == tstate->thread_id
fast non-atomic increment/store
else cold Py_IncRef fallback
```

Decref fast path:

```text
load ob_ref_local
check immortal sign bit
check ownership
fast non-atomic decrement
if zero -> _Py_MergeZeroLocalRefcount
else cold Py_DecRef fallback
```

slow paths 被放进 cold section，避免污染 hot path instruction cache。

## 代码实现 Review

改动集中在 `lir/generator.cpp/h`，说明这是 lowering/refcount emission 层的优化，不是 HIR pass。学习时重点看：

- Incref/Decref lowering 是否分 free-threading 和 non-free-threading；
- 如何访问 `ob_ref_local`、`ob_tid`、`tstate->thread_id`；
- immortal object 如何识别；
- cold block 如何创建和连接；
- zero local refcount merge 如何调用。

这个 commit 需要非常谨慎，因为 refcount correctness 错误通常不是立即 crash，而是 use-after-free、leak 或 data race。

## Correctness 风险

几个必须成立的条件：

- thread ownership check 必须准确；
- immortal sentinel 判断不能和正常 refcount 混淆；
- decrement 到 0 时必须走 merge/slow path；
- fallback helper 语义必须和 CPython 一致；
- cold path 不能破坏 frame state 或 register convention。

## 和 `d5fa88c3` 的关系

`d5fa88c3` 是“不生成不需要的 Decref”；`3c88c653` 是“必须生成时让 common case 更便宜”。二者是 refcount optimization 的两层：

```text
eliminate unnecessary refcount ops
  -> inline unavoidable refcount ops
  -> cold fallback for uncommon cases
```

## ARM64 启发

free-threading 下 atomic RMW 在 ARM64 上通常很贵，因为 memory ordering 和 cache-line ownership 成本明显。这个 commit 把常见 thread-owned object path 转成普通 load/add/store，是 ARM64 可能明显受益的 runtime protocol optimization。

不过它也可能增加 code size，因为 inline refcount sequence 比 helper call 更长。所以需要用 benchmark 判断 hot path 收益是否超过 I-cache 成本。

## 测试与验证建议

文档计划里不跑测试，但后续如果要验证，应包括：

- free-threading build；
- refcount stress tests；
- object ownership transfer cases；
- immortal objects；
- zero local refcount path；
- TSAN/ASAN；
- benchmark code size 和 runtime。

## 后续追问

- cold fallback 是否真的 cold？profiling 能否确认？
- ARM64 上 inline sequence 是否可以进一步减少 branch？
- helper call removal 带来的 code size 增长是否影响 fastmark？
- deferred RC 如果继续推进，这段 lowering 是否还适用？
