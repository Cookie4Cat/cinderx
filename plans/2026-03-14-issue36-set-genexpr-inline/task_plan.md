# Task Plan: Issue 36 set(genexpr) inline lowering

## Goal
Eliminate generator-object creation and yield/resume overhead for `set(<genexpr>)` by lowering the pattern to set-comprehension-style HIR during JIT HIR building.

## Workflow
- Brainstorming: compare current `set(genexpr)` and set-comprehension bytecode/HIR.
- Write plan: keep concrete findings and validation notes in this directory.
- TDD: add at least one targeted regression around final HIR shape for `set(genexpr)`.
- Verification before completion: validate on remote ARM environment and record findings.

## Constraints
- Use `124.70.162.35` for meaningful runtime validation.
- Keep scope narrow enough to land safely.
- Preserve semantics for shadowed `set` names and captured freevars.

## Current Findings
- Current final HIR for `set(i * 2 for i in range(8))` still contains:
  - `MakeFunction`
  - `CallMethod`
  - outer `VectorCall(set, gen_obj)`
- Current final HIR for `{i * 2 for i in range(8)}` is already flat:
  - `MakeSet`
  - `InvokeIterNext`
  - `SetSetItem`
- `bm_nqueens` uses:
  - `set(vec[i] + i for i in cols)`
  - `set(vec[i] - i for i in cols)`
  so closure-capturing genexpr support matters.
- The Python compiler in `cinderx/PythonLib/cinderx/compiler/pycodegen.py` already contains an AST/codegen optimization for `set/list/tuple(<genexpr>)`, but normal runtime code objects are still produced by CPython and reach the JIT in unoptimized form.

## Planned Scope
- First implementation only targets builtin `set(<genexpr>)`.
- Lowering point:
  - builder-time interception of the inner `CALL 0` that creates the generator object
  - only when the next bytecode is the outer `CALL 1` to builtin `set`
- Reuse nested genexpr bytecode translation, but with custom collector mode:
  - ignore generator protocol ops (`RETURN_GENERATOR`, `RESUME`)
  - map `YIELD_VALUE` to `SetSetItem`
  - materialize closure freevars from the genexpr function's closure tuple

## Status
- [x] Capture current bytecode/HIR shape
- [x] Identify safe implementation point
- [~] Implement builder-time `set(genexpr)` lowering
- [x] Add regression coverage
- [x] Verify remotely and update findings

## Current Result
- The builder-time nested-genexpr lowering prototype is now stable enough to run remotely.
- Implemented scope:
  - builtin `set(<genexpr>)`
  - handles closure-capturing genexprs such as the `bm_nqueens` shape
  - rewrites the inner generator call into a flat `MakeSet + InvokeIterNext + SetSetItem` loop
- Added a second-stage fold for no-closure `<genexpr>` helpers:
  - `MakeFunctionConstFold`
  - replaces dead `<genexpr>` `MakeFunction` with a constant function object
  - removes the remaining simple-case function allocation
- Remote validation:
  - new tests passed:
    - `ArmRuntimeTests.test_set_genexpr_eliminates_generator_call`
    - `ArmRuntimeTests.test_set_genexpr_with_closure_eliminates_generator_call`
    - `ArmRuntimeTests.test_set_genexpr_preserves_exception_behavior`
    - `ArmRuntimeTests.test_set_genexpr_with_closure_preserves_exception_behavior`
  - existing regression re-run:
    - `ArmRuntimeTests.test_list_annotation_enables_exact_slice_and_item_specialization`
    - result: `OK`
- Current limitation:
  - closure-capturing genexprs still keep `MakeFunction`
  - so the remaining allocation gap is now concentrated in closure cases
  - simple no-closure `set(genexpr)` no longer allocates a function object on the hot path

## Measured Impact
- apples-to-apples remote comparison against a clean base worktree built from `origin/bench-cur-7c361dce`
- microbenchmark:
  - current `set(genexpr)`: `0.1674s`
  - base `set(genexpr)`: `1.0066s`
  - speedup: about `6.01x`
- `bm_nqueens`-style direct function benchmark:
  - current: `1.3243s`
  - base: `1.5738s`
  - speedup: about `15.9%`
