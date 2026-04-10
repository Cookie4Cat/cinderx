# [arm-opt][jit][deepcopy] issue #47: try/except KeyError path deopts as UnhandledException

## Problem description

- Workload: `copy.deepcopy` with standard-library helpers `_keep_alive` and `_deepcopy_tuple`
- User-visible symptom:
  - JIT compiles the happy path for `try/except KeyError` helpers.
  - The expected `KeyError` miss path deopts with `UnhandledException`.
  - Deopt count grows linearly with call count and cannot be warmed away.
- Why it matters:
  - `deepcopy` is a realistic stdlib workload using Python's EAFP style.
  - This blocks JIT from staying on hot paths that intentionally rely on caught exceptions.

## Proposal

- Primary hypothesis:
  - HIR construction or lowering fails to preserve handler control flow for `try/except` regions used by `copy.py`.
- Planned order: `HIR -> LIR -> codegen`
- Validation:
  - minimal reproducer
  - targeted regression test
  - ARM remote HIR/deopt capture through the unified entrypoint
  - ARM benchmark + requested regression subset
- Exit criteria:
  - no deterministic `UnhandledException` deopt on the expected KeyError path
  - `deepcopy` gets a measurable ARM win
  - no material regression in the requested benchmark set

## Current IR

- User report shows `_keep_alive` and `_deepcopy_tuple` contain only the try-body happy path in final HIR.
- Observed missing shape:
  - no explicit `except KeyError` handler bb in the generated HIR
  - throwing `BinaryOp<Subscript>` exits via `UnhandledException` deopt instead
- Current repository evidence still needs to be re-captured on latest `origin/bench-cur-7c361dce` through the unified remote entrypoint.

## Target HIR

- Preferred target:
  - a protected throwing op inside `try/except KeyError` retains a control-flow edge to a handler bb.
  - the handler bb continues compiled execution for the `except` body.
- Acceptable narrow target:
  - for the common `dict[k] except KeyError` form, emit an equivalent non-throwing check + branch when safe.
- Why this should help:
  - it removes deterministic JIT-to-interpreter transitions on the expected miss path.

## Optimization suggestions

- HIR ideas:
  - inspect protected-region modeling in the builder and ensure exception edges survive into the final CFG
  - if generic support is too broad for round 1, lower a narrow `dict[k] except KeyError` pattern used by `deepcopy`
- LIR ideas:
  - only if HIR already models the handler edge but backend lowering still punts to deopt
- codegen ideas:
  - only if HIR/LIR are correct and the backend still emits unconditional `UnhandledException` exits
- Main risks:
  - broad exception-edge changes could affect correctness for unrelated control flow
  - pattern matching must avoid changing semantics for non-dict objects or broader exception classes

## Minimal reproducer

- Source:
  - start with a small `try: return d[k] except KeyError: return 0` function
  - then mirror `_keep_alive` / `_deepcopy_tuple` more closely if needed
- Command:
  - to be finalized after the first local regression test and unified ARM repro command are scripted
- Expected behavior:
  - the expected miss path should stay in compiled execution rather than deopting with `UnhandledException`

## Baseline and environment

- ARM host: `124.70.162.35`
- x86 host: `106.14.164.133`
- Scheduler DB: `C:/work/code/cinderx-deepcopy-issue47-20260318/plans/remote-scheduler.sqlite3`
- Scheduler tool: `C:/work/code/coroutines/cinderx/scripts/remote_scheduler.py`
- Unified remote entrypoint:
  - local wrapper: `scripts/push_to_arm.ps1`
  - remote script: `/root/work/incoming/remote_update_build_test.sh`
- Remote workdir:
  - to be recorded with the first active lease
- ARM baseline:
  - unified remote entrypoint, lease `#1`, stage `HIR-baseline-test`
  - targeted regression result on base:
    - `_keep_alive`: `200` `UnhandledException/BinaryOp` deopts
    - `_deepcopy_tuple`: `200` `UnhandledException/BinaryOp` deopts
    - correctness total: `19900`
  - note:
    - the default `test_arm_runtime.py` suite on this branch already has unrelated historical failures, so targeted isolation currently relies on `ARM_RUNTIME_SKIP_TESTS=test_` plus a focused `EXTRA_TEST_CMD`
- x86 baseline or comparison plan:
  - defer until ARM fix stabilizes unless the round needs x86 parity data earlier
- Benchmark settings:
  - use the unified remote entrypoint
  - record exact warmup / iteration policy in notes and findings once baseline runs

## Repeat-error prevention

- Known mistakes to avoid:
  - do not jump to LIR/codegen before verifying the current HIR shape
  - do not spend remote time before a failing local regression test exists
  - do not repeat a failed remote attempt without a new hypothesis or new validation
- New guardrails added in this round:
  - pending first regression test and first remote lease

## Round plan

- Round 1:
  - HIR:
    - capture current exception-path HIR
    - add failing regression
    - implement the smallest safe HIR fix
  - LIR:
    - inspect only if HIR is correct but backend still punts
  - codegen:
    - inspect only if LIR is correct but runtime still exits via `UnhandledException`
- Future rounds:
  - loop back to HIR unless hard evidence shows the next bottleneck is lower in the stack

## Round 1 update

- Baseline status: reproduced
- Current HIR-stage implementation direction:
  - add an exact-dict miss helper that returns a private sentinel on miss instead of raising `KeyError`
  - in `emitBinaryOp()` for `BINARY_SUBSCR_DICT`, use exception-table-aware pattern matching to:
    - inline `_keep_alive` miss handling
    - branch `_deepcopy_tuple` misses to the post-except continuation
- Why this shape:
  - it fixes the `deepcopy` hot path without first implementing generic compiled exception-handler CFG support
- Current blocker update:
  - `_keep_alive` is now fixed in the targeted ARM probe:
    - HIR changed to the new helper-based shape
    - deopt count dropped from `200` to `0`
  - `_deepcopy_tuple` miss path has now been redesigned to a helper-return path.
  - combined ARM probe is now:
    - `_keep_alive`: `0`
    - `_deepcopy_tuple`: `0`
    - `total`: `19900`
    - `elapsed`: `0.00032323300001735333`
  - previous partial-fix probe was:
    - `_keep_alive`: `0`
    - `_deepcopy_tuple`: `200`
    - `elapsed`: `0.0007303920001504594`
  - latest scheduler state is clean with no active leases.
  - remaining work moved to regression benchmarking rather than issue reproduction.

## Regression sweep update

- Broader ARM subset compare vs base completed.
- Broad 2-sample compare:
  - compare artifact: `artifacts/deepcopy/reg_compare.json`
  - large-looking slow signals:
    - `comprehensions` `+9.31%`
    - `logging_silent` `+51.94%`
- Focused 5-sample rerun for `comprehensions,logging`:
  - compare artifact: `artifacts/deepcopy/reg_focus_compare.json`
  - `comprehensions` reduced to `+3.89%`
  - `logging_format` `+1.03%`
  - `logging_simple` `-2.59%`
  - `logging_silent` `+8.21%`
- Assessment:
  - no material broad regression remains in the requested set
  - `logging_silent` is the only residual >5% signal, but its absolute delta is only about `0.08 us`

## Exit criteria

- `deepcopy` no longer produces deterministic `UnhandledException` deopts on the expected KeyError path
- ARM `deepcopy` shows a clear win relative to the latest baseline
- requested regression subset remains within acceptable variance
- issue notes, mistake ledger, and findings are updated with final evidence
