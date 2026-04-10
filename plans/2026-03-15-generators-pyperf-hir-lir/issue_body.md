# generators: Tree.__iter__ truthiness fast path analysis and optimization

## Summary

This issue tracks the remaining profitable JIT work found for
`pyperformance generators` on branch `bench-cur-7c361dce`.

The earlier generator-specific work already removed the larger HIR issues:
- low-local generator field lowering
- compact generator decref lowering

After that, the main remaining hot loss was no longer in HIR. The hot function
was still `Tree.__iter__`, and its `if self.left` / `if self.right` branches
were still paying generic `PyObject_IsTrue` on the hot path.

## Baseline and hot-shape findings

Remote host:
- `124.70.162.35`

Unified verification entry:
- `scripts/arm/remote_update_build_test.sh`

Important operational detail:
- Meaningful runs had to use fresh remote workdirs (for example
  `/root/work/cinderx-generators-base` and
  `/root/work/cinderx-generators-verify`) because reusing an older workdir
  mixed incompatible tracked files and stale build outputs.

Consistent temporary skip tokens used for unrelated pre-existing ARM runtime
failures:
- `int_float_builtin_lowers_to_double_to_int`
- `round_float_builtin_lowers_to_round_to_int`

Forced-compile HIR probe on the baseline branch showed:
- `Tree.__iter__`
  - `compiled_size = 2528`
  - dominant HIR ops:
    - `LoadField = 20`
    - `Guard = 10`
    - `Decref = 10`
    - `CondBranchCheckType = 6`
    - `CheckField = 5`
    - `IsTruthy = 2`
- `tree`
  - `compiled_size = 1704`
  - not in the timed traversal loop

Conclusion:
- HIR was already close to its practical floor for this benchmark shape.
- The remaining profitable work was LIR-side truthiness lowering.

## Root cause

`Tree.__iter__` traverses child links using:
- `if self.left: yield from self.left`
- `if self.right: yield from self.right`

In the benchmark, those child values are overwhelmingly:
- `Tree` instances
- `None`

The generic LIR lowering for `IsTruthy` still retained `_PyObject_IsTrue` as
the dominant fallback. Even after the bool fast path landed earlier, plain heap
objects still went through the helper on the hot path.

That is unnecessary for the benchmark's dominant case because:
- `None` is always false
- a plain object with no `nb_bool`, `mp_length`, or `sq_length` slots is always
  true

## Implemented fix

Extended `Opcode::kIsTruthy` lowering in `cinderx/Jit/lir/generator.cpp`:

- `obj is Py_None` -> false immediately
- exact `bool` -> compare with `Py_True`
- if `tp_as_number == nullptr` or `nb_bool == nullptr`, continue checking
- if `tp_as_mapping == nullptr` or `mp_length == nullptr`, continue checking
- if `tp_as_sequence == nullptr` or `sq_length == nullptr`, return true
- otherwise fall back to `PyObject_IsTrue`

This preserves Python semantics for types that define truthiness slots while
removing the helper on the benchmark's common `Tree` / `None` path.

## Regression coverage

Added:
- `test_istruthy_plain_object_uses_default_truthy_fast_path`

Updated existing compactness guard:
- generator compactness threshold rebased to:
  - `bb_count <= 72`
  - `compiled_size <= 3000`

The shape changed because the new truthiness fast path intentionally expands
the hot LIR to save helper calls.

## Verification

### Unified entry, TDD phase

- `WORKDIR=/root/work/cinderx-generators-tdd4`
- `PARALLEL=2`
- `SKIP_PYPERF=1`
- result:
  - `Ran 49 tests ... OK`

### Unified entry, final verification

- `WORKDIR=/root/work/cinderx-generators-verify`
- `PARALLEL=2`
- `SKIP_PYPERF=0`
- `BENCH=generators`
- result:
  - `Ran 49 tests ... OK`

Artifacts:
- jitlist:
  - `/root/work/arm-sync/generators_jitlist_20260315_030445.json`
  - value: `0.06811246101278812 s`
- autojit:
  - `/root/work/arm-sync/generators_autojit50_20260315_030445.json`
  - value: `0.0719388599973172 s`
- autojit compile summary:
  - `/root/work/arm-sync/generators_autojit50_20260315_030445_compile_summary.json`
  - `main_compile_count = 3`
  - `other_compile_count = 0`

### Same-host direct hot comparison

This was the cleanest from->to performance signal collected in the session.

Old hot run:
- median wall: `0.39330390794202685 s`
- min wall: `0.3181799229932949 s`

New hot run:
- median wall: `0.3489009899785742 s`
- min wall: `0.26523061899933964 s`

From -> To:
- median wall: `-11.29%`
- min wall: `-16.64%`

## Current result shape

After the change:
- `Tree.__iter__`
  - `compiled_size = 2864`
  - `bb_count = 67`

The new LIR shows:
- explicit `Py_None` false fast path
- exact-bool fast path
- slot-null checks before the helper call
- preserved helper fallback for types that really need dynamic truthiness

## Notes / caveats

- A second full old-baseline rerun through the unified entry hit remote disk
  pressure while installing pyperformance venv dependencies (`[Errno 28] No
  space left on device`), so the same-host direct hot comparison above is the
  strongest clean A/B number from this session.
- The full remote gate for the new version did complete successfully.
