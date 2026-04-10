## Code Review Summary

**Files reviewed**: focused review of the richards-relevant HIR/LIR/codegen delta plus runtime tests
**Overall assessment**: COMMENT

---

## Findings

### P0 - Critical

(none)

### P1 - High

1. **[cinderx/Jit/hir/simplify.cpp] exact LoadMethod cache split skipped instance shadowing validation**
  - The experimental fast path compared only cached receiver type and then used `LoadMethodCacheEntryValue`, bypassing the `keys_version` check performed by `LoadMethodCache::lookup()`.
  - That would allow a cached class method to survive after an instance dict shadows the same attribute name.
  - Action taken: fixed locally by removing the live HIR producer for this path before any remote compile or benchmark.

### P2 - Medium

2. **Experimental method-cache split scaffolding remains in the tree without a live producer**
  - The HIR/LIR/runtime support code for the exact-method-cache split is still present even though the unsafe HIR producer has been removed.
  - This is not a runtime blocker for the current round, but it is now dead experimental surface and should either be completed with proper invalidation guards or cleaned up in a follow-up once the richards round stabilizes.

### P3 - Low

(none)

---

## Removal/Iteration Plan

- Defer removal:
  - dead exact-method-cache split scaffolding
  - Why defer: it may still be useful as a future experiment once a correct shadowing guard design exists.
  - Preconditions: explicit invalidation design or decision to abandon the experiment for richards.
  - Validation: focused cache-shadowing regression test plus benchmark evidence if revived.

## Additional Suggestions

- If the AArch64 `StoreAttrCache::invoke` stub remains a live codegen candidate, add a regression test that overwrites an attribute with distinct object identities and verifies decref/dealloc behavior, not only size and integer-value correctness.
