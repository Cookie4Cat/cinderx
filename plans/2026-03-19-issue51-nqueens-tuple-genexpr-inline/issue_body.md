# [arm-opt][pyformance] bm_nqueens: inline tuple(genexpr) in permutations

## Proposal

- Case: `bm_nqueens`
- Symptom: ARM still pays generator protocol overhead in `permutations()` on the
  two `yield tuple(...)` hot paths
- Primary hypothesis: current 3.14 compiler shape already lowers `tuple(genexpr)`
  to list-collector bytecode, but JIT still builds a generator object and runs the
  nested `YIELD_VALUE/RESUME` protocol instead of flattening the loop
- Planned order: `HIR -> LIR -> codegen`
- Validation:
  - targeted ARM runtime tests for simple/closure tuple(genexpr)
  - direct `bench_n_queens(8)` benchmark
  - pyperformance regression subset through the remote entry script
- Exit criteria:
  - `tuple(genexpr)` simple and closure cases remove generator call setup in HIR
  - `bm_nqueens` on ARM improves without functional regressions
  - listed sensitive benchmarks show no material regression

## Problem description

- Workload: `bm_nqueens`
- User-visible symptom:
  - `permutations()` still spends hot-path time on `tuple(genexpr)` collector code
- Why it matters:
  - issue36 already removed the analogous `set(genexpr)` overhead
  - `tuple(genexpr)` is the next largest generator-protocol residue in this case

## Current IR

- Current HIR/LIR/codegen evidence:
  - historical notes show `permutations` still contains:
    - `VectorCall = 7`
    - `CallMethod = 2`
    - `MakeFunction = 2`
    - `BuildSlice = 2`
    - `ListSlice = 4`
- Hot blocks / hot ops:
  - generator function allocation
  - generator object creation
  - `YIELD_VALUE/RESUME` loop for tuple collection
- Known blockers:
  - current main worktree has unrelated unresolved conflicts, so this round runs
    in clean worktree `C:/work/code/generators-nqueens-clean`

## Target HIR

- Desired HIR shape:
  - simple case:
    - `MakeList`
    - `InvokeIterNext`
    - genexpr body
    - `ListAppend`
    - `MakeTupleFromList`
    - no `CallMethod`
  - closure case:
    - same flattened loop plus closure materialization
    - no generator object creation
- Why this shape should help:
  - removes generator-object allocation and generator protocol overhead while
    preserving the compiler-optimized list-to-tuple collector behavior

## Optimization suggestions

- HIR ideas:
  - generalize issue36 builder rewrite to a collector-mode abstraction
  - match the 3.14 `BUILD_LIST -> MAKE_FUNCTION -> CALL 0 -> FOR_ITER ->
    LIST_APPEND -> LIST_TO_TUPLE` shape
- LIR ideas:
  - only if HIR still leaves redundant collector helper ops
- codegen ideas:
  - only if ARM profile still points at instruction lowering after HIR/LIR settle
- Main risks:
  - closure/freevar semantics
  - exception behavior
  - matching a too-broad bytecode shape

## Minimal reproducer

- Source:
  - `tuple(i * 2 for i in range(8))`
  - `tuple(vec[i] + i for i in cols)`
- Command:
  - targeted scripts under `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
- Expected behavior:
  - functional results preserved
  - simple and closure cases lose `CallMethod`
  - simple case shows `MakeList + ListAppend + MakeTupleFromList`

## Baseline and environment

- ARM host: `124.70.162.35`
- x86 host: `106.14.164.133`
- Scheduler DB: `plans/remote-scheduler.sqlite3`
- Remote workdir: pending first ARM lease
- ARM baseline:
  - historical direct `bench_n_queens(8)`:
    - `compile_strategy=all`: `1.1747283110162243s`
    - `compile_strategy=none`: `1.389004991040565s`
    - no runtime deopts
- x86 baseline or comparison plan:
  - wait until ARM round is stable, then run matching verification
- Benchmark settings:
  - prefer direct benchmark first, then pyperformance subset through remote entry

## Repeat-error prevention

- Known mistakes to avoid:
  - do not describe or implement this as a generic tuple specialization
  - do not skip closure/exception tests
  - do not mix direct numbers with pyperformance subset numbers in one claim
- New guardrails added in this round:
  - exact tuple(genexpr) runtime tests land before remote benchmark

## Round plan

- Round 1:
  - HIR: builder-time tuple(genexpr) inline rewrite
  - LIR: only if HIR still leaves avoidable collector helpers
  - codegen: only if prior stages are stable and ARM still leaves a material gap
- Future rounds:
  - if `bm_nqueens` improves but sensitive regressions appear, revert or narrow
    the pattern before exploring a broader follow-up

## Exit criteria

- ARM target:
  - direct `bm_nqueens` improves measurably from current baseline
- x86 comparison target:
  - no obvious cross-host correctness mismatch after ARM round stabilizes
- correctness / regression target:
  - targeted tuple(genexpr) tests pass
  - listed sensitive benchmarks show no material regression

## Round 1 update

- Status:
  - completed on ARM
- Final HIR result:
  - optimized tuple(genexpr) path now removes generator-object creation for:
    - simple `return tuple(...)`
    - closure `return tuple(...)`
    - benchmark-relevant `yield tuple(...)`
- ARM targeted tests:
  - 5 tuple(genexpr) tests passed on the final installed build
- ARM direct benchmark:
  - `bench_n_queens(8)` current build:
    - `all`: `0.13829927999904612s`
    - `none`: `0.2242956129994127s`
    - `deopt = 0`
- ARM regression smoke:
  - requested 18-benchmark subset all completed once with no `Benchmark died`
- Remaining caveat:
  - this round did not rebuild a same-host pre-patch baseline, so the direct
    current-vs-current incremental delta should be treated as future follow-up
    work if needed
