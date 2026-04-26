# FOR_ITER_LIST / FOR_ITER_TUPLE 工程化优化样例

## 元信息

- 基线：`meta/main` pinned 到服务器 CPython 3.14.3 对应 commit `ff2105b8`
- 目标：消费 CPython 3.14 quickened opcode `FOR_ITER_LIST` / `FOR_ITER_TUPLE`
- 平台：ARM64 server `my-server`
- 结论：LIST/TUPLE microbench 有明确收益，selected pyperformance 无显著变化；`FOR_ITER_RANGE` 暂列 negative / follow-up

## 优化形状

CPython 3.14 interpreter 对 list/tuple iterator 已经有 specialized fast path：

- guard iterator exact type：`list_iterator` / `tuple_iterator`
- 读取 iterator 内部字段：`it_seq`、`it_index`
- bounds check 后直接从 backing array 取 item
- 更新 `it_index`
- 只在 exhausted / stale specialization / wrong iterator type 时回 generic iterator path

CinderX 原来在 JIT intake/HIR 层没有消费这个 specialized opcode，最终仍是：

```text
InvokeIterNext
CondBranchIterNotDone
```

这会回到 generic iterator protocol。新路径把 list/tuple 的 hot next-item 变成 raw field load + direct array load。

## 实现 review

关键实现点：

- `BytecodeInstruction::specializedOpcode()` 保留 `FOR_ITER_LIST` / `FOR_ITER_TUPLE`
- `HIRBuilder::emitForIter()` 接收 `CFG&`，用于创建 fast/slow/merge blocks
- 对 specialized opcode 先发 `CondBranchCheckType`
- type check 成功才读取 CPython internal iterator layout
- type check 失败、`it_seq == nullptr`、越界时全部回落到原 `InvokeIterNext`

最重要的 correctness lesson：

第一版用了 `GuardType` 保护 raw field load，但 `GuardTypeRemoval` 会删除“不被 operand constraint 需要”的 guard。最终 HIR 里 guard 消失，`re._compiler:_compile` 在 pyperformance import 阶段 segfault。GDB 看到 fast path 在 `Incref` 一个 bogus item pointer `0x1`。

修复后的形状改成 `CondBranchCheckType`：

```text
CondBranchCheckType<ObjectUser[list_iterator:Exact]> iter
  fast: LoadField<it_seq> / LoadField<it_index> / LoadArrayItem / StoreField<it_index>
  slow: InvokeIterNext
merge:
  CondBranchIterNotDone
```

这个形状不会被 guard removal 抹掉，而且 stale specialization 可以自然 fallback。

## 测试实现 review

新增 focused Python JIT tests：

- warmup 后确认 `dis.get_instructions(adaptive=True)` 能看到：
  - `FOR_ITER_LIST`
  - `FOR_ITER_TUPLE`
  - `FOR_ITER_RANGE`
- force compile 后验证 list/tuple/range 基础结果
- list-specialized function 传入 tuple/range，验证 stale specialization fallback correctness

`FOR_ITER_RANGE` 目前只作为“能观测到 opcode 且 JIT 仍能编译”的 intake/follow-up 测试，不把它声明成已优化。

## ARM64 证据

JIT gate：

- `import cinderx, cinderx.jit`
- `cinderx.jit.is_enabled() == True`
- smoke function `force_compile == True`
- benchmark 子进程 bootstrap log 每个 worker 都记录 JIT enabled/compiled

Focused HIR/LIR dump：

- base：list/tuple/range 都是 `InvokeIterNext`
- opt：list/tuple 出现 `LoadField<it_seq>`、`LoadField<it_index>`、`LoadArrayItem`、`StoreField<it_index>`
- opt：range 仍是 `InvokeIterNext`

Microbench median：

| workload | base | opt | 结论 |
|---|---:|---:|---|
| list iteration | 159.8 ms | 133.7 ms | ~16% faster |
| tuple iteration | 159.2 ms | 131.3 ms | ~17% faster |
| range iteration | 274.3 ms | ~272-278 ms | no stable improvement |

Selected pyperformance normal run：

- `deltablue`
- `fannkuch`
- `generators`
- `nqueens`
- `richards`
- `scimark_*`
- `spectral_norm`
- `unpack_sequence`

结果：全部 `Not significant`，没有稳定 macro win，也没有明显 regression。

## FOR_ITER_RANGE negative result

尝试过按 CPython interpreter shape 实现 range iterator fast path：

- guard exact `range_iterator`
- 读取 `_PyRangeIterObject.start/step/len`
- `len > 0` 时更新 `start/len`
- `PrimitiveBox(start)` 作为 next value

但 focused dump 仍显示 `loop_range` 走 generic `InvokeIterNext`，说明当前还有一个 intake/quickened opcode 读取层面的 gap：Python `dis` 能看到 `FOR_ITER_RANGE`，但 HIR builder 没有进入 range branch。

这条暂不保留为推荐 patch。下一步应该单独做：

- 在 JIT intake 层打印/断言 `FOR_ITER_RANGE` 的 numeric opcode
- 对比 `_Py_OPCODE(codeUnit)`、`dis(adaptive=True)`、`_CiOpcode_Deopt`
- 确认 `FOR_ITER_RANGE` 是否被 `uninstrument()` / `specializedOpcode()` / generated opcode table 抹平

## 可以举一反三的方法

- 对 raw CPython object layout 的 fast path，优先用 explicit `CondBranchCheckType + fallback`，不要依赖可能被 removal pass 删除的 `GuardType`
- 每个 specialized opcode 先做 “intake preserved -> HIR branch entered -> LIR shape changed -> micro improves -> macro no regression” 的证据链
- CPython quickened opcode 的 `dis` 证据不等于 CinderX intake 证据；两者之间必须有 HIR dump 验证
- micro win 不自动代表 pyperformance win；这类 loop-body 局部优化更可能在 synthetic 或 very tight loops 中体现

