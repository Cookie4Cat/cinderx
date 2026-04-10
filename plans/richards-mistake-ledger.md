# Richards Mistake Ledger

## 2026-03-15 - Do not treat HIR shrinkage as an end-to-end win

- Symptom: Several richards follow-up HIR ideas made the IR look cleaner or smaller but did not improve ARM runtime.
- Root cause: Richards is sensitive to helper, guard, and backend density; a “better looking” HIR does not guarantee a lower end-to-end cost.
- Detection gap: Earlier loops sometimes advanced from IR aesthetics before same-host benchmark confirmation.
- Prevention rule: Every new HIR idea needs an explicit ARM benchmark win before it is considered progress.
- Validation added: Same-host ARM direct richards probe must be recorded for any new HIR attempt, then issue + notes must be updated before proceeding.

## 2026-03-15 - Do not retry store-side HIR specialization blindly

- Symptom: The `STORE_ATTR_INSTANCE_VALUE` overwrite fast path regressed badly.
- Root cause: Constructor and first-write paths were not equivalent to overwrite-only paths, and the guard sequence cost outweighed the intended fast path.
- Detection gap: The prototype was narrower than the real richards write shapes.
- Prevention rule: Do not retry store-side HIR specialization unless the reproducer proves the target site is a stable overwrite-only shape and the new guard sequence is explicitly justified.
- Validation added: Any future store-side hypothesis must include site classification plus a correctness guard in `test_arm_runtime.py` or an equivalent focused reproducer.

## 2026-03-15 - Do not infer wins from `spill_stack_size` alone

- Symptom: Backend reasoning over-focused on `spill_stack_size` as if it were pure regalloc spill bytes.
- Root cause: The metric also includes lightweight-frame and frame-header related space.
- Detection gap: The frame-layout meaning was not checked in codegen/regalloc sources early enough.
- Prevention rule: Treat `spill_stack_size` as a mixed pressure signal, not a direct spill counter.
- Validation added: Any future backend claim about spill pressure must include source-backed interpretation and at least one corroborating signal beyond `spill_stack_size`.

## 2026-03-15 - No backend retry without a changed hypothesis

- Symptom: AArch64 deopt stage-1 compaction and always-shared helper-call stubs both consumed remote validation time and lost end-to-end.
- Root cause: Both ideas optimized visible code-shape symptoms without proving that the symptom was the actual bottleneck.
- Detection gap: The remote step answered the question only after full compile and measurement; the local preflight evidence was too weak.
- Prevention rule: Do not rerun backend/codegen experiments unless the new patch changes the causal story, not just the syntax of a known-losing direction.
- Validation added: Before any backend remote attempt, record the exact IR/LIR/codegen motif that is supposed to change and why the previous losing attempt does not already cover it.

## 2026-03-15 - Methodology must stay matched across ARM and x86

- Symptom: Richands history contains both direct `Richards.run(3)` probes and pyperformance runs, which are useful for different purposes but easy to mix.
- Root cause: Fast direct probes are convenient during iteration, while final case claims require matched methodology across hosts.
- Detection gap: Historical notes span multiple runners and noise profiles.
- Prevention rule: Use direct probes only as stage-local signals; use matched methodology for any final ARM-vs-x86 statement.
- Validation added: Every issue update must state whether a number is a direct probe, a pyperformance run, or an IR-only verification artifact.

## 2026-03-15 - No remote action without scheduler + issue trail

- Symptom: Historical experiments used many workdirs and package drops, making it harder to reconstruct ownership and phase boundaries.
- Root cause: Coordination metadata was spread across ad hoc artifacts instead of a single case-local closed loop.
- Detection gap: No single case file carried the scheduler, round, and issue state together.
- Prevention rule: No remote compile, verify, or benchmark without `plans/remote-scheduler.sqlite3`, and no stage is complete until the issue and ledger are both updated.
- Validation added: This case now maintains explicit `proposal`, `issue`, `task-plan`, `notes`, and `mistake-ledger` files.

## 2026-03-15 - Do not split instance method-cache fast paths without shadowing guards

- Symptom: The experimental exact `LoadMethod` cache split was preparing to return cached method values after checking only receiver type.
- Root cause: The split fast path bypassed `LoadMethodCache::lookup()` and therefore skipped the instance-dict `keys_version` validation used to detect method-name shadowing.
- Detection gap: The initial design focused on helper/call-shape cost and did not carry forward the full invalidation contract from the existing cache helper.
- Prevention rule: Do not turn a cache helper into an inline fast path unless all invalidation conditions from the helper are preserved explicitly.
- Validation added: The live exact-method-cache split producer has been removed before remote validation, and any future revival must include an explicit shadowing guard plus a focused regression test.

## 2026-03-15 - When a rejected optimization still has a live producer, remove it before benchmarking

- Symptom: The already-rejected `STORE_ATTR_INSTANCE_VALUE` overwrite fast path was still active enough to trip a positive runtime test during the ARM rebuild.
- Root cause: Historical notes marked the direction as bad, but the live builder path and its success-assertion test were not fully removed from the worktree.
- Detection gap: The regression was only rediscovered once the ARM rebuild executed the latest runtime suite.
- Prevention rule: When a hypothesis is declared non-landing, remove both its live producer and any test that still assumes it is the desired outcome.
- Validation added: The store-side fast path and its failing positive test were removed before the next remote step.

## 2026-03-15 - Shared codegen helpers must be guarded for non-AArch64 builds

- Symptom: x86 comparison build failed because `isStoreAttrInvokeTarget()` referenced an AArch64-only helper symbol.
- Root cause: An AArch64-specific helper path escaped into a shared codegen utility without a matching architecture guard.
- Detection gap: The issue was invisible on ARM and only surfaced once the x86 comparison build ran.
- Prevention rule: Any architecture-specific helper added under `codegen/` must be compiled once on the comparison architecture before the round is considered stable.
- Validation added: `isStoreAttrInvokeTarget()` now returns `false` on non-AArch64 builds, and the x86 current build completed afterward.

## 2026-03-15 - Do not put `PYTHONJITAUTO` on the pyperformance parent process

- Symptom: `python -m pyperformance ...` in the driver venv crashed or raised import-time failures as soon as the parent process inherited `PYTHONJITAUTO`.
- Root cause: The driver process itself is not the benchmark worker; it should stay in a safe startup mode and only the child worker should recover the requested autojit threshold.
- Detection gap: Earlier worker-hook debugging focused on `sitecustomize` path checks and not on the parent-process environment contract.
- Prevention rule: Keep the pyperformance parent process on `PYTHONJITDISABLE=1` and pass worker-only autojit state through a dedicated inherited variable.
- Validation added: `CINDERX_WORKER_PYTHONJITAUTO` is now consumed by `sitecustomize.py`, and both ARM and x86 worker rechecks passed.

## 2026-03-15 - Do not benchmark a candidate against a non-aligned baseline

- Symptom: The first round 2 comparison mixed the new aligned branch with the older round 1 current workdir and produced an unusable result.
- Root cause: The benchmark compared a candidate that already included latest-base alignment fixes against a baseline built from an older branch state.
- Detection gap: The branch-alignment work happened before the round 2 helper experiment, but the benchmark setup still pointed at the old baseline.
- Prevention rule: Once the branch base changes, rebuild a fresh aligned baseline before attributing wins or losses to the new optimization.
- Validation added: round 2 was re-run against `/root/work/cinderx-richards-basealign-r2`, producing the valid `-2.35%` richards win.

## 2026-03-16 - A shadowing-safe cache split can still lose end-to-end

- Symptom: The env-gated exact-instance method-cache split passed the new shadowing regression but still regressed whole `richards`.
- Root cause: Preserving correctness by adding fallback behavior kept the fast path from being cheap enough to pay for its extra branching and cache-shape machinery.
- Detection gap: The previous unsafe version failed on correctness before we could measure the fully safe variant.
- Prevention rule: When a previously unsafe optimization is revived with the missing correctness checks restored, treat it as a new performance experiment rather than assuming the earlier win hypothesis still holds.
- Validation added: the exact-instance cache split now has both a shadowing regression and a direct richards benchmark result, and the result is explicitly negative.

## 2026-03-17 - Fix the cause, not the shape, for polymorphic virtual calls

- Symptom: The biggest richards win in this round did not come from adding more cache structure; it came from refusing to apply monomorphic `LOAD_ATTR_METHOD_WITH_VALUES` lowering to non-exact receivers.
- Root cause: `Task.runTask` was hurt because a single-type method-with-values specialization was fundamentally the wrong lowering for a polymorphic virtual call.
- Detection gap: Earlier rounds focused on repairing or accelerating the specialized path instead of first asking whether the path should exist for that receiver shape.
- Prevention rule: When a deopt issue is caused by a specialization precondition mismatch, first try gating the specialization on a statically checkable precondition before adding more fallback machinery.
- Validation added: the exact-only builder gate produced a `-34.67%` richards win and a zero-deopt synthetic regression for the targeted polymorphic case.

## 2026-03-17 - After narrowing the gate, reclassify the remaining regressions

- Symptom: Once the issue-#44 gate was narrowed to non-exact `self`, the obvious target-family regressions disappeared but `logging_format` remained mildly slower.
- Root cause: Not every regression under the broad gate belonged to the same specialization bug family.
- Detection gap: The first sweep mixed true collateral regressions with unrelated or noisy ones.
- Prevention rule: After narrowing a fix, rerun a focused subset and treat the remaining regressions as a new, smaller localization problem.
- Validation added: the self-only gate recovered `comprehensions` and `richards_super`, leaving `logging_format` as the main residual target.

## 2026-03-17 - Do not overreact to single-value residual regressions

- Symptom: `logging_format` looked like a persistent regression in the first focused subset.
- Root cause: `--debug-single-value` on a tiny logging benchmark was too noisy to treat one pass as conclusive.
- Detection gap: The first subset pass optimized for speed of localization rather than statistical confidence.
- Prevention rule: For tiny residual regressions, rerun repeated samples before changing code to fix them.
- Validation added: 5 repeated `logging` pyperformance runs showed `logging_format` at `-0.76%`, so it is no longer the top residual concern.
