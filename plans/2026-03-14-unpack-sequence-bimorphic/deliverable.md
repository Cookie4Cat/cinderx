# Deliverable: issue-32 bimorphic unpack_sequence fast path

Implemented a bimorphic tuple/list fast path for `UNPACK_SEQUENCE` in [builder.cpp](/c:/work/code/interpreter/cinderx/cinderx/Jit/hir/builder.cpp).

The existing tuple and list fast paths were already present, but specialized `UNPACK_SEQUENCE_*` opcodes previously inserted a monomorphic `GuardType` ahead of them, forcing the alternate sequence type to deopt forever. The fix removes that pre-guard and uses specialization only to choose which type check runs first.

Regression coverage was added in [test_arm_runtime.py](/c:/work/code/interpreter/cinderx/cinderx/PythonLib/test_cinderx/test_arm_runtime.py). Remote ARM verification passed and confirmed:
- both tuple and list paths remain in HIR (`LoadFieldAddress = 1`, `LoadField = 1`)
- repeated list-side deopts are gone (`DeoptCount = 0`)
- shared-function tuple/list performance is now close (`1.08x` ratio in the lightweight remote benchmark)
