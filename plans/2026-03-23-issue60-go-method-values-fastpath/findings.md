# Findings: Issue 60 go method-with-values fast path regression

## 2026-03-23 kickoff

- Working branch: `codex/issue60-go-method-values-profile`
- Clean worktree: `C:/work/code/generators-issue60-clean`
- Remote entry: `scripts/arm/remote_update_build_test.sh`
- Scheduler DB: `plans/remote-scheduler.sqlite3`

## Initial code inspection

- Current gate in `cinderx/Jit/hir/builder.cpp`:
  - `canUseMethodWithValuesFastPath()` returns true only for
    `hasStableExactReceiverType(receiver)`
- Current inliner scan in `cinderx/Jit/hir/inliner.cpp`:
  - only visits `VectorCall`
  - and `InvokeStaticFunction`
- So the only way method calls become inlinable today is:
  - builder turns `LOAD_ATTR_METHOD_WITH_VALUES` into const descr + fastcall shape

## Open items

- Need a small reproducer for attr-derived monomorphic receiver
- Need ARM data for current baseline and candidate

## Round 1 candidate - attr-derived + leaf-owner gate

- Candidate:
  - allow non-exact `LOAD_ATTR_METHOD_WITH_VALUES` fast path when:
    - receiver is attr-derived
    - descriptor owner has no subclasses
- Remote targeted result:
  - failed
- Failure mode:
  - new synthetic `Holder.reference.execute()` regression reopened
    `LOAD_ATTR_METHOD_WITH_VALUES` deopts
  - observed relevant deopt count: `10000`
- Decision:
  - reject
  - attr-derived alone is not a safe proxy for monomorphic receiver behavior

## Round 2 candidate - recursive same-method only

- Candidate:
  - allow non-exact `LOAD_ATTR_METHOD_WITH_VALUES` fast path only when:
    - receiver is attr-derived
    - callee qualname matches current function qualname
    - descriptor owner has no subclasses
- Remote targeted tests on `124.70.162.35`:
  - `test_attr_derived_monomorphic_method_load_restores_inlining`: `OK`
  - `test_attr_derived_polymorphic_method_load_avoids_method_with_values_deopts`: `OK`
  - `test_polymorphic_virtual_method_avoids_method_with_values_guard_deopts`: `OK`
  - `test_polymorphic_method_load_avoids_method_with_values_deopts`: `OK`
  - `test_polymorphic_loop_local_method_load_avoids_method_with_values_deopts`: `OK`

## Issue-specific performance signal

- Actual `bm_go` `Square.find` chain HIR stats:
  - baseline:
    - `CallMethod = 1`
    - `LoadMethodCached = 1`
    - `num_inlined_functions = 0`
  - candidate:
    - `CallMethod = 0`
    - `VectorCall = 1`
    - `num_inlined_functions = 1`
- Direct `Square.find` chain microbench with HIR inliner enabled:
  - base median: `0.005224066000209859s`
  - new median: `0.003888513000219973s`
  - delta: `-25.57%`
- Direct `bm_go.versus_cpu()`-style probe with HIR inliner enabled:
  - base median: `0.17524875899971448s`
  - new median: `0.1666271429999142s`
  - delta: `-4.92%`

## Broader performance signal

- Base/new subset (`go,raytrace,deltablue`, `SAMPLES=3`, default worker config):
  - `go`: roughly `145-146 ms -> 148-149 ms`
  - `raytrace`: roughly `445 ms -> 450 ms`
  - `deltablue`: roughly `5.07 ms -> 5.09 ms`
- Full requested subset smoke (`SAMPLES=1`) completed on both base and new:
  - no benchmark died
- Focused repeat subset (`comprehensions,coverage,scimark,spectral_norm,coroutines`, `SAMPLES=3`):
  - `comprehensions`: `+14.20%`
  - `spectral_norm`: `+5.45%`
  - `scimark_sor`: `+4.66%`
  - `scimark_sparse_mat_mult`: `+11.39%`
  - `coverage`: `-0.11%`
  - `coroutines`: `+0.10%`

## Current decision

- Status: `do not land yet`
- Reason:
  - the recursive-only gate clearly fixes the issue-specific hot path
  - but the requested broader regression sweep still shows too many suspicious
    regressions to call the change safe
- Next best direction:
  - stop extending static heuristics
  - move to a true profile-driven or hybrid fast-path-plus-generic-fallback
    design

## Round 3 candidate - hybrid fast path from interpreter specialization profile

- Candidate:
  - keep exact-receiver direct lowering
  - for non-exact `LOAD_ATTR_METHOD_WITH_VALUES`, carry the interpreter
    specialized cache data forward to the following `CALL`
  - on the call site, try:
    - fast branch: specialized-profile-based const-descr `VectorCall`
    - fallback branch: generic `CallMethod`
- Result:
  - compile/install succeeded
  - but the key targeted regression still failed:
    - `test_attr_derived_monomorphic_method_load_restores_inlining`
  - observed output:
    - `CallMethod = 1`
    - `VectorCall = 0`
    - `num_inlined_functions = 0`
- Interpretation:
  - the current hybrid plumbing does not yet reconnect the non-exact
    `LOAD_ATTR_METHOD_WITH_VALUES` site to an inlinable `VectorCall`
  - so the branch still does not satisfy the issue’s core requirement

## Round 4 candidate - snapshot-backed profile-driven gate

- Candidate:
  - keep the call-site hybrid design
  - only enable the profiled `LOAD_ATTR_METHOD_WITH_VALUES` recovery in the
    outer function body (`tc.frame.parent == nullptr`)
  - keep inner recursive calls inside already-inlined callees on generic
    `LoadMethodCached + CallMethod`
  - add an explicit leading `Snapshot` before both the fast-path and fallback
    call blocks so later inliner-introduced guards have a dominating frame state
- Root cause of the previous crash:
  - once the profiled fast-path `VectorCall` was inlined, `InlineFunctionCalls`
    expanded it into:
    - `LoadField`
    - `GuardIs`
    - `BeginInlinedFunction`
    - branch to callee CFG
  - our generated fast-path block originally had no leading `Snapshot`
  - `bindGuards()` in `RefcountInsertion` therefore saw `GuardIs` with no
    dominating snapshot and dereferenced a null frame-state pointer
  - `gdb --batch` and temporary `bindGuards()` logging confirmed the crash
    point:
    - `bb 7 instr GuardIs ... with snapshot 0x0`

## Round 4 targeted verification

- Remote targeted tests on `124.70.162.35`:
  - `test_attr_derived_monomorphic_method_load_restores_inlining`: `OK`
  - `test_attr_derived_polymorphic_method_load_avoids_method_with_values_deopts`: `OK`
  - `test_polymorphic_virtual_method_avoids_method_with_values_guard_deopts`: `OK`
  - `test_polymorphic_method_load_avoids_method_with_values_deopts`: `OK`
  - `test_polymorphic_loop_local_method_load_avoids_method_with_values_deopts`: `OK`
- Current monomorphic regression signal:
  - `CallMethod = 2`
  - `VectorCall = 0`
  - `num_inlined_functions = 1`
  - return value `9`
- Interpretation:
  - one outer attr-derived recursive call is now genuinely inlined again
  - the remaining recursive call inside the inlined callee intentionally stays
    generic for safety
  - this is why the final HIR still contains `CallMethod`

## Round 4 benchmark signal

- Direct issue-specific probes with HIR inliner enabled:
  - `Square.find` chain:
    - new median: `0.001345984s`
    - base median: `0.001318382s`
    - delta: about `+2.09%`
  - `bm_go.versus_cpu()`:
    - new median: `1.693260981s`
    - base median: `1.744004352s`
    - delta: about `-2.91%`
- Direct pyperformance `--debug-single-value` with HIR inliner enabled:
  - `go`: `127 ms -> 127 ms`
  - `raytrace`: `357 ms -> 356 ms`
  - `deltablue`: `3.74 ms -> 3.76 ms`
- Requested subset smoke on the new candidate with HIR inliner enabled:
  - completed:
    - `generators,coroutines,comprehensions,richards,richards_super,float,go,`
      `deltablue,raytrace,nqueens,nbody,unpack_sequence,fannkuch,coverage,`
      `scimark,spectral_norm,chaos,logging`
  - no benchmark died

## Updated decision

- Status: `candidate is now viable`
- Why:
  - the true profile-driven gate is working on the target attr-derived shape
  - the inliner crash is fixed by restoring a dominating snapshot in the
    generated call blocks
  - all five targeted regressions are green
  - the requested smoke subset no longer shows crash regressions
  - direct `bm_go.versus_cpu()` improves while `raytrace` / `deltablue` stay
    effectively flat
