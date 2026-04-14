---
name: "cinderx-build-test"
description: "执行cinderx的编译构建和功能测试。当用户需要编译、构建、测试cinderx项目时调用此技能。"
---

# CinderX 编译构建与功能测试

在远程 Linux 服务器上执行 CinderX 的编译构建和功能测试。通过 `remote-connector` 连接远程服务器执行所有操作。

## 配置

远程连接参数和路径配置在 `.trae/config.ini` 中，脚本启动时自动读取。关键字段：`server_ip`、`key_file`、`user`、`work_dir`、`upload_dir`、`remote_python`。

## 辅助脚本

- `.trae/scripts/build_test.ps1` — 主脚本，提供构建、测试等操作入口
- `.trae/scripts/remote.ps1` — 底层脚本，负责 SSH 连接、远程命令执行、文件上传/下载

## 操作与命令

| 操作 | 命令 | 说明 |
|------|------|------|
| 编译构建 | `-Action build` | 同步源码到远程并编译 |
| PGO/LTO构建 | `-Action build -EnablePGO -EnableLTO` | 带优化的构建 |
| 功能测试 | `-Action test [-TestFilter <expr>]` | 运行 pytest，`-TestFilter` 对应 pytest `-k` |
| 单用例测试 | `-Action test-single -TestPath <path>` | 运行单个用例，`-TestPath` 支持文件名自动查找和 `::` 语法定位到类/方法 |
| 构建并测试 | `-Action build-and-test [-TestFilter <expr>]` | 完整流水线：同步→编译→验证→测试 |
| 检查加载 | `-Action check` | 验证 CinderX 模块是否可正常加载 |
| 清理 | `-Action clean` | 删除远程构建目录 |

通用参数：`-VerboseOutput` 启用详细输出。

## 构建流程

1. **源码同步**：SCP 上传本地源码到远程 `upload_dir`
2. **编译构建**：`remote_python pip install --no-build-isolation -e .`（CMake 配置 + 编译生成 `_cinderx.so`）
3. **加载验证**：`remote_python` 导入 `cinderx` 模块检查初始化状态
4. **功能测试**：`remote_python` 运行 `cinderx/PythonLib/test_cinderx/` 下的 pytest 用例

## 注意事项

- CinderX 不支持 Windows，所有操作必须在 Linux 远程服务器上执行
- 首次构建需下载依赖（asmjit、fmt 等），耗时较长
- PGO 构建时间约为普通构建的 2-3 倍
- 测试失败后，调用 `cinderx-test-diagnose` 定位具体失败用例
