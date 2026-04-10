# Task Plan: Issue 18 Exact List Slice Specialization

## Goal
Optimize exact-list slice patterns that still lower as `BuildSlice + BinaryOp<Subscript>` and remove avoidable `PySlice_New` allocation on the hot path.

## Scope
- Only target exact-list slicing for now.
- Do not touch generic `BinaryOp<Subscript>` semantics for non-list containers.
- Do not rework already-specialized single-item list subscripts.

## Findings So Far
- `list[idx]` for exact lists is already specialized today.
- `list[start:stop]` for exact lists is still emitted as:
  - `BuildSlice`
  - `BinaryOp<Subscript>`
  - immediate `Decref` of the slice object
- Remote repro confirms the missing optimization on ARM.

## Plan
- [x] Create planning files
- [x] Confirm current gap locally and on remote
- [ ] Add a dedicated exact-list slice HIR/runtime lowering path
- [ ] Add HIR tests
- [ ] Verify remotely with HIR and benchmark evidence

## Result
- Implemented exact-list slice specialization through:
  - `ListSlice` HIR
  - `JITRT_ListSlice` runtime helper
  - `ListSliceCleanup` post-refcount cleanup pass
- Scope intentionally limited to:
  - exact lists only
  - 2-operand slices only (`step is None`)
  - bounds that are `None` or `LongExact`
- Remote ARM verification confirmed:
  - `BuildSlice: 0`
  - `BinaryOp<Subscript>: 0` for the two slice operations
  - `ListSlice: 2`
  - single-item subscript remained on the already-existing `LoadArrayItem` fast path
