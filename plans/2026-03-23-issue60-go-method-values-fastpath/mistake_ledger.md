# Mistake Ledger: Issue 60 go method-with-values fast path regression

## 2026-03-23

### Do not confuse “specialized opcode exists” with “safe to hardwire monomorphic HIR”
- The interpreter cache for `LOAD_ATTR_METHOD_WITH_VALUES` only carries one
  type-version / keys-version / descriptor triple.
- That is not the same as a robust multi-type profile.

### Keep the old issue44 regressions green
- Any recovery for `go` must continue to pass the existing polymorphic method
  deopt regressions, otherwise we are re-opening the earlier richards/raytrace
  failure mode.

### “attr-derived” is not enough
- Symptom:
  - `Holder.reference.execute()` is attr-derived but still polymorphic
- Why it matters:
  - reopening fast path on that shape immediately reintroduced the exact kind of
    `LOAD_ATTR_METHOD_WITH_VALUES` deopt storm we were trying to avoid
- Prevention rule:
  - every future candidate must keep both:
    - attr-derived monomorphic recursion regression
    - attr-derived polymorphic field regression

### Generated call blocks need an explicit leading snapshot
- Symptom:
  - after the profiled fast-path `VectorCall` was inlined, compilation crashed
    in `bindGuards()` / `RefcountInsertion`
- Root cause:
  - the builder-synthesized fast-path block started directly with the call
  - once inlined, that call expanded to `LoadField + GuardIs +
    BeginInlinedFunction`
  - `bindGuards()` requires a dominating snapshot in the same block before it
    binds frame state onto the injected guards
- Prevention rule:
  - if builder creates a fresh block that starts with a call-like instruction
    and later passes may rewrite that call into guards, always emit a
    `Snapshot` first
