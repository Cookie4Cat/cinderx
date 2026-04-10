# Design Notes: issue-32 bimorphic unpack_sequence fast path

## Confirmed Root Cause
- `emitUnpackSequence()` already contains a tuple fast path and a list fast path.
- The actual blocker is the specialized-opcode preamble:
  - `UNPACK_SEQUENCE_LIST` inserts `GuardType(TListExact)`
  - `UNPACK_SEQUENCE_TUPLE` / `UNPACK_SEQUENCE_TWO_TUPLE` insert `GuardType(TTupleExact)`
- Once that guard is emitted, the alternate sequence type never reaches the later tuple/list dispatch logic and always deopts.

## Chosen Fix
- Remove the monomorphic pre-guard for specialized unpack opcodes.
- Keep the existing tuple/list dual-path lowering, but let the specialized opcode choose branch order:
  - tuple-specialized: check tuple first, list second
  - list-specialized: check list first, tuple second
- Deopt only if the runtime value is neither tuple nor list.

## Why This Is Safe
- The existing tuple and list lowering code is already present and correct.
- We are not broadening behavior to arbitrary iterables on the fast path.
- We preserve the profile-informed hot path order without making the function permanently monomorphic.

## Validation
- Add a regression with one shared `do_unpacking()` function that is called with both tuple and list after JIT compilation.
- Require:
  - no repeated deopts on the list half
  - both tuple and list data-path ops appear in HIR (`LoadFieldAddress` and `LoadField`)
  - correct runtime result
