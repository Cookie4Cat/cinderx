# Notes: pyperformance generators HIR/LIR optimization

## Baseline Context
- Branch: `bench-cur-7c361dce`
- Host: `124.70.162.35`
- Unified remote entry:
  `scripts/push_to_arm.ps1` -> `scripts/arm/remote_update_build_test.sh`

## Prior Work Already Landed
- Low-local generator helpers can use instance-value field lowering.
- Generator `Decref/XDecref` lowering already has a generator-specific compact
  path.

## Questions To Answer
- What are the hottest compiled functions for `bm_generators` on the current
  branch?
- Which HIR opcodes still dominate after the older fixes?
- Is the next safe win in HIR simplification, builder lowering, or only in LIR?

## Baseline Answers
- Unified remote entry had to be run with:
  - clean workdir: `/root/work/cinderx-generators-base`
  - `ARM_RUNTIME_SKIP_TESTS=int_float_builtin_lowers_to_double_to_int,round_float_builtin_lowers_to_round_to_int`
- `pyperformance generators` baseline:
  - jitlist: `0.16045697103254497`
  - autojit50: `0.12096913601271808`
  - auto-jit compile summary:
    - `main_compile_count = 3`
    - compiled functions in the log: `tree`, `Tree.__init__`, `Tree.__iter__`

## Hot Function Evidence
- Forced-compile HIR probe for `bm_generators` showed:
  - `Tree.__iter__`:
    - `compiled_size = 2528`
    - dominant HIR ops:
      - `LoadField = 20`
      - `Guard = 10`
      - `Decref = 10`
      - `CondBranchCheckType = 6`
      - `CheckField = 5`
      - `YieldFrom = 2`
      - `Send = 2`
  - `tree`:
    - `compiled_size = 1704`
    - not in the timed traversal loop

## Direction Chosen
- HIR is already near the floor for this shape:
  - field loads are specialized
  - attr-cache calls are gone
  - generator decref lowering is already compact
- The remaining hot loss is in LIR:
  - each `if self.left` / `if self.right` still routes plain-object truthiness
    through `_PyObject_IsTrue`
  - benchmark operands are overwhelmingly `Tree` or `None`, so the helper call
    is avoidable on the hot path

## TDD Target
- Add an ARM runtime regression for plain heap objects with no `__bool__` /
  `__len__`.
- Require LIR to show a richer compare-based fast path than the current bool-only
  truthiness lowering before the helper call.

## Final Verification
- Unified remote entry TDD run:
  - `WORKDIR=/root/work/cinderx-generators-tdd4`
  - `PARALLEL=2`
  - `SKIP_PYPERF=1`
  - result: `Ran 49 tests ... OK`
- Unified remote entry final run:
  - `WORKDIR=/root/work/cinderx-generators-verify`
  - `PARALLEL=2`
  - `SKIP_PYPERF=0`
  - result: `Ran 49 tests ... OK`
  - pyperformance:
    - jitlist: `0.06811246101278812`
    - autojit50: `0.0719388599973172`
- Same-host direct hot compare:
  - old median wall: `0.39330390794202685`
  - new median wall: `0.3489009899785742`
  - directional improvement: about `11.29%`

## Rejected / Watchlist
- Do not regress generator correctness or refcount ordering for a benchmark-only
  size win.
- Do not broaden changes into generic call inlining for generators unless the
  evidence requires it.
