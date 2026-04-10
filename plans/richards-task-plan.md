# 2026-03-15 Richards ARM Task Plan

## Metadata

- Case: `richards`
- Branch: `bench-cur-7c361dce`
- HEAD: `b14f114ee391`
- Skill order:
  - `$planning-with-files`
  - `$arm-pyformance-optimizer`
  - `$code-review-expert`
  - `using-superpowers` process check
- Shared scheduler DB: `plans/remote-scheduler.sqlite3`
- Remote hosts:
  - ARM `124.70.162.35`
  - x86 `106.14.164.133`
- Preferred remote workdirs:
  - ARM: `/root/work/cinderx-richards-sop`
  - x86: `/root/work/cinderx-richards-sop`
- Supporting files:
  - `plans/richards-proposal.md`
  - `plans/richards-issue.md`
  - `plans/richards-notes.md`
  - `plans/richards-mistake-ledger.md`

## Goal

- Continue the richards ARM optimization as a case-level closed loop.
- Preserve the imported HIR gain, avoid repeating already-failed ideas, and drive the remaining work strictly in `HIR -> LIR -> codegen` order.
- Require explicit ARM wins for every newly attempted stage, then compare against x86 only after the ARM round is stable.

## Scope

- Audit the current dirty worktree and classify each richards-relevant delta by stage.
- Produce and keep current the proposal, issue, notes, and mistake ledger.
- Use the shared scheduler for every remote action.
- Update the issue and ledger after each meaningful step or rejection.

## Non-goals

- Do not rerun historical failed prototypes without a new hypothesis or new validation.
- Do not spend x86 benchmark time before the current ARM round is stable.
- Do not do repeated x86 functionality runs; keep exactly one final pre-merge x86 functional check.

## Imported State

- Historical HIR parity work shows ARM and x86 have essentially matching richards HIR shape on the top hot functions, with the remaining gap already pointing below HIR.
- Imported HIR win:
  - `LOAD_ATTR_METHOD_WITH_VALUES`
  - direct `CallMethod(PyFunction, self, ...) -> VectorCall`
  - Historical ARM direct probe improved from `0.4713475180324167s` to `0.2626585039542988s`.
- Historical rejected or neutral paths already documented:
  - `STORE_ATTR_INSTANCE_VALUE` overwrite fast path: regressed badly.
  - specialized attr guard dedup: about `+0.6%` slower on same-host ARM fresh workdir.
  - `PYTHONJITINSTANCEVALUEMINLOCALS=1`: large regression.
  - AArch64 deopt stage-1 compaction: about `+2.3%` slower.
  - always-shared AArch64 helper-call stubs: about `+6.4%` slower.
- Current worktree contains 24 modified files spanning HIR, LIR, codegen, test, and remote script changes. It must be stage-audited before any new remote compile.

## SOP Phase Status

- Phase 0 Intake:
  - Status: `in_progress`
  - This file, notes, issue, proposal, and mistake-ledger files are being created now.
- Phase 1 Proposal and issue setup:
  - Status: `in_progress`
  - Proposal and issue draft must be created before any new code or remote action.
- Phase 2 Baseline and reproducer:
  - Status: `pending`
  - Need scheduler-backed ARM baseline refresh for the current worktree or explicitly reuse imported evidence.
- Phase 3 Local proof:
  - Status: `pending`
  - Need stage audit plus structured code review of the current delta.
- Phase 4 Remote ARM validation:
  - Status: `pending`
  - Must reserve `compile` / `verify` / `benchmark` leases through the shared DB.
- Phase 5 Remote x86 comparison:
  - Status: `pending`
  - Allowed only after ARM round is stable.
- Phase 6 Retrospective and prevention:
  - Status: `pending`
  - Every stage completion or rejection updates issue plus ledger.
- Phase 7 Closure or loop:
  - Status: `pending`
  - Close only after final ARM-vs-x86 position is explicit and all leases are released.

## Current SOP Round

- Round label: `SOP reset round 1`
- Why reset:
  - The repository already contains historical richards evidence, but it is scattered across plans, findings, and artifacts.
  - This SOP round imports that evidence and starts a fresh, explicit closed loop for the remaining unverified work.
- HIR status for this round:
  - Imported gain preserved.
  - No new HIR remote attempt until a genuinely new hypothesis survives local audit and review.
- LIR status for this round:
  - Candidate live work includes method-cache split and `CallMethod` lowering updates.
  - Needs code review and stage attribution.
- codegen status for this round:
  - Candidate live work includes the AArch64 `StoreAttrCache::invoke` stub path.
  - Must not be benchmarked before the LIR stage is made explicit.

## Thread Checklist Status

- [x] Case name confirmed: `richards`
- [x] Historical issue context imported into case-local files
- [x] Case-local plan and notes files created
- [x] Success criteria written down
- [x] Historical mistake evidence reviewed before new remote work
- [x] Shared scheduler DB initialized and status checked
- [ ] Current dirty worktree classified into `HIR / LIR / codegen`
- [x] Structured code review written against the current delta
- [ ] Current round issue update drafted
- [ ] ARM lease reserved for the next remote action
- [ ] ARM compile / verify / benchmark completed and lease released
- [ ] x86 comparison reserved only after ARM round is stable
- [ ] Final one-shot x86 functionality validation completed

## Next Actions

- [x] Initialize `plans/remote-scheduler.sqlite3` and record clean status.
- [ ] Map the current dirty worktree into stage buckets with exact file ownership and live hypotheses.
- [x] Run `$code-review-expert` workflow on the pending delta before remote spending.
- [ ] Decide whether the next live stage is truly `LIR` or whether a smaller HIR-only correction is still needed.
- [ ] Draft the first issue reply for `SOP reset round 1`, including imported evidence and the next remote question.
- [ ] Reserve the minimum ARM lease needed for the next concrete question.
- [ ] After each remote action, update `plans/richards-issue.md` and `plans/richards-mistake-ledger.md`.

## Round 2 Candidate

- Primary candidate:
  - tighten the tiny wrapper method path around `HandlerTaskRec.workInAdd` / `deviceInAdd`
- Why this is next:
  - current direct benchmark still shows the largest per-function ARM-vs-x86 code-size gap in the method-chain wrappers:
    - `HandlerTaskRec.workInAdd`: `1000` vs `704` (`+42.05%`)
    - `HandlerTaskRec.deviceInAdd`: `1000` vs `704` (`+42.05%`)
    - `Packet.append_to`: `1056` vs `808` (`+30.69%`)
- Working hypothesis:
  - richards still pays too much on ARM for exact-instance method lookup/call plumbing in these tiny wrappers.
  - the most promising next step is a correctness-safe instance method-cache fast path that preserves shadowing checks, not a blind retry of the earlier unsafe exact-cache split.
- Guardrails for round 2:
  - do not reuse the old exact method-cache split as-is
  - any new fast path must preserve instance-dict shadowing validity
  - benchmark tiny-wrapper microcase and whole `richards` together before declaring progress

## Round 2 Status

- Candidate:
  - `LoadMethodCache::lookup()` hot-path reorder:
    - explicit slot-0 fast path
    - promote later exact-type hits into slot 0
- Alignment fixes required before testing on latest base:
  - `gen_asm.cpp` / `gen_asm.h` drift against current `ModuleState` API
  - `builder.h` signature drift for `emitStoreAttr`
- ARM aligned-base rebuild:
  - compile lease `6`
  - workdir: `/root/work/cinderx-richards-basealign-r2`
  - build and focused richards wrapper smoke passed
- ARM candidate rebuild:
  - compile lease `3`
  - workdir: `/root/work/cinderx-richards-lmcache-r2`
  - broad runtime suite still contains unrelated base-branch failures, so round 2 correctness was checked with targeted wrapper validation instead
- ARM targeted verify:
  - verify lease `4`
  - `test_jit_force_compile_smoke` passed
  - wrapper-specific richards force-compile smoke passed
- ARM round 2 benchmark:
  - benchmark lease `7`
  - aligned base vs candidate:
    - `richards`: `0.2747411550s -> 0.2682828620s` (`-2.35%`)
    - `method_chain`: `0.0016784300s -> 0.0016314271s` (`-2.80%`)
- ARM round 2 follow-up candidate:
  - exact-instance method-cache split, now made shadowing-safe through `LoadMethodCache::getValueHelper()` fallback
  - compile lease `9`
  - verify lease `10`
  - benchmark lease `11`
  - result:
    - `method_chain`: `0.0016532539s -> 0.0016452830s` (`-0.48%`)
    - `richards`: `0.2687889599s -> 0.2726917050s` (`+1.45%`)
  - decision:
    - correctness is acceptable
    - performance is not good enough for landing
- ARM issue #44 candidate:
  - gate `LOAD_ATTR_METHOD_WITH_VALUES` lowering on exact receiver type only
  - compile lease `12`
  - verify lease `13`
  - benchmark lease `14`
  - result:
    - `method_chain`: `0.0016417440s -> 0.0016625750s` (`+1.27%`)
    - `richards`: `0.2724542680s -> 0.1779967260s` (`-34.67%`)
  - targeted regression:
    - new synthetic polymorphic virtual-method test passed
  - quick regression sweep vs `lmcache-r2`:
    - biggest regressions in the requested list were:
      - `comprehensions` `+7.34%`
      - `spectral_norm` `+4.25%`
      - `logging_format` `+3.26%`
      - `scimark_sor` `+2.82%`
      - `richards_super` `+2.54%`
    - most other listed cases were flat to better, including:
      - `coroutines` `-7.03%`
      - `go` `-3.98%`
      - `coverage` `-3.72%`
      - `raytrace` `-4.88%`
      - `richards` `-0.92%` in formal debug-single-value pyperformance mode

## Current Best Next Step

- Keep this round 2 helper reorder as positive evidence.
- The next candidate should still stay close to the polymorphic virtual-method problem, but the exact-instance cache split variant is now explicitly ruled out.
- The two most valuable follow-ups now are:
  - verify whether the `Task.runTask` deopt fix can be narrowed to avoid the small `richards_super` / `comprehensions` / `spectral_norm` regressions
  - a config-matched x86 rebuild so the formal ARM-vs-x86 comparison can be trusted again

## Hard Rules

- No remote command without a scheduler lease.
- No repeated failed attempt without a changed hypothesis, changed patch, or changed validation.
- No stage is considered done until issue plus ledger state are updated.
- No x86 benchmarking before the ARM round is stable.
- No more than one final x86 functionality validation before merge.

## Latest Local Review Outcome

- Scheduler:
  - `plans/remote-scheduler.sqlite3` initialized successfully.
  - current status: no active ARM or x86 leases.
- Blocker found and handled locally:
  - the experimental exact `LoadMethod` cache split in `cinderx/Jit/hir/simplify.cpp` skipped the instance-dict `keys_version` validation enforced by the normal `LoadMethodCache::lookup()` helper.
  - that made the feature unsafe for any receiver type whose instance dict can shadow the method name.
  - the live HIR producer for that path has been removed before any remote compile or benchmark.
- Updated round direction:
  - HIR remains "preserve imported win, no new live HIR experiment".
  - next live candidate should come from the remaining LIR/codegen deltas that still have a distinct hypothesis after review.

## Round 1 Status

- ARM HIR-base rebuild:
  - compile lease `1`
  - build plus ARM runtime tests passed
  - historical package lacked newer pyperf helper files, so the helper script's pyperf verification tail failed after the useful work was already done
- ARM current rebuild:
  - compile leases `2`, `3`, `4`
  - surfaced and fixed:
    - exact method-cache split correctness hole
    - invalid `Type > TNullptr` comparison in `simplifyCallMethod()`
    - missing `kFillMethodCache` memory-effects case
    - unreverted `STORE_ATTR_INSTANCE_VALUE` fast path and its failing positive test
  - final current build plus 23 ARM runtime tests passed on lease `4`
- ARM LIR benchmark:
  - benchmark lease `5`
  - HIR-base vs current direct benchmark:
    - `richards`: `0.2162761030s -> 0.1793787990s` (`-17.06%`)
    - `method_chain`: `0.0016903901s -> 0.0016239550s` (`-3.93%`)
- ARM codegen benchmark:
  - benchmark lease `6`
  - env-gated `PYTHONJITAARCH64STOREATTRSTUBMINCALLS=1000000 -> 6`:
    - `richards`: `0.1935252650s -> 0.1807337359s` (`-6.61%`)
    - `method_chain`: `0.0017029609s -> 0.0016588881s` (`-2.59%`)
  - note: default no-env current run (`0.1793787990s`) is still slightly faster than the stub-on run, so this remains an experimental codegen knob rather than a default merge setting
- x86 comparison:
  - x86 compile leases `7`, `8`, `9`, `10`
  - x86 benchmark lease `11`
  - current direct benchmark:
    - `richards`: `0.2460568990s`
    - `method_chain`: `0.0020649391s`
  - current ARM vs current x86:
  - `richards`: ARM faster by `27.10%`
  - `method_chain`: ARM faster by `21.36%`
- Formal pyperformance worker-hook fix:
  - ARM verify lease `12`
  - fixed:
    - `verify_pyperf_venv.py` no longer requires `sitecustomize` to come from the venv when an explicit prefix is requested
    - parent pyperformance processes no longer inherit `PYTHONJITAUTO`; workers recover it through `CINDERX_WORKER_PYTHONJITAUTO`
- Formal pyperformance richards:
  - ARM benchmark lease `13`
    - `richards`: `0.1145693631s`
  - x86 benchmark lease `14`
    - `richards`: `0.0748875150s`
  - caveat:
    - this x86 formal number came from a build path using `/root/venv-cinderx314/bin/python` and compile logs showed config differences relative to ARM (notably lightweight-frame/adaptive-static settings), so it is real evidence but not yet a final apples-to-apples closure number
- Remaining blocker before formal closure:
  - x86 formal pyperformance still needs a fully config-matched build path before we treat the cross-host number as final closure evidence
  - final pre-merge x86 functionality validation has not been spent yet

## 2026-03-17 Poly2 Update

- Narrowed issue-#44 gate:
  - disable `LOAD_ATTR_METHOD_WITH_VALUES` only for non-exact local `self`
- Lease trail:
  - compile `16`
  - verify `17`
  - benchmark `18`
- Result:
  - direct `richards`: `0.2744622920s -> 0.1935804160s` (`-29.47%`)
  - direct `method_chain`: `0.0016087320s -> 0.0016213530s` (`+0.78%`)
- Focused regression subset:
  - `comprehensions`: `-4.03%`
  - `richards`: `-1.15%`
  - `richards_super`: `-0.01%`
  - `logging_format`: `+2.76%`
  - `logging_silent`: `-1.41%`
  - `logging_simple`: `-0.73%`
- Current best next step:
  - keep the self-only gate as the best issue-#44 fix so far
  - treat `logging_format` as likely noise after repeated sampling
  - if we keep investigating residuals, `logging_simple` is now the more plausible logging-side follow-up
