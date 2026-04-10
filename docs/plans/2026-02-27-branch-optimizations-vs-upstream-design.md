# 分支优化相对上游 Main 的设计说明

日期：2026-02-27  
目标分支：`bench-cur-7c361dce`  
上游基线：`facebookincubator/cinderx` `main` @ `9e6a3cc92794de3cb8caaa698cb0861fc02a11d2`

## 目标
记录本分支当前携带的优化思路，解释其为何改善 Python 3.14 ARM 表现，并给出与上游同步时保持收益的稳定路径。

## 范围
- 范围内：
  - AArch64 JIT 代码生成与调用降级优化。
  - AArch64 调用结果 move 链的寄存器分配与 post-alloc 优化。
  - Python 3.14 ARM 默认特性开启（`ENABLE_ADAPTIVE_STATIC_PYTHON`、`ENABLE_LIGHTWEIGHT_FRAMES`）。
  - 影响性能兑现的构建/工具链稳健性（`LTO`、`PGO`）。
- 范围外：
  - 与 ARM JIT/运行时性能无关的功能开发。
  - 替换上游基准方法论。

## 基线与差距
- 当前分支与上游 main 的 merge-base：`17c27b6c09f968437b73385b641b4c3de5174048`。
- 分析时分叉规模：
  - 本分支独有提交：42
  - 上游独有提交：27
- 含义：
  - 本分支包含一批尚未进入上游的优化。
  - 上游也有本分支尚未合入的修复（bug/安全/运行时）。

## 设计摘要

### 1）AArch64 调用目标降级策略
问题：
- ARM 上重复 helper/runtime 调用会放大原生代码体积并增加分支跳转层级，拖累 JIT 吞吐与 I-cache 效率。

设计：
- 引入按绝对目标地址去重的调用目标字面量池。
- AArch64 `emitCall` 走字面量池入口（`ldr literal -> blr`）。
- 对单次/热点立即数目标做选择性直连字面量降级。
- 每个函数在尾声统一发射字面量池。

主要实现位置：
- `cinderx/Jit/codegen/environ.h`
- `cinderx/Jit/codegen/gen_asm_utils.cpp`
- `cinderx/Jit/codegen/gen_asm.cpp`
- `cinderx/Jit/codegen/frame_asm.cpp`

预期效果：
- 重复目标场景下代码体积下降。
- 单目标热点场景分支开销下降。
- 高调用内核下指令缓存局部性更好。

### 2）AArch64 调用结果寄存器链优化
问题：
- ARM 调用降级常出现 `retreg -> tmp -> argreg` 的 move 链，增加指令数与寄存器压力。

设计：
- Regalloc 软提示：
  - 对“调用结果立即作为下一次调用 arg0 使用”的短链，优先保留在返回寄存器。
- Postalloc 重写：
  - 折叠特定调用结果 move 链。
  - 允许跨不破坏寄存器的 guard/元数据指令折叠。
  - 在调用边界或 clobber 处停止，确保正确性。

主要实现位置：
- `cinderx/Jit/lir/regalloc.cpp`
- `cinderx/Jit/lir/postalloc.cpp`

预期效果：
- 热调用路径中冗余 move 指令减少。
- 编译函数体积更小，实际 IPC 更好。

### 3）Python 3.14 ARM 默认特性开启策略
问题：
- 若默认关闭高影响运行时特性，ARM 构建表现容易偏低。

设计：
- 在 OSS CPython 3.14 ARM（`aarch64`/`arm64`）默认开启：
  - `ENABLE_ADAPTIVE_STATIC_PYTHON`
  - `ENABLE_LIGHTWEIGHT_FRAMES`
- 保持 Meta 3.12 行为与环境变量覆盖语义。
- 提供运行时可观测 API，保证验证确定性：
  - `cinderx.is_adaptive_static_python_enabled()`
  - `cinderx.is_lightweight_frames_enabled()`

主要实现位置：
- `setup.py`
- `cinderx/_cinderx-lib.cpp`
- `cinderx/PythonLib/cinderx/__init__.py`
- `cinderx/PythonLib/test_cinderx/test_oss_quick.py`

预期效果：
- 3.14 ARM 默认特化行为更积极。
- 轻量帧路径下帧开销更低。

### 4）构建/工具链兑现（LTO/PGO）
问题：
- 当 LTO/PGO 在不同工具链/主机上不稳定时，性能意图无法兑现。

设计：
- 强化 clang LTO 链接稳健性（优先 `lld`，并校验 `LLVMgold` 回退）。
- 对 `CINDERX_ENABLE_LTO`/`CINDERX_ENABLE_PGO` 做严格且可预测的环境变量解析。
- 给易波动的 PGO 工作负载阶段加重试包装。

主要实现位置：
- `CMakeLists.txt`
- `setup.py`
- `tests/test_setup_adaptive_static_python.py`
- `tests/test_setup_lightweight_frames.py`
- `tests/test_setup_pgo_workload_retries.py`

预期效果：
- ARM 构建更高概率以目标优化配置运行。

## 验证策略
- 运行时正确性与 JIT 可用性：
  - `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
- 特性状态正确性：
  - `test_oss_quick.py` 与 `tests/` 下 API 级测试
- 性能证据：
  - 使用远端 ARM runner 与 richards 采集脚本
  - 将关键增量与命令证据写入 `findings.md`

## 风险与缓解
- 风险：分支与上游修复（安全/运行时）漂移。
  - 缓解：定期同步上游并重跑 ARM 性能门禁。
- 风险：架构特化优化影响 x86 或其他 Python 版本。
  - 缓解：在 setup 中保持 ARM 显式门控，并维护 ARM 专用测试。
- 风险：代码尺寸优化在部分模式下牺牲时延。
  - 缓解：保留尺寸护栏测试，并持续保留 A/B 基准工件。

## 集成计划
1. 按主题整理分支独有 ARM 优化提交（调用降级、regalloc/postalloc、默认特性、构建稳健性）。
2. rebase/cherry-pick 到最新上游 main。
3. 重跑远端 ARM 全量验证（`interp/JIT`、autojit、基准快照）。
4. 更新 `findings.md`，并保留本设计文档作为架构参考。
