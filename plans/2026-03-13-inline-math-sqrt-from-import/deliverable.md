# Deliverable: issue-12 from-import math.sqrt intrinsify

Extended the existing `math.sqrt` intrinsification to cover `from math import sqrt; sqrt(x)` call sites in addition to `import math; math.sqrt(x)`.

The implementation stays localized to [simplify.cpp](/c:/work/code/interpreter/cinderx/cinderx/Jit/hir/simplify.cpp): `VectorCall` simplification now accepts either the existing `LoadModuleAttrCached` callee shape or a guarded builtin `sqrt` callee (`GuardIs` target matches builtin `math.sqrt`).

Regression coverage was added in [test_arm_runtime.py](/c:/work/code/interpreter/cinderx/cinderx/PythonLib/test_cinderx/test_arm_runtime.py) to verify both import styles lower to `DoubleSqrt` with no `VectorCall`. Remote ARM verification passed and confirmed both paths are covered.
