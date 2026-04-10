# 计划：Static Python 编译期开关（Issue #3）

## 目标
新增编译期开关以控制 Static Python 功能路径是否启用，并满足以下验收重点：

1. CinderX 解释执行性能相对基线不回退。
2. CPython 解释执行对比结果不受影响（同口径对比不恶化）。
3. JIT 功能正常，JIT 性能不回退。

## 闭环流程

### 1. Brainstorming
- 评估最小可落地路径：新增全局编译选项，默认保持开启。
- 保持向后兼容：默认构建行为不变，避免对现有部署产生破坏。
- 选择宏名：`CINDER_ENABLE_STATIC_PYTHON`。

### 2. Writing Plans
- CMake 新增 `ENABLE_STATIC_PYTHON`，并导出宏 `CINDER_ENABLE_STATIC_PYTHON`。
- setup.py 新增同名环境开关透传到 CMake。
- 当 Static Python 关闭时，强制关闭 `ENABLE_ADAPTIVE_STATIC_PYTHON`。
- `_cinderx` 导出 `is_static_python_enabled()` 供 Python 层和测试检测。

### 3. TDD
- RED：先在 `test_oss_quick.py` 增加 `is_static_python_enabled` 用例，远端验证失败。
- GREEN：实现开关 + API，远端验证转绿。

### 4. Verification Before Completion
- 统一通过远端入口构建并执行：
  - 构建/安装/ARM 运行时门禁
  - `test_oss_quick.py`（新增用例）
  - 基准对比（CinderX interp/jit 与 CPython interp/jit）
- 将关键结论和数据写入 `findings.md`。

