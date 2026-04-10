# Richards ARM Optimization Proposal

## Proposal

- Case: `richards`
- Symptom: ARM still shows a meaningful backend/codegen disadvantage on hot richards functions even after the imported HIR win; the current worktree also contains unverified cross-stage changes that must be validated in SOP order.
- Imported win to preserve:
  - `LOAD_ATTR_METHOD_WITH_VALUES`
  - `CallMethod(PyFunction, self, ...) -> VectorCall(func, self, ...)`
  - Historical ARM direct `Richards.run(3)` probe improved from `0.4713475180324167s` to `0.2626585039542988s` in the documented HIR environment.
- Primary hypothesis:
  - HIR is no longer the dominant unexplained gap for richards.
  - The next practical win is more likely to come from LIR lowering around method calls / method caches, and only then from a narrowly scoped AArch64 codegen path.
- Planned order: `HIR -> LIR -> codegen`
- Validation:
  - Create and maintain case-local plan, notes, issue, and mistake-ledger files.
  - Use `plans/remote-scheduler.sqlite3` for every remote `compile` / `verify` / `benchmark` action.
  - Audit the current dirty worktree by stage before any new remote compile.
  - Run structured code review before spending remote time on non-trivial deltas.
  - Use direct `Richards.run(3)` only as a fast stage probe, and keep final ARM-vs-x86 comparison on matched methodology.
- Key risks:
  - Current worktree mixes HIR, LIR, and codegen changes, so attribution can drift if we benchmark everything at once.
  - Richards has already shown HIR-shape improvements that were neutral or negative end-to-end.
  - Method-call lowering and AArch64 store-attr stub work can introduce receiver, cache, or refcount correctness bugs.
- Exit criteria:
  - Each new stage attempt in this SOP loop must show a clear ARM gain or be explicitly rejected and recorded.
  - No repeated remote retry without a changed hypothesis, changed patch, or changed validation.
  - Final ARM-vs-x86 comparison uses the same workload and methodology, and any remaining ARM gap is reduced or explicitly accepted.
  - Pre-merge x86 work is limited to one final functionality pass.
