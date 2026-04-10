# deepcopy / issue #47 task plan

## Case

- Case: `deepcopy`
- Issue: `#47`
- Branch: `codex/deepcopy-issue47`
- Base: `origin/bench-cur-7c361dce` @ `7fe48dd9`
- Unified remote entrypoint: `scripts/push_to_arm.ps1` -> `/root/work/incoming/remote_update_build_test.sh`
- Shared scheduler DB: `C:/work/code/cinderx-deepcopy-issue47-20260318/plans/remote-scheduler.sqlite3`
- Shared scheduler tool: `C:/work/code/coroutines/cinderx/scripts/remote_scheduler.py`

## Brainstorming

- Symptom: JIT-compiled `copy.deepcopy` helpers that rely on `try/except KeyError` generate only the happy path and deopt with `UnhandledException` on the expected KeyError path.
- Expected hotspot: HIR builder / exception-edge modeling is likely dropping or never lowering exception handlers for regular `try/except`.
- Main hypothesis: the builder can emit bytecode instructions inside protected regions, but the resulting HIR blocks do not preserve a CFG edge from throwing instructions to the active exception handler block, so codegen falls back to `UnhandledException` deopt.
- HIR target: for a protected `BINARY_SUBSCR` inside `try/except KeyError`, the HIR should either:
  - keep the throw-capable instruction and attach an exception edge to a handler bb, or
  - lower a narrow dict-subscript / KeyError pattern into an explicit branch without exceptions.
- Biggest risk: fixing generic exception edges may be correctness-sensitive and broad; a pattern-only rewrite may help `deepcopy` but miss the more general `try/except` gap.

## Success criteria

- Reproduce the reported `UnhandledException` deopt on ARM using the unified remote entrypoint and capture current HIR evidence.
- Add a targeted regression test that fails before the fix and passes after it.
- Land the smallest safe HIR-stage fix first.
- Validate that `deepcopy` no longer linearly deopts on the expected KeyError path.
- Run the requested benchmark regression subset and show no material regression.
- Keep `findings.md`, issue draft, and mistake ledger updated after each meaningful stage.

## Stage order

1. `HIR`
2. `LIR`
3. `codegen`

Current expectation: stay in `HIR` until a concrete exception-edge or pattern-lowering fix is either validated or ruled out.

## Round 1 plan

- Phase 0 intake:
  - Create case files and findings scaffold.
  - Confirm scheduler path and unified remote entrypoint.
- Phase 1 proposal:
  - Write compact proposal and issue draft from the user report.
- Phase 2 baseline:
  - Build a minimal reproducer for `_keep_alive` / `_deepcopy_tuple`.
  - Add a regression test that asserts the hot KeyError path stays in JIT or at least avoids `UnhandledException` deopt.
  - Capture current ARM deopt/HIR evidence remotely.
- Phase 3 local proof:
  - Inspect HIR builder exception handling.
  - Implement the smallest HIR-only fix or guarded special-case lowering.
  - Run local targeted tests.
- Phase 4 remote ARM:
  - Compile and verify via the unified entrypoint under a scheduler lease.
  - Benchmark `deepcopy` and the requested regression subset.
- Phase 5 comparison / closure:
  - Defer x86 unless ARM is stable enough to compare or merge gating requires it.
  - Update issue, ledger, and findings with the decision.

## Current status

- `2026-03-18`: clean worktree created from latest `origin/bench-cur-7c361dce`.
- `2026-03-18`: standard SOP, Chinese checklist, and unified remote entrypoint confirmed.
- `2026-03-18`: case-local proposal, issue draft, notes, and mistake ledger created.
- `2026-03-18`: added targeted ARM regression `test_deepcopy_keyerror_helpers_avoid_unhandledexception_deopts`.
- `2026-03-18`: ARM lease `#1` (`compile`, stage `HIR-baseline-test`) captured the failing baseline through the unified entrypoint.
  - targeted result:
    - `_keep_alive`: `200` `UnhandledException/BinaryOp` deopts
    - `_deepcopy_tuple`: `200` `UnhandledException/BinaryOp` deopts
    - total correctness check: `19900`
- `2026-03-18`: static analysis plus 3.14 bytecode inspection narrowed the first implementation to a HIR-stage dict-miss rewrite:
  - `_keep_alive`: inline miss body
  - `_deepcopy_tuple`: branch to the post-except continuation
- `2026-03-18`: remote follow-up evidence changed the round status:
  - `_keep_alive` is now partially fixed on ARM:
    - HIR counts changed from the old `BinaryOp/LoadMethodCached/CallMethod` shape to a rewritten shape with `CallStatic`, `MakeList`, `GuardType`, and no `BinaryOp`
    - direct deopt probe result: `keep_alive_deopts=0`
  - combined probe confirms a real partial issue win:
    - baseline was `200/200`
    - current patch is `0/200`
    - `total=19900`
  - `_deepcopy_tuple` remains the only deterministic deopt source in the reproducer
  - the `CallStatic` miss sentinel needed a lifetime fix; using a raw leaked sentinel removed the process-exit segfault
- `2026-03-18`: `_deepcopy_tuple` was redesigned to use a helper-return miss path instead of branching into a future bytecode block.
  - combined ARM probe now shows:
    - `_keep_alive=0`
    - `_deepcopy_tuple=0`
    - `total=19900`
    - `elapsed=0.00032323300001735333`
  - compared with the previous partial state (`0/200`, `elapsed=0.0007303920001504594`), this round improved the combined probe by about `55.75%`.
- `2026-03-18`: lease `#3` released cleanly after capturing full `0/0` evidence.
- `2026-03-18`: broader ARM regression sweep completed against `origin/bench-cur-7c361dce` base.
  - broad 2-sample subset compare:
    - primary compare file: `artifacts/deepcopy/reg_compare.json`
    - only two >5% slowdowns in the broad pass:
      - `comprehensions` `+9.31%`
      - `logging_silent` `+51.94%`
  - focused 5-sample rerun for the suspicious cases:
    - compare file: `artifacts/deepcopy/reg_focus_compare.json`
    - `comprehensions` shrank to `+3.89%`
    - `logging_format` `+1.03%`
    - `logging_simple` `-2.59%`
    - `logging_silent` stayed at `+8.21%`, but the absolute delta is only about `0.08 us`
- `2026-03-18`: lease `#4` released cleanly after the regression sweep.
- `2026-03-18`: current status is “issue fixed, no material broad regression found, with one tiny residual `logging_silent` signal recorded”.
