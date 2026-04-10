# 2026-02-27 CinderX `dump_elf` 机器架构字段修复（ARM）

## 背景
- 现象：在 ARM 主机上，`cinderjit.dump_elf()` 的输出用 `objdump -d` 反汇编时被识别为 `elf64-x86-64`。
- 根因假设：CinderX ELF 写入器头部默认 `e_machine` 被硬编码为 x86-64。
- 约束：所有测试/验证必须通过远端入口 `<远端测试入口>`（`ssh root@124.70.162.35`）。

## 头脑风暴
1. 最小修复：
   - 根据编译目标（`__aarch64__`、`__x86_64__`）设置 ELF 头 `machine`，而不是硬编码。
   - 其他布局/section 保持不变。
2. 安全性：
   - 在 x86 构建中保持原有行为。
   - 对未知架构直接编译失败，避免静默写出错误元数据。
3. 防回归：
   - 在 `dump_elf` 回归测试中读取 ELF 头 `e_machine`，并与运行时架构映射比对。

## TDD 计划
1. RED：
   - 在 `test_cinderjit.py` 新增 `dump_elf` 机器字段回归测试。
   - 在远端 ARM 上跑定向测试，修复前预期失败。
2. GREEN：
   - 在 ELF 头代码中实现架构感知的 `e_machine` 选择。
   - 远端 ARM 重跑定向测试，预期通过。
3. 额外验证：
   - `readelf -h` 显示 `Machine: AArch64`。
   - `objdump -d` 不再误识别为 x86。

## 远端验证命令
1. 定向 RED/GREEN 测试：
   - `ssh root@124.70.162.35 'cd /root/work/cinderx-main && /root/venv-cinderx314/bin/python -m unittest test_cinderx.test_cinderjit.CinderJitModuleTests.test_dump_elf_machine_matches_runtime_arch'`
2. 手工检查 ELF 头：
   - `ssh root@124.70.162.35 'readelf -h /tmp/<dumped>.elf | grep Machine'`
3. 手工检查反汇编：
   - `ssh root@124.70.162.35 'objdump -d /tmp/<dumped>.elf | head'`

## 预计改动文件
- `cinderx/Jit/elf/header.h`
- `cinderx/PythonLib/test_cinderx/test_cinderjit.py`
- `findings.md`
