# Notes: Issue 18

## Narrowed Problem Statement
- Stage 1 from the issue is mostly already implemented for exact lists:
  - `list[mid]` becomes `IndexUnbox + CheckSequenceBounds + LoadArrayItem`
- The real missing part is exact-list slicing:
  - `list[:mid]`
  - `list[mid+1:]`

## Candidate Implementation
- Add a new HIR instruction, likely `ListSlice`, rather than forcing this through generic `BinaryOp`.
- Lower `ListSlice` to a runtime helper that:
  - accepts `list`, `start_obj`, `stop_obj`
  - parses bounds without allocating a `PySliceObject`
  - calls `PyList_GetSlice`

## Why This Shape
- Smallest change that removes `BuildSlice` allocation.
- Keeps Python slice semantics centralized in one helper.
- Avoids overcommitting to a broader slice IR for tuples/strings/step slicing.

## Open Design Choice
- Initial version should likely support only step=`None`.
- If `BuildSlice` has a non-`None` step, leave it on the old generic path.

## Implemented Shape
- `simplifyBinaryOp()` now rewrites:
  - exact list
  - `BuildSlice<2>`
  - start/stop in `{NoneType, LongExact}`
  into `ListSlice`.
- `ListSlice` lowers to `JITRT_ListSlice(list, start_obj, stop_obj)`.
- `JITRT_ListSlice` uses:
  - `_PyEval_SliceIndexNotNone`
  - `PySlice_AdjustIndices`
  - `PyList_GetSlice`
  and does not allocate an intermediate `PySliceObject`.
- Because `BuildSlice` is a `DeoptBase`, DCE would not remove the dead slice object on its own.
- Added `ListSliceCleanup` after `RefcountInsertion` to remove dead `BuildSlice + Decref` remnants introduced by this specialization.

## Remote Verification Summary
- Baseline exact-list local repro:
  - `BuildSlice: 2`
  - `BinaryOp: 2`
  - `Decref: 4`
- Current exact-list local repro:
  - `ListSlice: 2`
  - no `BuildSlice`
  - no generic slice `BinaryOp`
  - `Decref: 2`
- Functional result remained:
  - `([10, 20], 30, [40, 50])`

## Benchmark Summary
- Host: `124.70.162.35`
- Baseline worktree:
  - `/root/work/cinderx-issue14-base`
- Current worktree:
  - `/root/work/cinderx-git`
- Both used:
  - `taskset -c 0`
  - `LD_LIBRARY_PATH=/opt/toolchains/gcc-12.3.1-2025.03-aarch64-linux/lib64`
  - `/root/work/cinderx-git/.venv-benchfinal/bin/python`
- Workload:
  - `test_local_list_slice()` with an exact local list
  - `1,000,000` iterations
  - `7` repeats
- Median:
  - baseline `1.3714s`
  - current `1.0596s`
  - about `22.7%` faster

## Parameter-Typed List Follow-up
- The user-facing test shape:
  - `def test_list_slice(lst: list): ...`
  did not initially hit the fast path even after `ListSlice` landed.
- Root cause:
  - without annotation guards, the parameter remained `Object` in final HIR
  - it never reached `TList`/`TListExact`
  - so `ListSlice` / `LoadArrayItem` specialization could not trigger
- Verified on remote:
  - explicitly enabling `enable_emit_type_annotation_guards()` immediately produced:
    - `GuardType: 1`
    - `ListSlice: 2`
    - `LoadArrayItem: 1`
- Implemented follow-up:
  - when `specialized_opcodes` is enabled, load function annotations and emit
    entry `GuardType` checks for a small builtin whitelist:
    - `list`, `tuple`, `dict`, `str`, `int`, `float`
  - this keeps the broader `emit_type_annotation_guards` option intact while
    enabling only builtin-specialization-relevant guards by default

## Parameter-Typed Benchmark
- Workload:
  - `test_list_slice(lst: list)` with a list argument
  - `1,000,000` iterations
  - `7` repeats
- Median:
  - baseline `0.8109s`
  - current `0.6255s`
  - about `22.9%` faster
