# Task Plan: issue-32 bimorphic unpack_sequence fast path

## Goal
Keep `UNPACK_SEQUENCE` on the compiled fast path for both tuple and list when a single hot function sees both types.

## Scope
- `HIRBuilder::emitUnpackSequence()`
- Specialized `UNPACK_SEQUENCE_*` opcode lowering
- Mixed tuple/list regression coverage
- Remote ARM verification through the standard test entry flow

## Workflow
1. Brainstorming: inspect current unpack lowering and confirm why mixed types still deopt
2. Writing-Plans: record the dual-fast-path design and tradeoffs
3. Test-Driven-Development: add a regression for shared tuple/list unpacking first
4. Verification-Before-Completion: run remote build/tests and record findings

## Status
- [x] Brainstorming
- [x] Writing-Plans
- [x] Test-Driven-Development
- [x] Verification-Before-Completion

## Remote Test Entry
- `scripts/arm/remote_update_build_test.sh`

## Latest Result
- The monomorphic specialized-opcode `GuardType` was removed from `UNPACK_SEQUENCE`.
- Specialized opcodes now only bias tuple/list branch order; they no longer prevent the alternate fast path from being used.
- Remote ARM verification passed through the standard entry script.
- Targeted remote repro results:
  - `LoadFieldAddress = 1`
  - `LoadField = 1`
  - `DeoptCount = 0`
  - tuple result `18000`
  - list result `18000`
- A lightweight remote benchmark on the shared function showed:
  - tuple `0.0292s`
  - list `0.0316s`
  - ratio `1.08x`
