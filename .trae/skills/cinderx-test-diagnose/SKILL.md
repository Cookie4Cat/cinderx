---
name: "cinderx-test-diagnose"
description: "定位和分析cinderx功能测试失败用例，逐文件运行测试并诊断崩溃和失败原因。当用户需要排查、定位、修复功能测试失败时调用此技能。"
---

# CinderX 功能测试失败定位与诊断

在远程 Linux 服务器上逐文件运行测试，定位失败/崩溃用例，分析根因，辅助修复。

## 配置与脚本

- 配置文件：`config.ini`（同 `cinderx-build-test`）
- `scripts/build_test.ps1` — 主脚本（`test-single` 操作用于单用例执行）
- `scripts/remote.ps1` — 底层远程连接脚本
- `scripts/run_tests_per_file.sh` — 逐文件运行测试的 Shell 脚本，隔离崩溃影响

## 诊断流程

### 第 1 步：检查远程环境

```powershell
powershell -ExecutionPolicy Bypass -File scripts/remote.ps1 `
  -Action exec -ConfigFile config.ini `
  -Command "cd /home/cinderx && /home/pybin/bin/python3.14 -c 'import cinderx; print(cinderx.get_import_error()); print(cinderx.is_initialized())'"
```

预期输出 `None` 和 `True`。失败则需先执行 `cinderx-build-test` 的 build 操作。

### 第 2 步：定位失败用例

根据是否已知具体失败用例，选择不同路径：

- **已知具体失败用例**（用户指定了文件名或用例路径）：跳过全量测试，直接进入第 3 步诊断该用例。
- **未知失败用例**（需要先发现哪些用例失败）：执行逐文件运行全部测试，收集失败信息。

#### 逐文件运行全部测试（仅在未知失败用例时执行）

```powershell
# 上传脚本
powershell -ExecutionPolicy Bypass -File scripts/remote.ps1 `
  -Action upload -ConfigFile config.ini `
  -LocalPath "scripts\run_tests_per_file.sh" -RemotePath "/home/run_tests_per_file.sh"

# 执行（后台运行）
powershell -ExecutionPolicy Bypass -File scripts/remote.ps1 `
  -Action exec -ConfigFile config.ini `
  -Command "chmod +x /home/run_tests_per_file.sh && cd /home/cinderx && nohup bash /home/run_tests_per_file.sh /home/pybin/bin/python3.14 cinderx/PythonLib/test_cinderx /home/test_results_full.txt 'test_jit_global_cache.py test_arm_runtime.py' 120 > /home/test_runner.log 2>&1 & echo PID=$!"
```

参数：Python路径、测试目录、结果文件路径、已知崩溃文件列表（空格分隔，跳过并标记）、超时秒数。

等待完成：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/remote.ps1 `
  -Action exec -ConfigFile config.ini `
  -Command "ps -p <PID> -o pid,stat,etime,comm 2>/dev/null && echo '--- Still running ---' || echo '--- Process completed ---'; tail -10 /home/test_results_full.txt 2>/dev/null"
```

下载测试结果：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/remote.ps1 `
  -Action download -ConfigFile config.ini `
  -RemotePath /home/test_results_full.txt -LocalPath "<work_dir>\test_results_full.txt"
```

分析结果，读取 `test_results_full.txt`，提取：
1. **汇总统计**：末尾 SUMMARY 的 PASSED/FAILED/SKIPPED/CRASHED 计数
2. **失败用例**：搜索 `FAILED` 关键字
3. **崩溃文件**：搜索 `CRASH` 关键字
4. **失败详情**：`FAILURES` 段落中的错误类型和堆栈

### 第 3 步：逐个诊断失败/崩溃用例

#### FAILED 用例诊断

1. **单独执行**：`build_test.ps1 -Action test-single -TestPath "<file>::<Class>::<method>"`
2. **查看源代码**：读取本地对应测试文件
3. **JIT 对比**（如怀疑 JIT 问题）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/remote.ps1 `
  -Action exec -ConfigFile config.ini `
  -Command "cd /home/cinderx && CINDERX_JIT_DISABLE=1 /home/pybin/bin/python3.14 -m pytest cinderx/PythonLib/test_cinderx/<file>::<Class>::<method> -v --tb=long 2>&1"
```

4. **定位根因**：根据错误信息判断类别（API兼容性/逻辑错误/JIT编译问题）
5. **读取相关源码**：根据堆栈读取 CinderX 对应的 Python/C++ 源码
6. **提出修复建议**

#### CRASH 文件诊断

1. **确认崩溃点**：找到 `*** CRASH ***` 标记
2. **逐用例缩小范围**：先用 `test-single` 运行类级别，再逐步缩小到方法
3. **获取 C 堆栈**：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/remote.ps1 `
  -Action exec -ConfigFile config.ini `
  -Command "cd /home/cinderx && /home/pybin/bin/python3.14 -m pytest cinderx/PythonLib/test_cinderx/<file>::<Class>::<method> -v --tb=long 2>&1 | tail -80"
```

4. **分析 C 堆栈**：`Current thread's C stack trace` 中的函数名可通过 `c++filt` 解码
5. **读取相关 C++ 源码**：根据函数名在 `cinderx/Jit/` 下搜索
6. **提出修复建议**

#### 修复后验证

修改代码后需先执行 `cinderx-build-test` 的 build 操作重新编译，再用 `test-single` 验证。

### 第 4 步：输出诊断报告

结构化报告包含：总体概览、失败用例详情（错误信息+根因+修复建议）、崩溃文件详情（崩溃点+堆栈分析+修复方向）、修复优先级建议。

## 常见根因分类

| 根因类别 | 典型表现 | 修复方向 |
|----------|----------|----------|
| Python版本兼容性 | `KeyError` 引用已移除的操作码/函数 | 更新测试代码适配 Python 3.14 |
| JIT HIR类型推断缺陷 | `chaseAssignOperand` 空指针崩溃 | 修复 `cinderx/Jit/hir/` 下的类型推断逻辑 |
| JIT栈模拟缺陷 | `stack_.empty()` 断言失败 | 修复 `cinderx/Jit/` 下的栈操作模拟 |
| JIT代码生成缺陷 | `emitAnyCall` abort | 修复 `cinderx/Jit/hir/HIRBuilder.cpp` |
| JIT帧行号追踪 | 行号断言失败 | 修复 `cinderx/Jit/` 下的帧信息维护 |
| AArch64后端缺陷 | AArch64 相关断言 | 修复 `cinderx/Jit/` 下的 AArch64 代码生成 |

## 注意事项

- 所有测试操作必须在 Linux 远程服务器上执行
- 逐文件运行隔离崩溃影响，但单文件内崩溃仍会导致该文件后续用例无法执行
- 已知崩溃文件（`test_jit_global_cache.py`、`test_arm_runtime.py`）默认跳过
- 修改代码后需先重新编译再验证
- 诊断完成后应清理本地临时结果文件
