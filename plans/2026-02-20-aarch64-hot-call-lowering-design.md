# AArch64 Hot Call Lowering Design

Date: 2026-02-20
Scope: ARM64 JIT call lowering for hot paths (`instr != nullptr`)

## Context

Current AArch64 lowering behavior in `emitCall(env, uint64_t func, instr)` is:

- `instr == nullptr`: direct literal call (`ldr scratch, [literal]; blr scratch`)
- `instr != nullptr`: always call through helper stub (`bl helper_stub`)

This is good for repeated targets but suboptimal for single-use immediate call
targets in hot paths because:

- helper stub adds one extra dynamic branch hop
- helper stub materialization adds extra code for singleton targets

## Goal

Keep repeated-target dedup benefits while reducing overhead for singleton hot
immediate call targets.

## Non-Goals

- No changes to x86_64 behavior
- No runtime patching / self-modifying callsites
- No large codegen refactor outside AArch64 call emission

## Recommended Approach

Use a lightweight pre-pass over LIR to count immediate call target usage for
`lir::Instruction::kCall` on AArch64:

- count uses of each absolute immediate call target (`uint64_t`)
- in `emitCall(..., instr != nullptr)`:
  - if `instr->isCall()` and count <= 1: emit direct literal call
  - else: keep current helper-stub path

This preserves compact callsites for repeated targets while reducing
branch/size overhead for singleton hot calls.

## Tradeoffs

Pros:

- Low-risk, localized change
- No ABI changes
- Deterministic behavior (no runtime mutation)
- Targets the user-requested hot path

Cons:

- Pre-pass only covers `kCall` immediate targets, not every helper call emitted
  by non-Call lowering paths
- Singleton direct path can slightly increase callsite bytes for cases later
  discovered to be repeated (avoided by pre-pass counting)

## Validation Strategy

1. TDD regression:
   - add ARM runtime test asserting singleton immediate-call function gets a
     smaller baseline than repeated-target variant (size delta threshold)
2. Existing ARM compactness regression:
   - keep `test_aarch64_call_sites_are_compact` passing
3. Remote pipeline:
   - build + ARM runtime tests + targeted richards spot checks

## Success Criteria

- New singleton-call regression test fails before change and passes after.
- Existing ARM runtime tests stay green.
- No meaningful code-size regression in repeated-target compactness guard.
