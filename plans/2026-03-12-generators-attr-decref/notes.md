# Design Notes: issue-22 generators attr/decref optimization

## User-Observed Hotspots
- Repeated `LoadAttrCached` for the same receiver/name pair in generator code:
  - first load consumed by `IsTruthy`
  - second load consumed by the actual `yield from` / value path
- Large LIR/basic-block growth from many standalone `Decref` sites

## Initial Hypotheses
- The duplicated attr loads are likely caused by bytecode shape:
  - `if self.left:`
  - `yield from self.left`
  The builder emits two independent `LoadAttr`, and simplification lowers both to cached loads.
- This is a better first target than decref lowering because it removes:
  - extra C cache calls
  - one whole decref chain per duplicated load
  - redundant `IsTruthy` input object churn

## Candidate Optimization
- Recognize the pattern:
  - `x = LoadAttr[...] receiver`
  - `truth = IsTruthy x`
  - conditional branch
  - dominated reload of the same attribute from the same SSA receiver
- Reuse the first load instead of re-emitting the second cached load when no side-effecting instruction can invalidate the assumption.

## Secondary Optimization Area
- If generator performance is still poor after attr-load reuse:
  - inspect whether generator-specific decref sites can be batched earlier
  - or whether immortal / known-non-owning cases are still lowered too conservatively

## Phase 2 Decision
- `BatchDecref` is only formed for contiguous decref runs in one HIR block.
- The generator iterator shape does not satisfy that pattern, so `BatchDecref = 0` remained even after attr lowering.
- The smallest safe next step is not deeper HIR motion, but a generator-only LIR lowering change:
  - keep ordinary-function `Decref` inline
  - lower generator `Decref/XDecref` to runtime helpers
  - this directly attacks the basic-block explosion without changing refcount ordering

## Validation Strategy
- Add a targeted regression that dumps final HIR for a minimal generator tree iterator:
  - assert duplicate `LoadAttrCached<"left">` / `LoadAttrCached<"right">` counts drop
  - preserve functional output
- Run remote ARM validation and, if helpful, capture opcode counts for the compiled iterator helper.
- Add a second regression that dumps LIR for `Tree.__iter__` and asserts the generated block count / compiled size stay under a compact threshold.
