# Deliverable: issue-21 mutable load_global guard strategy

Implemented a safer `LOAD_GLOBAL` guard-selection strategy in [builder.cpp](/c:/work/code/interpreter/cinderx/cinderx/Jit/hir/builder.cpp).

The JIT now keeps identity guards for stable globals such as modules, functions, types, and immortal constants, while switching mutable heap-type globals to exact-type guards. This preserves the cached global fast path without hard-binding the compiled code to a single instance address.

Regression coverage was added in [test_arm_runtime.py](/c:/work/code/interpreter/cinderx/cinderx/PythonLib/test_cinderx/test_arm_runtime.py) for a rebinding `planner = Planner()` scenario. Remote ARM verification passed through the standard entry script, and the targeted repro confirmed `GuardIs = 0`, `GuardType = 1`, and `DeoptCount = 0`.
