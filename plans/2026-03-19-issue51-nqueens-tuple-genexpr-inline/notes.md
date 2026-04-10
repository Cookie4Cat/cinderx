# Notes: Issue 51 tuple(genexpr) inline for bm_nqueens

## Historical context
- Issue #36 / commit `c3ac4a6f` 已实现 `set(genexpr)` inline lowering。
- 仓库旧记录显示 `bm_nqueens` 当前稳定基线约为:
  - direct `bench_n_queens(8)` / `compile_strategy=all`: `1.1747283110162243s`
  - `compile_strategy=none`: `1.389004991040565s`
  - no runtime deopts
- 旧 HIR split 结论:
  - `n_queens` 自身已不是主热点
  - `permutations` 仍有:
    - `VectorCall = 7`
    - `CallMethod = 2`
    - `MakeFunction = 2`
    - `BuildSlice = 2`
    - `ListSlice = 4`

## Real current tuple(genexpr) shape on 3.14
- 不是最原始的:
  - `LOAD_GLOBAL tuple`
  - `MAKE_FUNCTION`
  - `CALL 0`
  - `CALL 1`
- 而是更接近:
  - `BUILD_LIST`
  - `MAKE_FUNCTION`
  - `CALL 0` 生成 gen object
  - `FOR_ITER`
  - `LIST_APPEND`
  - `LIST_TO_TUPLE`
- 因而 builder 重写点应当瞄准:
  - `CALL 0` 后的 nested genexpr loop
  - 最终 collector 从 list 收束到 tuple

## Candidate implementation
- Generalize the current set inline path:
  - new collector mode enum:
    - `Set`
    - `ListToTuple`
  - `YIELD_VALUE`:
    - `Set` -> `SetSetItem`
    - `ListToTuple` -> `ListAppend`
  - inline exit finalization:
    - `Set` -> no-op
    - `ListToTuple` -> `MakeTupleFromList`
- Pattern match options:
  - keep current issue36 entry point:
    - intercept inner `CALL 0`
    - peek following bytecodes
  - match tuple path only when:
    - active stack shape matches `BUILD_LIST + MAKE_FUNCTION + iterable`
    - downstream bytecode sequence is compiler-optimized list collector form
    - builtin consumer semantics are preserved
- `MakeFunctionConstFold`:
  - likely reusable as-is once the outer `MakeFunction` loses all runtime users
  - verify direct-use graph after builder rewrite before touching the pass

## TDD checklist
- Simple case:
  - `tuple(i * 2 for i in range(8))`
  - expect no `CallMethod`
  - expect `MakeList`, `InvokeIterNext`, `ListAppend`, `MakeTupleFromList`
- Closure case:
  - `tuple(vec[i] + i for i in cols)`
  - expect no `CallMethod`
  - preserve closure/freevar behavior
- Exception cases:
  - divide by zero in genexpr body
  - closure subscript `IndexError`

## Remote validation plan
- Use shared scheduler before ARM remote compile / verify / benchmark.
- Use only `scripts/arm/remote_update_build_test.sh`.
- Inject direct benchmark through `POST_PYPERF_CMD`.
- Inject targeted tests through `EXTRA_TEST_CMD`.
- Regression subset should include at least:
  - `generators,coroutines,comprehensions,richards,richards_super,float,go`
  - `deltablue,raytrace,nqueens,nbody,unpack_sequence,fannkuch`
  - `coverage,scimark,spectral_norm,chaos,logging`

## Open questions
- Whether the tuple path is best matched from bytecode or from early HIR.
- Whether closure cases still leave `MakeFunction` alive after rewrite.
- Whether direct `bm_nqueens` win is large enough before paying for broader subset validation.

## Resolved in round 1
- The builder matcher must treat `FOR_ITER`'s false target as `POP_ITER`, not
  as the preceding `END_FOR`.
- The optimized tuple collector has two valid continuations:
  - immediate `RETURN_VALUE`
  - `JUMP_FORWARD` into a later consumer such as outer `YIELD_VALUE`
- The benchmark-relevant `yield tuple(pool[i] for i in indices[:r])` shape is
  therefore not a separate optimization path; it is the same collector rewrite
  plus a non-return continuation.
