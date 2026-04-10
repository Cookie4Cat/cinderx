# Notes: Issue 36

## Current bytecode shape

### `set(genexpr)`
Outer function:
- `LOAD_GLOBAL set + NULL`
- `LOAD_CONST <genexpr code>`
- `MAKE_FUNCTION`
- build iterable
- `GET_ITER`
- inner `CALL 0`
- outer `CALL 1`

Inner `<genexpr>` code:
- optional `COPY_FREE_VARS`
- `RETURN_GENERATOR`
- `POP_TOP`
- `RESUME 0`
- `LOAD_FAST .0`
- `FOR_ITER`
- body
- `YIELD_VALUE`
- `RESUME 5`
- `POP_TOP`
- `JUMP_BACKWARD`
- `RETURN_VALUE`

### set comprehension
- already flat in outer bytecode and HIR
- no `MAKE_FUNCTION`
- no generator object
- no `YIELD_VALUE` / `RESUME`

## Current final HIR

### `set(i * 2 for i in range(8))`
- `LoadGlobalCached("set")`
- `GuardIs(set)`
- `MakeFunction`
- `GetIter`
- `CallMethod` to create generator object
- `VectorCall(set, gen_obj)`

### `{i * 2 for i in range(8)}`
- `MakeSet`
- `GetIter`
- loop header with `InvokeIterNext`
- `SetSetItem`

## Closure case
For:

```python
def f(vec, cols):
    return set(vec[i] + i for i in cols)
```

Outer final HIR shows:
- `MakeCell vec`
- `MakeTuple<1> closure`
- `MakeFunction`
- `SetFunctionAttr<func_closure>`
- `GetIter(cols)`
- `CallMethod(genfunc, iter)`
- `VectorCall(set, gen_obj)`

Inner genexpr bytecode uses:
- `COPY_FREE_VARS 1`
- `LOAD_DEREF vec`

So any useful implementation needs closure-tuple support.

## Design direction
- Builder-time rewrite is preferable to a later HIR pass because:
  - current bytecode pattern is explicit and stable
  - we can skip emitting the expensive generator-object call chain
  - dead earlier builder emissions (`MakeFunction`, `SetFunctionAttr`) can be removed by DCE
- The best interception point is the inner `CALL 0`, because:
  - iterable is already available on the stack
  - genexpr function object is already available on the stack
  - the next bytecode reveals the outer consumer (`CALL 1` to `set`)

## Prototype attempt
- Implemented a first builder-time prototype:
  - pattern-match at inner `CALL 0`
  - recognize builtin `set` consumer plus `<genexpr>` code object
  - synthesize `MakeSet`
  - translate nested genexpr loop into an inner CFG
  - map `YIELD_VALUE` to `SetSetItem`
  - handle closure discovery through `SetFunctionAttr<func_closure>`
- The prototype now **does** hit the pattern:
  - debug output confirms the stack shape at the inner `CALL 0`
  - debug output confirms the nested `<genexpr>` code object is found

## Failure mode
- The current nested inline approach still segfaults during compilation.
- Failure evolution:
  1. first crash was due queuing a synthetic exit block not present in `block_map_`
  2. second crash was due use-after-free when pruning unreachable inner blocks
  3. current crash remains in `SSAify`, after the rewrite has already happened
- The current initial HIR after rewriting looks close to the desired shape:
  - `MakeSet`
  - inner `InvokeIterNext`
  - `BinaryOp<Multiply>`
  - `SetSetItem`
  - branch backedge
- So the remaining problem is no longer pattern recognition; it is CFG/FrameState correctness for the nested rewrite.

## Crash fixes
- Fixed synthetic-exit queueing by skipping blocks that are not in `block_map_` during nested genexpr translation.
- Fixed a use-after-free in the debugging cleanup path by no longer querying deleted inner blocks.
- Most importantly, fixed the parent `FrameState` lifetime issue by storing nested-inline parent frames in the outer `HIRBuilder` instead of pointing to a stack local copy.
- Expanded parent-nulling to all blocks reachable from the nested genexpr entry, including blocks created later during translation such as periodic-task blocks.

## Current final HIR
- Simple case `set(i * 2 for i in range(8))` now lowers to:
  - `MakeSet`
  - `InvokeIterNext`
  - `BinaryOp<Multiply>`
  - `SetSetItem`
  - no `CallMethod`
  - no outer `VectorCall(set, gen_obj)`
- Closure case `set(vec[i] + i for i in cols)` now lowers to:
  - `MakeSet`
  - `InvokeIterNext`
  - `LoadCellItem/CheckFreevar`
  - `BinaryOp<Subscript>`
  - `BinaryOp<Add>`
  - `SetSetItem`
  - no `CallMethod`

## Remaining limitation
- The rewrite currently triggers at the inner `CALL 0`.
- Because of that, `MakeFunction` still remains in the outer function's HIR and runtime path.
- So this is not yet fully equivalent to a true set-comprehension lowering.
- The next step, if needed, is to move the optimization earlier so `MAKE_FUNCTION` itself is avoided.

## Second-stage improvement
- Added `MakeFunctionConstFold` after refcount insertion.
- It targets:
  - `<genexpr>`
  - no freevars
  - null qualname
  - no remaining direct runtime users other than `Decref` / `UseType`
- For that narrow case, it materializes a constant `PyFunctionObject` at compile time and rewrites frame-state/deopt references to the constant register.
- Result:
  - simple `set(genexpr)` no longer has `MakeFunction` in final HIR
  - closure case still keeps `MakeFunction`

## Closure follow-up attempt
- Tried an additional closure-only tweak:
  - bypass tuple-item indirection for captured cells during inline setup
  - goal was to reduce closure-case loop overhead further
- Remote result on `n_queens(8)` was not reliably better, so that change was not kept.

## Remote runtime validation
- Host: `124.70.162.35`
- New runtime regressions:
  - `ArmRuntimeTests.test_set_genexpr_eliminates_generator_call`
  - `ArmRuntimeTests.test_set_genexpr_with_closure_eliminates_generator_call`
  - `ArmRuntimeTests.test_set_genexpr_preserves_exception_behavior`
  - `ArmRuntimeTests.test_set_genexpr_with_closure_preserves_exception_behavior`
  - result: both `OK`
- Existing regression re-run:
  - `ArmRuntimeTests.test_list_annotation_enables_exact_slice_and_item_specialization`
  - result: `OK`

## Microbenchmark
- Remote JITed microbenchmark after second-stage fold:
  - `with_genexpr(): set(i * 2 for i in range(8))`
  - `with_setcomp(): {i * 2 for i in range(8)}`
- Current median:
  - `with_genexpr`: `0.1674330570967868s`
  - `with_setcomp`: `0.16612694202922285s`
- Interpretation:
  - simple `set(genexpr)` is now effectively at parity with setcomp
  - the remaining issue is specifically closure-bearing cases

## Base-vs-current comparison
- Built a clean base worktree from `origin/bench-cur-7c361dce` on the same host and toolchain.
- Same comparison script on both builds:
  - current `set(genexpr)`: `0.1674330570967868s`
  - base `set(genexpr)`: `1.0065587260760367s`
  - speedup: about `6.01x`
  - current setcomp: `0.16612694202922285s`
  - base setcomp: `0.2993291780585423s`
- Direct `n_queens(8)` benchmark from the pyperformance algorithm:
  - current: `1.3242973680607975s`
  - base: `1.5738149019889534s`
  - speedup: about `15.9%`

## Risk
- Need to preserve runtime semantics for shadowed builtin names.
- Need to avoid breaking captured-freevar genexprs.
- Need to ensure the generated HIR is still exception-safe and refcount-safe.
