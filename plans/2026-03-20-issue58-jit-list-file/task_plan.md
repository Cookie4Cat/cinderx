# Task Plan: Issue 58 JIT list file whitespace and CRLF compatibility

## Goal
修复 `PYTHONJITLISTFILE` / `read_jit_list()` 读取 JIT list 文件时的跨平台和空白字符兼容性问题：

- Windows `\r\n` 文件在 Linux 上读取后，行尾 `\r` 不应导致匹配失败
- 尾随空格不应导致匹配失败
- 与注释/空行行为保持兼容

## Workflow
1. Brainstorming
2. Writing-Plans
3. Test-Driven-Development
4. Verification-Before-Completion

## Current understanding
- 实际解析在 `cinderx/Jit/jit_list.cpp`
- `parseFile()` 使用 `std::getline()`，Linux 下不会自动去掉 `\r`
- `parseLine()` 当前没有做 trim，但头文件注释已经声明：
  - `Leading and trailing whitespace is ignored`
- 所以当前实现与既有契约不一致

## Scope
- 只修 JIT list 文件行级解析
- 不改 JIT list 语法本身
- 不扩大到“分隔符两侧任意空白都合法”的更宽语法承诺

## TDD plan
- 补 Python 测试覆盖：
  - `read_jit_list()` 读取 CRLF 文件
  - `read_jit_list()` 读取尾随空格文件
  - 启动路径使用 `PYTHONJITLISTFILE` 时同样可工作
  - 前导空格 + 注释/空白行仍被忽略

## Verification plan
- 本地相关测试：
  - `test_read_jit_list`
  - 新增 issue58 相关测试
- 远端补充验证：
  - 统一入口 `scripts/arm/remote_update_build_test.sh`
  - 只跑 `test_jitlist.py` 的新增 issue58 子用例

## Status
- [completed] Brainstorming
- [completed] Writing-Plans
- [completed] Test-Driven-Development: 解析 trim 修复与两条回归测试已落地
- [completed] Verification-Before-Completion: 本机无 Python，已改用远端构建并跑新增两条 `JitListTest`，结果通过
