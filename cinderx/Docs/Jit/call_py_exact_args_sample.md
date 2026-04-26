# CALL_PY_EXACT_ARGS 工程化优化样例

## 目标

这轮只做一个窄样例：把 CPython 3.14 已经通过 inline cache 证明过的 `CALL_PY_EXACT_ARGS`，接入 CinderX JIT 的 type-info intake，让 HIR 能知道 callable 是 exact `PyFunction`，进而复用已有的 `CallMethod -> VectorCall` 和 LIR direct `_PyObject_Vectorcall` lowering。

这不是完整的 Python-call inlining，也不处理 `CALL_PY_GENERAL`、bound method、builtin、kwargs。目标是建立一条可复现的证据链。

## CPython 3.14 证据

`CALL` family 的 cache format 是：

- `counter`
- `func_version`

在 `cinderx/Interpreter/3.14/Includes/generated_cases.c.h` 中，`CALL_PY_EXACT_ARGS` 会：

- 检查 callable 是 `PyFunction`。
- 从 `this_instr[2].cache` 读取 `func_version`。
- 校验 `func->func_version == func_version`。
- 校验 `code->co_argcount == oparg + has_self`。
- 直接 push Python frame。

新增脚本 `cinderx/TestScripts/jit_call_py_exact_args_audit.py` 用一个稳定 micro workload warm up CPython bytecode，然后通过 `dis.get_instructions(adaptive=True, show_caches=True)` 验证实际出现 `CALL_PY_EXACT_ARGS`。

在 ARM 服务器 `/opt/python-3.14/bin/python3.14` 上的 smoke 结果：

```text
Python: 3.14.3+
CALL_PY_EXACT_ARGS: 1

caller:
   36 LOAD_GLOBAL_MODULE               callee + NULL
   46 LOAD_FAST_BORROW_LOAD_FAST_BORROW i, i
   48 LOAD_SMALL_INT
   50 BINARY_OP_ADD_INT                +
   62 CALL_PY_EXACT_ARGS
```

之前 type-info coverage audit 的 selected pyperformance 采样里，`CALL_PY_EXACT_ARGS` 是 call family 的 P0 gap：`sites=462`，`weighted=5780759`。出现 workload 包括 `unpack_sequence`、`go`、`richards`、`richards_super`、`deltablue`、`raytrace`、`generators`、`pickle_pure_python`、`unpickle_pure_python`、`regex_compile`、`spectral_norm`、`scimark`、`nqueens`、`float`。

## CinderX baseline gap

baseline 中 `BytecodeInstruction::specializedOpcode()` 没有保留 `CALL_PY_EXACT_ARGS`，它会被 `unspecialize()` 成普通 `CALL`。

`HIRBuilder::emitAnyCall()` 也只看 `bc_instr.opcode()`，所以 call-family specialization 在 intake 阶段丢失。HIR 只生成 generic `CallMethod`，后续能不能变成 `VectorCall` 取决于已有类型信息，不能消费 CPython 3.14 inline cache 已经采到的 callable shape。

## 当前实现

这版 patch 做四件事：

- 在 `BytecodeInstruction::specializedOpcode()` 白名单中保留 `CALL_PY_EXACT_ARGS`。
- 在 `HIRBuilder::emitAnyCall()` 中，对普通 `CALL` 且无 kwargs/kwnames 的 `CALL_PY_EXACT_ARGS`，在生成 `CallMethod` 前对 callable operand 插入 `GuardType<TFunc>`，并给 call 标记 `CallFlags::PyFunc`。
- 在 `GuardTypeRemoval` 中保留 feeding `VectorCall<..., pyfunc>` 的 function guard，因为这个 guard 不是普通 operand constraint，而是后端选择 direct Python-function vectorcall path 的证据。
- 在 LIR lowering 中，当 `VectorCall` 带 `PyFunc` flag 时使用 direct `_PyObject_Vectorcall`，避开 `JITRT_Vectorcall`。

这个 guard 的收益路径是：

1. `CALL_PY_EXACT_ARGS` 说明 CPython interpreter 已经在同一 bytecode site 观察到 exact Python function call。
2. HIR guard 把 callable register refinement 成 `TFunc`，`PyFunc` flag 让这个 guard 不会被后续 guard-removal 删除。
3. 现有 simplify 在 `self` 是 `Nullptr` 时把 `CallMethod` rewrite 成 `VectorCall<..., pyfunc>`。
4. LIR lowering 看到 `func()->type() <= TFunc` 或 `CallFlags::PyFunc`，使用 direct `_PyObject_Vectorcall`，避开 `JITRT_Vectorcall` 的额外 helper path。

一个关键教训：只插 `GuardType<TFunc>` 不够。普通 `VectorCall` 的 operand type constraint 仍是 object-level，guard-removal 会认为这个 guard 对 correctness 没必要并删除它，导致 LIR 仍走 `JITRT_Vectorcall`。所以这条优化需要一个显式的 “this call came from `CALL_PY_EXACT_ARGS` and requires a PyFunction guard for codegen” 标记。

## HIR/LIR 证据

用 `caller(f, a, b): return f(a, b)` 做 focused dump，因为 global callee 形状 baseline 已经能通过 `LoadGlobalCached + GuardIs` 推出 exact function，不能体现这条优化。

baseline optimized HIR：

```text
v19:Object = VectorCall<2> v8 v9 v10
```

baseline LIR：

```text
VectorCall 0xffff...:64bit, 0(0x0):64bit, ...
```

这里的 call target 是 `JITRT_Vectorcall`。

opt optimized HIR：

```text
v19:Func = GuardType<Func> v9
v21:Object = VectorCall<2, pyfunc> v19 v10 v11
```

opt LIR：

```text
Guard ... v9, [PyFunction_Type], ...
VectorCall 4774752(0x48db60):64bit, 0(0x0):64bit, ...
```

这里的 call target 是 `_PyObject_Vectorcall`，也就是预期的 shorter helper path。

## 为什么暂不直接消费 func_version

`func_version` 是高价值信息，但这版没有生成 runtime `func_version` guard。原因是当前 HIR 已有的 deopt guard 更适合 object identity/type guard；如果要严谨比较 `PyFunctionObject::func_version` 这种 C integer field，需要新增或复用一条 integer guard/deopt 形状，并明确 frame state 和 refcount 行为。

这里先保持 conservative：

- `GuardType<TFunc>` 失败时 deopt，回到 interpreter/generic semantics。
- guard 成功后仍调用 `_PyObject_Vectorcall`，不会跳过 Python call 语义。
- `func_version` 作为下一阶段候选：如果我们要 inline callee frame、skip argcount/defaults checks，才必须把它变成 runtime guard。

## 测试覆盖

新增 Python JIT correctness tests：

- warm up 后先用 `dis.get_instructions(adaptive=True, show_caches=True)` 断言 caller bytecode 里实际出现 `CALL_PY_EXACT_ARGS`。
- 再 `force_compile()` caller，验证 exact positional Python function call 正常返回。
- 把 callable argument 换成 callable object，验证 guard/deopt/fallback 不改变语义。

这组测试覆盖的是 correctness 和 specialization evidence。HIR golden test 仍建议作为下一步补充：期望形状是 `CALL_PY_EXACT_ARGS -> GuardType<Func> -> CallMethod`，再由 simplify 变成 `VectorCall`。

## 远端验证状态

服务器 `/opt/python-3.14/bin/python3.14` 是：

```text
3.14.3+ (heads/3.14:1749b3c, Mar 15 2026, 02:57:55)
```

当前 `meta/main` 已经导入了 CPython 3.14.4，生成代码会引用服务器头文件里没有的 `_Py_LoadAttr_StackRefSteal`。因此本轮把 CinderX pin 到官方 `ff2105b8`：

```text
ff2105b8 Sync pre-release CPython main branch from GitHub (2026-03-15)
```

这个 pin 和服务器 CPython 3.14.3+ 匹配；远端目录是：

```text
/root/work/cinderx-call-py-exact-args-3143-20260426/
```

已验证：

- `base-src`: official `ff2105b8`，wheel build 成功。
- `opt-src`: `ff2105b8 + CALL_PY_EXACT_ARGS` patch，wheel build 成功。
- `jit-smoke-base.log`: `jit_enabled True`，`force_compile True`，`is_jit_compiled True`。
- `jit-smoke-opt.log`: `jit_enabled True`，`force_compile True`，`is_jit_compiled True`。
- `call-py-exact-args-smoke-opt.txt`: warmup 后确认出现 `CALL_PY_EXACT_ARGS`。

### Dynamic opcode sampling

用 selected pyperformance workload 做 JIT 进程内 atexit sampler，扫描 GC 中仍存活的 function code object，确认真实 benchmark 进程里 `CALL_PY_EXACT_ARGS` 并不是零：

```text
CALL: 5630181
CALL_KW: 332105
CALL_NON_PY_GENERAL: 99622
CALL_PY_EXACT_ARGS: 39486
CALL_PY_GENERAL: 11128
CALL_BOUND_METHOD_EXACT_ARGS: 7912
```

注意这不是 execution count，而是跨 pyperformance 子进程采集到的 specialized opcode site/sample count；它的意义是证明该 family 在真实 workload 中存在，不只存在于 micro。

### Microbench

ARM 上 focused microbench：

```text
base median: 732.87 ns/call
opt  median: 717.25 ns/call
delta: about 2.1% faster
```

这个 microbench 先在未导入 CinderX 前 warm up 出 `CALL_PY_EXACT_ARGS`，再导入 CinderX 并 `force_compile(caller)`，用于隔离验证 LIR helper path 的收益。

### Selected pyperformance

非 `--fast` 跑了：

```text
richards,deltablue,raytrace,nbody,float,regex_compile
```

结果整体无显著变化：

```text
deltablue:      17.4 ms -> 17.3 ms, not significant
float:          442 ms  -> 430 ms,  not significant
nbody:          244 ms  -> 244 ms,  not significant
raytrace:       1.85 s  -> 1.79 s,  not significant
regex_compile:  418 ms  -> 417 ms,  not significant
richards:       152 ms  -> 152 ms,  not significant
```

结论：这条 patch 是一个有效的工程化样例和 micro-positive 优化，但它还不是 strong macro win。主要原因是 selected pyperformance 里很多 `CALL_PY_EXACT_ARGS` site 来自 import/setup/stdlib path，未必落在 benchmark steady-state 热循环；另外 global callee case baseline 已经能通过 `LoadGlobalCached + GuardIs` 获得 `TFunc`。

## 后续实验方向

- 给 `PyFunctionObject::func_version` 增加 focused HIR guard，比较 direct C field 和 cached immediate。
- 在 exact args + func version valid 时，尝试直接构造 callee frame，接近 CPython `CALL_PY_EXACT_ARGS` 的 tier-1 fast path。
- 将相同 audit 方法扩展到 `CALL_PY_GENERAL` 和 `CALL_BOUND_METHOD_EXACT_ARGS`，但需要单独处理 defaults、bound self、kwargs。
