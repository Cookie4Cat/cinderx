# Deliverable: issue-22 generators attr/decref optimization

Implemented a generator-specific exception to the `LOAD_ATTR_INSTANCE_VALUE` low-local threshold in [builder.cpp](/c:/work/code/interpreter/cinderx/cinderx/Jit/hir/builder.cpp).

This change allows hot generator helpers such as `Tree.__iter__` to use the existing field-lowering path even when `co_nlocals` is small. A regression test was added in [test_arm_runtime.py](/c:/work/code/interpreter/cinderx/cinderx/PythonLib/test_cinderx/test_arm_runtime.py) to ensure low-local generators lower attribute accesses to fields instead of `LoadAttrCached`.

Remote ARM verification passed through the standard entry flow. A targeted repro confirmed `LoadField = 20` and `LoadAttrCached = 0`, which indicates the repeated cached attribute calls were removed. `Decref = 10` and `BatchDecref = 0` remain, so decref compaction is still open as a follow-up optimization.

The second phase added generator-only runtime helpers for `Decref/XDecref` in [generator.cpp](/c:/work/code/interpreter/cinderx/cinderx/Jit/lir/generator.cpp) and [jit_rt.cpp](/c:/work/code/interpreter/cinderx/cinderx/Jit/jit_rt.cpp). This keeps ordinary-function fast paths unchanged while collapsing generator decref lowering into compact calls. A second ARM runtime regression now checks that `Tree.__iter__` stays under a compact LIR block / compiled-size threshold (`bb_count = 43`, `compiled_size = 2424` in the verified build).
