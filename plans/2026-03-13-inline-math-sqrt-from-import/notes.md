# Design Notes: issue-12 from-import math.sqrt intrinsify

## Current State
- Existing intrinsification matches:
  - `LoadModuleAttrCached("sqrt")`
  - followed by `VectorCall`
- This covers:
  - `import math`
  - `math.sqrt(x)`

## Missing Shape
- `from math import sqrt` produces a different callee path:
  - `LoadGlobalCached("sqrt")`
  - `GuardIs<builtin math.sqrt>`
  - `VectorCall`
- The current simplifier never reaches this path because it only inspects
  `LoadModuleAttrCached`.

## Safe Matching Strategy
- Generalize the known-sqrt matcher so it can validate a builtin `math.sqrt`
  object directly, not only via a module-attr load.
- Extend `simplifyVectorCallMathSqrt()` to recognize:
  - the existing module-attr callee path
  - a guarded callee whose `GuardIs` target is the builtin `math.sqrt` object

## Semantic Constraints
- We must preserve rebinding correctness.
- For the global-import shape, the existing `GuardIs` on the callee already
  provides the required guard and should remain in the optimized HIR.
- The optimization target is:
  - remove `VectorCall`
  - keep `DoubleSqrt`
  - preserve negative-input deopt behavior

## Validation
- Add a regression that compiles both:
  - `import math; math.sqrt(...)`
  - `from math import sqrt; sqrt(...)`
- Require both compiled functions to contain `DoubleSqrt` and no `VectorCall`.
