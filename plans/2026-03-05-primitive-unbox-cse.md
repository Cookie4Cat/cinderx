# 计划：HIR PrimitiveUnbox CSE 优化（ARM 3.14）

## 目标
- 在 HIR 层新增 `PrimitiveUnbox CSE` pass，消除同一值同一类型的重复 unbox。
- 复现并修复 `g(x)=x+x` 场景中的双 `PrimitiveUnbox<CDouble>`。
- 按闭环执行：brainstorming -> writing-plans -> TDD -> verification-before-completion。
- 所有验证统一通过远端入口 `root@124.70.162.35`，关键结果写入 `findings.md`。

## Brainstorming
- 现象：`Simplify` 下沉后会产生重复 `PrimitiveUnbox`，当前无专门 CSE pass。
- 方案候选：
  1. 在 `simplify.cpp` 内联去重逻辑（耦合高）。
  2. 新建独立 HIR pass（推荐）。
- 选择：方案 2。
- pass 范围：先做“块内 CSE”（同基本块、同输入寄存器、同目标 primitive type）。
- 接入位置：`Simplify` 之后执行（并在后续第二次 `Simplify` 之后再执行一次）。

## Writing Plans
1. 新增 pass 文件：
- `cinderx/Jit/hir/primitive_unbox_cse.h`
- `cinderx/Jit/hir/primitive_unbox_cse.cpp`

2. 编译流水线接线：
- `cinderx/Jit/compiler.cpp` 引入并运行该 pass。

3. TDD：
- 在 `cinderx/PythonLib/test_cinderx/test_arm_runtime.py` 增加回归测试：
  - 构造 `g(x)=x+x` + float 热身 + `force_compile`
  - 用 `cinderjit.get_function_hir_opcode_counts(g)` 断言 `PrimitiveUnbox == 1`

## Verification Before Completion
- 远端执行：
  - 目标用例脚本：验证 `PrimitiveUnbox` 计数由 2 -> 1
  - 单测：`test_arm_runtime.py` 新增 case
  - 可选二次证据：`PYTHONJITDUMPFINALHIR=1` + `dump_elf` 查看单 `ldr` 路径

## 进度
- [x] Brainstorming
- [x] Writing-plans
- [x] TDD-RED
- [x] 实现 pass
- [x] TDD-GREEN
- [x] 远端验证与 findings 归档
