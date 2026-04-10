# Mistake Ledger: Issue 51 tuple(genexpr) inline for bm_nqueens

## Known history entering this round

### 2026-03-19 - Do not mis-model the 3.14 tuple(genexpr) shape
- Symptom:
  - older mental model assumes outer `tuple(genexpr)` still goes through a raw
    builtin `tuple` call on the hot path
- Why it matters:
  - implementation point would be wrong, and we would optimize the wrong layer
- Prevention rule:
  - first write down the exact current bytecode/HIR shape before editing

### 2026-03-19 - Do not broaden the match beyond exact tuple(genexpr) lowering
- Symptom:
  - previous broad optimizations in unrelated work caused cross-benchmark
    regressions because they matched too much
- Why it matters:
  - this round touches a hot generic construct with closure/exception edges
- Prevention rule:
  - require targeted simple + closure + exception tests before remote perf claims

### 2026-03-19 - Do not blend direct and pyperformance numbers
- Symptom:
  - direct microbenchmarks and pyperformance subset runs answer different
    questions
- Why it matters:
  - mixing them obscures whether the gain is real and whether regressions exist
- Prevention rule:
  - findings and issue replies must label each number as direct or pyperformance

### 2026-03-20 - For optimized tuple(genexpr), `FOR_ITER` false-target lands on `POP_ITER`
- Symptom:
  - first tuple(genexpr) matcher assumed the cleanup target started at `END_FOR`
- Why it mattered:
  - the builder never matched the optimized path, so the rewrite silently did
    nothing while tests kept seeing `CallMethod`
- Prevention rule:
  - when matching optimized tuple/list collector loops, inspect the actual
    `getJumpTarget()` behavior rather than assuming the textual disassembly
    label starts at `END_FOR`

### 2026-03-20 - `yield tuple(...)` is a continuation shape, not a separate collector
- Symptom:
  - the first tuple matcher only handled the direct-return mental model
- Why it mattered:
  - `bm_nqueens` uses `yield tuple(...)`, so the hot real-world case would still
    have been missed even if the simpler direct-return case worked
- Prevention rule:
  - any tuple(genexpr) optimization must validate both:
    - `return tuple(...)`
    - `yield tuple(...)`
