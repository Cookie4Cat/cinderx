# [arm-opt][pyformance] richards: continue ARM backend narrowing after imported HIR win

## Proposal

- Case: `richards`
- Symptom: ARM still shows a backend/codegen disadvantage on richards hot functions after the imported HIR win, and the current worktree contains unverified cross-stage changes that need SOP-grade validation.
- Primary hypothesis: the next practical richards ARM gain is more likely to come from LIR method-call lowering and only then from a narrowly scoped AArch64 codegen path, not from more broad HIR churn.
- Planned order: `HIR -> LIR -> codegen`
- Validation: case-local plan + notes + issue + mistake ledger, scheduler-backed remote actions, review before remote spend, ARM-first loop, x86 comparison only after ARM stability.
- Exit criteria: every new stage attempt must either show a clear ARM win or be explicitly rejected and recorded; final ARM-vs-x86 position must be matched-methodology and explicit.

## Problem description

- Workload: `richards`
- User-visible symptom:
  - imported evidence shows richards hot functions are already near-HIR-parity between ARM and x86, but ARM still carries larger compiled size and frame / spill metrics.
  - the working tree now mixes HIR, LIR, and codegen deltas, so the next stage must be re-anchored before new remote work.
- Why it matters:
  - `richards` is one of the first object / dispatch-heavy pyformance cases targeted for ARM-vs-x86 narrowing.
  - the user asked for a strict case-level SOP with issue-first tracking, scheduler-backed remote use, repeat-error prevention, and a final one-shot x86 functionality validation only before merge.

## Current IR

- Current HIR/LIR/codegen evidence:
  - imported ARM summary: `/root/work/arm-sync/richards_hir_lir_20260314_183722/summary.json`
  - imported x86 summary: `/root/work/arm-sync/richards_hir_lir_x86_20260314_201125_execfix4/summary.json`
  - imported richards analysis: `plans/2026-03-14-richards-hir-lir-plan.md`
- Hot blocks / hot ops:
  - `HandlerTask.fn`
  - `Task.runTask`
  - `Packet.append_to`
  - `Task.qpkt`
  - richards remains attr-heavy, method-call-heavy, and guard / helper heavy.
- Known blockers:
  - the current worktree spans multiple stages and needs stage attribution before remote validation.
  - several historical “cleaner HIR” or “smaller codegen” ideas already lost end-to-end, so blind retries are forbidden.

## Target HIR

- Desired HIR shape:
  - preserve the imported richards HIR win from `LOAD_ATTR_METHOD_WITH_VALUES` and direct `VectorCall` lowering.
  - avoid reintroducing broad helper-heavy attr loads where field or method specialization already proved beneficial.
  - do not grow guard chains on low-local or store-heavy sites without new evidence.
- Why this shape should help:
  - imported evidence already showed that reducing helper-heavy method/attr traffic materially helped richards on ARM.
  - imported parity evidence also showed that richards is no longer mainly blocked by gross HIR divergence, so the current target HIR is “preserve the gain without destabilizing it”.

## Optimization suggestions

- HIR ideas:
  - imported win is preserved; no new HIR remote attempt unless a genuinely new hypothesis survives local audit and review.
- LIR ideas:
  - validate `CallMethod -> JITRT_CallMethod`.
  - validate explicit `LoadMethodCache` split / entry handling.
  - confirm whether the current LIR changes reduce helper traffic or call-shape overhead on ARM richards.
- codegen ideas:
  - if and only if the LIR stage is stable, validate the AArch64 `StoreAttrCache::invoke` stub path as a separate codegen hypothesis.
  - do not retry deopt stage-1 compaction or always-shared helper stubs without a changed causal story.
- Main risks:
  - method receiver / cache correctness regressions
  - refcount or dealloc bugs in AArch64 store-attr stub flow
  - benchmarking a mixed-stage patch and losing attribution
  - repeating already-rejected ideas under new names

## Minimal reproducer

- Source:
  - `cinderx/benchmarks/richards.py`
  - hot-function collector: `scripts/bench/richards_hir_lir_collect.py`
- Command:
  - verify / IR:
    - `PYTHONJITDUMPFINALHIR=1 PYTHONJITDUMPLIR=1 /root/venv-cinderx314/bin/python scripts/bench/richards_hir_lir_collect.py --output-json <out>/summary.json --iterations 1 --warmup-runs 3 --disasm-dir <out>/disasm --dump-elf <out>/richards.elf`
  - fast stage benchmark:
    - use the existing direct richards runner shape (`Richards.run(3)`, 9 samples) for quick ARM stage validation
  - final comparison:
    - matched ARM/x86 methodology only after the ARM round is stable
- Expected behavior:
  - correctness preserved
  - stage-local benchmark numbers are reproducible and clearly labelled by runner type
  - any claimed win must be backed by an explicit ARM delta

## Baseline and environment

- ARM host: `124.70.162.35`
- x86 host: `106.14.164.133`
- Scheduler DB:
  - `plans/remote-scheduler.sqlite3`
- Remote workdir:
  - preferred shared workdir for this SOP thread: `/root/work/cinderx-richards-sop`
- ARM baseline:
  - imported same-host fresh baseline package: `631c95d9`
  - workdir: `/root/work/cinderx-richards-baseline-631c95d9`
  - direct `Richards.run(3)` median: `0.23786746303085238s`
  - imported HIR-win environment:
    - workdir: `/root/work/cinderx-richards-hiropt2-20260314_235251`
    - median: `0.2626585039542988s`
    - note: preserves the documented HIR gain relative to its own pre-optimization probe, but is not a same-host baseline replacement
- x86 baseline or comparison plan:
  - imported x86 HIR/LIR summary already exists for parity analysis
  - final x86 compare will be rerun only after the ARM round is stable and under matched methodology
- Benchmark settings:
  - direct `Richards.run(3)` 9-sample probe for fast stage-local validation
  - matched runner and warmup policy required for any ARM-vs-x86 conclusion
  - x86 functional validation is deferred until the final pre-merge check

## Repeat-error prevention

- Known mistakes to avoid:
  - do not retry `STORE_ATTR_INSTANCE_VALUE` overwrite fast path without a different site classification
  - do not retry specialized attr guard dedup as if it were still untested
  - do not use `PYTHONJITINSTANCEVALUEMINLOCALS=1` as a richards fix path
  - do not retry AArch64 deopt stage-1 compaction or always-shared helper stubs without a changed causal story
  - do not treat `spill_stack_size` as a pure regalloc-spill count
  - do not mix direct-probe and pyperformance-style numbers in the same comparison claim
- New guardrails added in this round:
  - case-local proposal / issue / notes / task-plan / mistake-ledger files are mandatory
  - every remote action must go through `plans/remote-scheduler.sqlite3`
  - no new remote retry without a changed hypothesis, changed patch, or changed validation
  - no x86 benchmark lease until the ARM round is stable

## Round plan

- Imported historical stages:
  - HIR parity and HIR win evidence imported from `plans/2026-03-14-richards-hir-lir-plan.md`
  - losing HIR and backend prototypes imported and blacklisted in the mistake ledger
- SOP reset round 1:
  - HIR:
    - audit the current dirty HIR delta against imported wins and rejections
    - if there is no genuinely new HIR hypothesis, mark HIR closed for this round without a new remote compile
  - LIR:
    - review and isolate the live method-cache / `CallMethod` lowering changes
    - if review is clean, run scheduler-backed ARM compile / verify / benchmark for this stage
  - codegen:
    - only after LIR evidence is stable, review and isolate the AArch64 `StoreAttrCache::invoke` stub path
    - validate it as a distinct codegen hypothesis, not mixed into the LIR result
- Future rounds:
  - loop back to HIR only if new ARM-vs-x86 evidence shows fresh HIR divergence or a missing HIR reproducer
  - otherwise continue lower-stage narrowing with strict evidence-first updates

## Exit criteria

- Each new attempted stage in the SOP loop produces one of:
  - clear ARM win
  - explicit rejection with evidence and mistake-ledger update
  - blocked status with the blocker written down
- Final ARM-vs-x86 comparison uses the same workload and methodology.
- Remaining ARM gap is either materially reduced or explicitly accepted with a documented reason.
- All scheduler leases are released and the active remote workdir has an owner.
- Pre-merge x86 work is limited to one final functionality pass.

## Round 1 - local review

### Context

- Case: `richards`
- Stage: `hir`
- Lease id / scheduler DB:
  - no remote lease
  - scheduler initialized locally at `plans/remote-scheduler.sqlite3`
- Remote workdir:
  - none yet

### Goal

- Audit the current dirty worktree before remote use and eliminate correctness holes that would make later ARM results untrustworthy.

### Change summary

- Reviewed the live HIR/LIR/codegen delta using the case-local SOP files plus the current git diff.
- Removed the live exact `LoadMethod` cache split producer from `cinderx/Jit/hir/simplify.cpp`.
- Why this change is safe:
  - it falls back to the existing `LoadMethodCached` helper path that already enforces the correct invalidation rules.
  - it blocks an unsafe experimental HIR path before any remote compile or benchmark depends on it.

### Evidence

- IR delta:
  - the removed path had compared only cached receiver type before reading cached method value directly.
  - the normal `LoadMethodCache::lookup()` path also checks instance-dict `keys_version`; the split fast path did not.
- Reproducer result:
  - no remote run yet; this was a local correctness review blocker.
- Tests:
  - no new test yet
  - current action was to prevent the unsafe path from becoming benchmark input

### Benchmark delta

- ARM:
  - not run
  - review blocker resolved locally before remote use
  - delta: not applicable
- x86 status:
  - not run yet

### Decision

- Status: `complete`
- Next action: finish stage attribution on the remaining live LIR/codegen delta, then prepare the minimum ARM remote action needed for the next distinct hypothesis.
- Risks or blockers:
  - supporting exact-method-cache experimental scaffolding still exists in the tree, but it no longer has a live producer in HIR.

### Retrospective

- What went wrong or almost went wrong:
  - an experimental cache split was about to bypass an existing invalidation contract.
- Why it was missed:
  - the optimization story focused on helper cost before re-checking the original cache helper's correctness conditions.
- New prevention rule:
  - do not inline a cache fast path unless every invalidation and shadowing condition from the helper remains explicit.

## Round 1 - lir

### Context

- Case: `richards`
- Stage: `lir`
- Lease id / scheduler DB:
  - compile: `4`
  - benchmark: `5`
  - scheduler: `plans/remote-scheduler.sqlite3`
- Remote workdir:
  - HIR-base: `/root/work/cinderx-richards-hirbase-r1`
  - current: `/root/work/cinderx-richards-lir-r1`

### Goal

- Validate whether the remaining current worktree delta still delivers an ARM win relative to the imported HIR-only baseline once the unsafe HIR experiments are removed.

### Change summary

- Fixed compile/runtime blockers uncovered during the current rebuild loop:
  - `simplifyCallMethod()` invalid `Type > TNullptr` comparison
  - missing `kFillMethodCache` memory-effects entry
  - store-side `STORE_ATTR_INSTANCE_VALUE` overwrite fast path and its failing positive test
- Rebuilt the current worktree and compared it against an isolated HIR-base rebuild using the same `method_call_helper_bench.py` runner.

### Evidence

- IR delta:
  - current patch no longer includes the unsafe exact method-cache split producer
  - current patch no longer carries the previously rejected store-side overwrite fast path
- Reproducer result:
  - benchmark script: `artifacts/arm/method_call_helper_eval_20260309_193054/method_call_helper_bench.py`
- Tests:
  - current ARM rebuild passed 23 runtime tests

### Benchmark delta

- ARM:
  - HIR-base `richards`: `0.2162761030s`
  - current `richards`: `0.1793787990s`
  - delta: `-17.06%`
  - HIR-base `method_chain`: `0.0016903901s`
  - current `method_chain`: `0.0016239550s`
  - delta: `-3.93%`
- x86 status:
  - not run yet for this stage

### Decision

- Status: `complete`
- Next action: test the env-gated AArch64 store-attr stub as a separate codegen stage, then run current-vs-current x86 comparison.
- Risks or blockers:
  - the helper-script pyperformance path still fails in its worker-hook verification, so this round is backed by direct benchmark evidence rather than formal pyperformance output

### Retrospective

- What went wrong or almost went wrong:
  - the first two current rebuild attempts only surfaced latent compile/test blockers.
- Why it was missed:
  - the local machine could not do a like-for-like native build, so ARM rebuilds became the first true compiler gate.
- New prevention rule:
  - when the local toolchain cannot compile the target configuration, treat the first successful remote build as part of proof, not just deployment.

## Round 1 - codegen

### Context

- Case: `richards`
- Stage: `codegen`
- Lease id / scheduler DB:
  - benchmark: `6`
  - scheduler: `plans/remote-scheduler.sqlite3`
- Remote workdir:
  - `/root/work/cinderx-richards-lir-r1`

### Goal

- Exercise the AArch64 `StoreAttrCache::invoke` shared-stub path in isolation and see whether it gives a meaningful ARM win on the current richards shape.

### Change summary

- Benchmarked the current worktree twice with the same isolated venv:
  - stub effectively off: `PYTHONJITAARCH64STOREATTRSTUBMINCALLS=1000000`
  - stub on: `PYTHONJITAARCH64STOREATTRSTUBMINCALLS=6`

### Evidence

- Tests:
  - no additional compile or runtime test changes in this stage
- Benchmark artifacts:
  - `artifacts/richards_codegen_round1_results_20260315_175100/`

### Benchmark delta

- ARM:
  - stub off `richards`: `0.1935252650s`
  - stub on `richards`: `0.1807337359s`
  - delta: `-6.61%`
  - stub off `method_chain`: `0.0017029609s`
  - stub on `method_chain`: `0.0016588881s`
  - delta: `-2.59%`
- x86 status:
  - not run yet for this stage

### Decision

- Status: `complete`
- Next action: run x86 comparison for the current default configuration.
- Risks or blockers:
  - default no-env current richards (`0.1793787990s`) was still slightly faster than the stub-on run (`0.1807337359s`)
  - treat the store-attr stub as an experimental env-gated win, not yet a default richards landing configuration

### Retrospective

- What went wrong or almost went wrong:
  - the env-present "off" baseline is not perfectly identical to the no-env default path.
- Why it was missed:
  - `useStoreAttrInvokeStub()` is keyed off environment-variable presence, so "off" and "unset" are not the same path shape.
- New prevention rule:
  - for env-gated codegen probes, record both the env-off baseline and the natural no-env baseline before proposing a default setting change.

## Round 1 - comparison

### Context

- Case: `richards`
- Stage: `comparison`
- Lease id / scheduler DB:
  - x86 compile: `10`
  - x86 benchmark: `11`
  - scheduler: `plans/remote-scheduler.sqlite3`
- Remote workdir:
  - x86 current: `/root/work/cinderx-richards-x86-r1`

### Goal

- Measure the remaining ARM-vs-x86 gap for the current default configuration using the same direct benchmark script.

### Change summary

- Fixed an x86-only compile failure where a shared codegen utility referenced an AArch64-only helper.
- Built and benchmarked the current worktree on x86 using the same `method_call_helper_bench.py` runner.

### Evidence

- Tests:
  - x86 build smoke passed with `force_compile()` on a simple function
- Benchmark artifacts:
  - local: `artifacts/richards_x86_round1_results_20260315_181000/richards_x86_current.json`
  - remote: `/root/work/arm-sync/richards_x86_current.json`

### Benchmark delta

- ARM current:
  - `richards`: `0.1793787990s`
  - `method_chain`: `0.0016239550s`
- x86 current:
  - `richards`: `0.2460568990s`
  - `method_chain`: `0.0020649391s`
- Remaining gap:
  - `richards`: ARM faster by `27.10%`
  - `method_chain`: ARM faster by `21.36%`

### Decision

- Status: `complete`
- Next action: keep the direct-benchmark evidence, then decide whether to spend additional time on unblocking the formal pyperformance worker-hook path before closure.
- Risks or blockers:
  - the official pyperformance worker-hook path still reports `sitecustomize did not load from the pyperformance venv`
  - the single final pre-merge x86 functionality run has not been spent yet

### Retrospective

- What went wrong or almost went wrong:
  - x86 comparison surfaced multiple environment and cross-arch compile blockers before the actual benchmark could run.
- Why it was missed:
  - the ARM-first loop intentionally deferred x86 work until late, so shared-codegen arch guards were not exercised earlier.
- New prevention rule:
  - when shared codegen helpers change, expect the x86 comparison build to be part of the stage-stability gate, even if the performance question is ARM-first.

## Round 1 - formal pyperformance

### Context

- Case: `richards`
- Stage: `comparison`
- Lease id / scheduler DB:
  - ARM verify: `12`
  - ARM benchmark: `13`
  - x86 benchmark: `14`
  - scheduler: `plans/remote-scheduler.sqlite3`
- Remote workdir:
  - ARM current: `/root/work/cinderx-richards-lir-r1`
  - x86 current: `/root/work/cinderx-richards-x86-r1`

### Goal

- Unblock the official pyperformance worker-hook path and collect formal `richards` numbers on both hosts.

### Change summary

- Fixed two infrastructure issues:
  - `verify_pyperf_venv.py` now accepts hook-based `sitecustomize` paths when an explicit prefix is requested.
  - pyperformance parent processes now stay on `PYTHONJITDISABLE=1`, while workers recover `PYTHONJITAUTO` from `CINDERX_WORKER_PYTHONJITAUTO` inside `sitecustomize.py`.
- Re-ran worker verification on both ARM and x86; both passed.
- Ran formal `pyperformance run --debug-single-value -b richards` on both hosts.

### Evidence

- ARM worker recheck:
  - `/root/work/arm-sync/pyperf_venv_recheck_worker.json`
  - status: `ok=true`
- x86 worker recheck:
  - `/root/work/arm-sync/pyperf_venv_x86_recheck_worker_v2.json`
  - status: `ok=true`
- Formal pyperformance artifacts:
  - ARM: `/root/work/arm-sync/richards_arm_current_pyperf_autojit50_v2.json`
  - x86: `/root/work/arm-sync/richards_x86_current_pyperf_autojit50_v2.json`

### Benchmark delta

- ARM:
  - `richards`: `0.1145693631s`
- x86:
  - `richards`: `0.0748875150s`
- Comparison:
  - current formal pyperformance puts ARM `52.99%` slower than x86

### Decision

- Status: `continue`
- Next action:
  - do not close on the raw formal pyperformance gap yet
  - first rebuild x86 with a config-matched toolchain/settings so the formal cross-host number is trustworthy
- Risks or blockers:
  - the x86 current build path used a different Python/toolchain route than ARM and observed configure output showed mismatched feature settings
  - the single final pre-merge x86 functionality run is still reserved and unspent

### Retrospective

- What went wrong or almost went wrong:
  - we initially treated the pyperformance worker-hook failure as purely a path-validation bug, but the parent process environment also needed to be split from the worker environment.
- Why it was missed:
  - direct benchmark success masked the fact that formal pyperformance has a stricter parent/worker startup contract.
- New prevention rule:
  - when validating pyperformance, test the parent-process startup mode and worker startup mode separately before running the benchmark itself.

## Round 2 - next candidate

### Context

- Case: `richards`
- Stage: `lir`
- Starting point:
  - latest aligned base: `origin/bench-cur-7c361dce`
  - current validated branch carries the round 1 ARM and pyperformance fixes

### Candidate hotspot

- Tiny wrapper methods still carry the biggest per-function ARM-vs-x86 code-size gap:
  - `HandlerTaskRec.workInAdd`: `1000` vs `704`
  - `HandlerTaskRec.deviceInAdd`: `1000` vs `704`
  - `Packet.append_to`: `1056` vs `808`

### Candidate hypothesis

- The next plausible ARM gain is a correctness-safe exact-instance method-cache / call fast path for tiny wrapper methods.
- This should target wrapper shapes like `workInAdd()` / `deviceInAdd()` where richards still appears to pay too much method lookup/call scaffolding on ARM.

### Hard constraints

- Do not revive the old exact-cache split without shadowing checks.
- Keep the proof loop:
  - tiny wrapper microcase first
  - whole direct `richards` second
  - remote ARM benchmark only after local proof and review

## Round 2 - lir

### Context

- Case: `richards`
- Stage: `lir`
- Lease id / scheduler DB:
  - aligned-base compile: `6`
  - candidate compile: `3`
  - targeted verify: `4`
  - benchmark: `7`
  - scheduler: `plans/remote-scheduler.sqlite3`
- Remote workdir:
  - aligned base: `/root/work/cinderx-richards-basealign-r2`
  - candidate: `/root/work/cinderx-richards-lmcache-r2`

### Goal

- Test whether a minimal, correctness-safe `LoadMethodCache` hot-path reorder can reduce ARM overhead in richards tiny wrapper methods on the latest aligned base.

### Change summary

- Updated `LoadMethodCache::lookup()` to:
  - check slot 0 first on the monomorphic hot path
  - promote later exact-type hits into slot 0
- Also fixed two latest-base compile drifts needed to get the aligned branch building on ARM:
  - `gen_asm.cpp` / `gen_asm.h`
  - `builder.h`

### Evidence

- Targeted verify:
  - `test_jit_force_compile_smoke` passed
  - wrapper-specific `Packet.append_to` / `HandlerTaskRec.workInAdd` / `deviceInAdd` force-compile smoke passed
- Benchmark artifacts:
  - local: `artifacts/richards_round2_lmcache_results_20260315_235800/`
  - remote:
    - `/root/work/arm-sync/richards_lmcache_r2_basealign.json`
    - `/root/work/arm-sync/richards_lmcache_r2_candidate.json`

### Benchmark delta

- ARM:
  - aligned base `richards`: `0.2747411550s`
  - candidate `richards`: `0.2682828620s`
  - delta: `-2.35%`
  - aligned base `method_chain`: `0.0016784300s`
  - candidate `method_chain`: `0.0016314271s`
  - delta: `-2.80%`
- x86 status:
  - not rerun yet on a config-matched aligned baseline

### Decision

- Status: `complete`
- Next action:
  - keep the helper reorder as positive evidence
  - continue within the tiny-wrapper method path family, but only with designs that preserve explicit shadowing validity
- Risks or blockers:
  - the branch still needs a config-matched x86 rebuild before formal cross-host closure
  - broad ARM runtime failures on the latest base remain outside the scope of this round 2 method-cache change

### Retrospective

- What went wrong or almost went wrong:
  - the first round 2 comparison used an old non-aligned baseline and produced a misleading result.
- Why it was missed:
  - branch-alignment work and round 2 benchmark setup were not re-synced before the first compare.
- New prevention rule:
  - once the branch base changes, rebuild the baseline before attributing a new optimization result.

## Round 2 - lir follow-up

### Context

- Case: `richards`
- Stage: `lir`
- Lease id / scheduler DB:
  - compile: `9`
  - verify: `10`
  - benchmark: `11`
  - scheduler: `plans/remote-scheduler.sqlite3`
- Remote workdir:
  - `/root/work/cinderx-richards-exactcache-r2`

### Goal

- Re-test the exact-instance method-cache split idea, but this time with explicit shadowing safety, to see whether the tiny-wrapper hotspot still has extra headroom.

### Change summary

- Reintroduced the exact managed-dict method-cache split behind `PYTHONJITEXACTMETHODCACHESPLIT=1`.
- Added safety:
  - `LoadMethodCache::getValueHelper()` now falls back to a full lookup when slot-0 type or keys-version validation fails.
- Added a regression:
  - `test_exact_method_cache_split_respects_instance_shadowing`

### Evidence

- Targeted verify:
  - `test_jit_force_compile_smoke` passed
  - `test_exact_method_cache_split_respects_instance_shadowing` passed
- Benchmark artifacts:
  - `/root/work/arm-sync/richards_exactcache_off.json`
  - `/root/work/arm-sync/richards_exactcache_on.json`

### Benchmark delta

- ARM:
  - exact-cache split off `richards`: `0.2687889599s`
  - exact-cache split on `richards`: `0.2726917050s`
  - delta: `+1.45%`
  - exact-cache split off `method_chain`: `0.0016532539s`
  - exact-cache split on `method_chain`: `0.0016452830s`
  - delta: `-0.48%`
- x86 status:
  - not rerun for this negative ARM-only follow-up

### Decision

- Status: `regressed`
- Next action:
  - keep the safe exact-instance split recorded as a rejected idea
  - continue hunting in the tiny-wrapper call sequence family, but not with this cache-split structure
- Risks or blockers:
  - none specific to this candidate beyond the recorded regression

### Retrospective

- What went wrong or almost went wrong:
  - the correctness-safe rewrite did exactly what it was supposed to do semantically, but it still failed to pay for itself on whole richards.
- Why it was missed:
  - the previous unsafe attempt never gave us a trustworthy end-to-end number once the required validity checks were restored.
- New prevention rule:
  - once correctness repairs materially change a fast path, re-benchmark from scratch and do not assume the hotspot economics stayed the same.

## Round 2 - hir

### Context

- Case: `richards`
- Stage: `hir`
- Lease id / scheduler DB:
  - compile: `12`
  - verify: `13`
  - benchmark: `14`
  - scheduler: `plans/remote-scheduler.sqlite3`
- Remote workdir:
  - baseline: `/root/work/cinderx-richards-lmcache-r2`
  - candidate: `/root/work/cinderx-richards-poly-r2`

### Goal

- Fix issue #44 directly by stopping monomorphic `LOAD_ATTR_METHOD_WITH_VALUES` lowering on polymorphic virtual-call receivers such as `Task.runTask -> self.fn(...)`.

### Change summary

- Added a builder gate:
  - `LOAD_ATTR_METHOD_WITH_VALUES` only lowers through the monomorphic method-with-values fast path when `receiver->type().isExact()`
  - otherwise it falls back to the generic method path
- Added a regression:
  - `test_polymorphic_virtual_method_avoids_method_with_values_guard_deopts`

### Evidence

- Targeted verify:
  - `test_jit_force_compile_smoke` passed
  - `test_polymorphic_virtual_method_avoids_method_with_values_guard_deopts` passed
- Direct benchmark artifacts:
  - `/root/work/arm-sync/richards_polyfix_base.json`
  - `/root/work/arm-sync/richards_polyfix_new.json`
- Deopt probe:
  - benchmark-file probe did not report method-with-values deopts on either side, so the synthetic regression is the sharper validation for this exact issue shape
- Regression sweep artifacts:
  - local: `artifacts/richards_issue44_round2_results_20260317_223500/`

### Benchmark delta

- ARM direct benchmark:
  - baseline `richards`: `0.2724542680s`
  - candidate `richards`: `0.1779967260s`
  - delta: `-34.67%`
  - baseline `method_chain`: `0.0016417440s`
  - candidate `method_chain`: `0.0016625750s`
  - delta: `+1.27%`
- Requested regression sweep highlights:
  - regressions:
    - `comprehensions` `+7.34%`
    - `spectral_norm` `+4.25%`
    - `logging_format` `+3.26%`
    - `scimark_sor` `+2.82%`
    - `richards_super` `+2.54%`
  - wins:
    - `scimark_monte_carlo` `-9.02%`
    - `coroutines` `-7.03%`
    - `logging_simple` `-5.29%`
    - `raytrace` `-4.88%`
    - `go` `-3.98%`
    - `richards` `-0.92%` in the pyperformance sweep itself

### Decision

- Status: `continue`
- Next action:
  - keep this builder gate as the current best fix for issue #44
  - investigate the moderate regressions (`comprehensions`, `spectral_norm`, `richards_super`, `logging_format`, `scimark_sor`) before declaring it safe to land
- Risks or blockers:
  - no red-alert regressions appeared in the requested sweep, but there are enough `+2%` to `+7%` regressions that the change still needs follow-up before merge

### Retrospective

- What went right:
  - the direct fix matched the real problem statement better than the earlier cache-shape experiments and immediately produced a large richards win.
- Why it worked:
  - it removes the bad specialization instead of trying to compensate for it later.
- New prevention rule:
  - when the issue is “wrong specialization for polymorphic receiver”, first ask whether the specialization should fire at all.

## Round 2 - hir narrowing update

### Context

- Case: `richards`
- Stage: `hir`
- Lease id / scheduler DB:
  - compile: `16`
  - verify: `17`
  - benchmark: `18`
  - scheduler: `plans/remote-scheduler.sqlite3`
- Remote workdir:
  - candidate: `/root/work/cinderx-richards-poly2-r2`

### Goal

- Narrow the issue-#44 fix to the true problematic receiver class: non-exact local `self`.

### Change summary

- Builder gate changed from:
  - disable `LOAD_ATTR_METHOD_WITH_VALUES` for all non-exact receivers
- to:
  - disable it only when the receiver is local arg0 named `self` and is not exact

### Evidence

- Targeted verify:
  - `test_jit_force_compile_smoke` passed
  - `test_polymorphic_virtual_method_avoids_method_with_values_guard_deopts` passed
  - `test_exact_method_cache_split_respects_instance_shadowing` passed
- Direct benchmark artifacts:
  - `/root/work/arm-sync/richards_poly2_base.json`
  - `/root/work/arm-sync/richards_poly2_new.json`
- Focused regression subset artifacts:
  - `/root/work/arm-sync/richards_poly2_regress_base_v2.json`
  - `/root/work/arm-sync/richards_poly2_regress_new_v2.json`

### Benchmark delta

- ARM direct benchmark:
  - baseline `richards`: `0.2744622920s`
  - candidate `richards`: `0.1935804160s`
  - delta: `-29.47%`
  - baseline `method_chain`: `0.0016087320s`
  - candidate `method_chain`: `0.0016213530s`
  - delta: `+0.78%`
- Focused regression subset:
  - `comprehensions`: `-4.03%`
  - `richards`: `-1.15%`
  - `richards_super`: `-0.01%`
  - `logging_format`: `+2.76%`
  - `logging_silent`: `-1.41%`
  - `logging_simple`: `-0.73%`

### Decision

- Status: `continue`
- Next action:
  - treat the self-only gate as the current best issue-#44 fix
  - treat `logging_format` as likely noise after repeated sampling
  - if needed, localize `logging_simple` next
- Risks or blockers:
  - no obvious target-family regressions remain
  - a small `logging_simple` regression may still deserve explanation

### Retrospective

- What went right:
  - narrowing the gate around the true receiver class preserved the richards win while recovering the clearly related collateral regressions.
- Why it worked:
  - the problematic shape is specifically polymorphic virtual dispatch on non-exact `self`, not generic non-exact method receivers.
- New prevention rule:
  - once a broad gate proves the direction, narrow it to the smallest receiver classification that still fixes the target issue.

## Round 2 - logging repeat check

### Context

- Case: `richards`
- Stage: `comparison`
- Lease id / scheduler DB:
  - benchmark: `19`
  - scheduler: `plans/remote-scheduler.sqlite3`

### Goal

- Verify whether the residual `logging_format` regression from the focused subset was real or just debug-single-value noise.

### Change summary

- Re-ran `pyperformance logging` 5 times on:
  - baseline: `/root/work/cinderx-richards-lmcache-r2`
  - candidate: `/root/work/cinderx-richards-poly2-r2`
- Compared medians for:
  - `logging_format`
  - `logging_silent`
  - `logging_simple`

### Benchmark delta

- `logging_format`: `-0.76%`
- `logging_silent`: `+0.78%`
- `logging_simple`: `+2.35%`

### Decision

- Status: `complete`
- Next action:
  - drop `logging_format` as the main residual blocker
  - if more residual cleanup is needed, look at `logging_simple` instead
- Risks or blockers:
  - no high-confidence logging regression remains beyond the small `logging_simple` signal

### Retrospective

- What went wrong or almost went wrong:
  - a single-value `logging_format` sample looked worse than it really was.
- Why it was missed:
  - tiny benchmarks need repeated samples before we trust small deltas.
- New prevention rule:
  - for tiny residual regressions, repeat before patching.
