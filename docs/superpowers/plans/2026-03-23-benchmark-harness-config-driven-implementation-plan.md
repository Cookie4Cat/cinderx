# Benchmark Harness Config-Driven Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `docker/cinderx-test` 和 `docker/cpython-baseline` 的 benchmark 接入机制改成真正的配置驱动，使新增 benchmark 时只需新增配置文件而不需修改脚本。

**Architecture:** 先引入 `configs/<benchmark>/benchmark.toml` 作为 benchmark 适配层的唯一来源，再让两套 `benchmark_harness.py` 优先从配置读取元数据、下载清单和参数构造模式。shell 脚本继续只做 runner/orchestration，不再感知 benchmark 的结构差异。

**Tech Stack:** Python 3.14, shell scripts, TOML 配置解析, unittest

---

## 文件边界

### 核心实现文件

- 修改：`/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/benchmark_harness.py`
  - 负责 `cinderx-test` 侧配置解析、下载清单、模块加载、参数构造
- 修改：`/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/benchmark_harness.py`
  - 负责 `cpython-baseline` 侧配置解析、下载清单、模块加载、参数构造

### 配置文件

- 创建：`/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/configs/generators/benchmark.toml`
- 创建：`/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/configs/mdp/benchmark.toml`
- 创建：`/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/configs/regex_compile/benchmark.toml`
- 创建：`/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/configs/generators/benchmark.toml`
- 创建：`/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/configs/mdp/benchmark.toml`
- 创建：`/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/configs/regex_compile/benchmark.toml`

### 兼容性 shell 脚本

- 修改：`/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/setup.sh`
- 修改：`/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/bench-benchmark.sh`
- 修改：`/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/test-benchmark.sh`
- 修改：`/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test-baseline.sh`
- 修改：`/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test-cinderx.sh`
- 修改：`/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test-comparison.sh`

### 测试文件

- 修改：`/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/test_benchmark_harness.py`
- 修改：`/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test_benchmark_harness.py`

### 文档

- 视需要修改：`/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/README.md`
- 视需要修改：`/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/README.md`

## Chunk 1: 定义配置 schema 并让 harness 能读 TOML

### Task 1: 为两套 harness 补配置读取能力

**Files:**
- Modify: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/benchmark_harness.py`
- Modify: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/benchmark_harness.py`
- Test: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/test_benchmark_harness.py`
- Test: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test_benchmark_harness.py`

- [ ] **Step 1: 为 benchmark 配置解析写失败测试**

在两套 `test_benchmark_harness.py` 中新增测试，至少覆盖：
- 能从 `configs/<benchmark>/benchmark.toml` 解析：
  - `name`
  - `module_dir`
  - `entry_file`
  - `bench_func`
  - `downloads`
  - `args.mode`
- 配置缺失关键字段时抛出清晰异常

- [ ] **Step 2: 运行失败测试确认当前还不支持 TOML**

Run:
```bash
python3 -m unittest docker.cinderx-test.scripts.test_benchmark_harness
python3 -m unittest docker.cpython-baseline.scripts.test_benchmark_harness
```

Expected:
- 新增的 TOML 解析测试失败

- [ ] **Step 3: 在两套 harness 中实现通用配置读取**

实现最小能力：
- 增加 `load_benchmark_config(config_root, benchmark_name)`
- 解析 `benchmark.toml`
- 返回统一结构

要求：
- 不删除现有逻辑
- 先让“读取配置”能力存在即可

- [ ] **Step 4: 重新运行测试确认配置读取通过**

Run:
```bash
python3 -m unittest docker.cinderx-test.scripts.test_benchmark_harness
python3 -m unittest docker.cpython-baseline.scripts.test_benchmark_harness
```

Expected:
- 配置解析测试通过

- [ ] **Step 5: 提交**

```bash
git add \
  docker/cinderx-test/scripts/benchmark_harness.py \
  docker/cpython-baseline/scripts/benchmark_harness.py \
  docker/cinderx-test/scripts/test_benchmark_harness.py \
  docker/cpython-baseline/scripts/test_benchmark_harness.py
git commit -m "docker: add benchmark toml parsing to harness"
```

### Task 2: 补齐三个 benchmark 的 benchmark.toml

**Files:**
- Create: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/configs/generators/benchmark.toml`
- Create: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/configs/mdp/benchmark.toml`
- Create: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/configs/regex_compile/benchmark.toml`
- Create: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/configs/generators/benchmark.toml`
- Create: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/configs/mdp/benchmark.toml`
- Create: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/configs/regex_compile/benchmark.toml`
- Test: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/test_benchmark_harness.py`
- Test: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test_benchmark_harness.py`

- [ ] **Step 1: 先写配置存在性和字段完整性的失败测试**

测试应验证：
- 三个 benchmark 都有 `benchmark.toml`
- 关键字段齐全
- `regex_compile` 包含 support files 和 `regex_compile_capture` 模式

- [ ] **Step 2: 运行测试确认当前 benchmark.toml 缺失**

Run:
```bash
python3 -m unittest docker.cinderx-test.scripts.test_benchmark_harness
python3 -m unittest docker.cpython-baseline.scripts.test_benchmark_harness
```

Expected:
- benchmark.toml 相关测试失败

- [ ] **Step 3: 新建六个 benchmark.toml**

要求：
- 两套目录的 schema 一致
- 内容与当前脚本行为等价
- 不引入 experiment-only 配置

- [ ] **Step 4: 重新运行测试确认配置文件可用**

Run:
```bash
python3 -m unittest docker.cinderx-test.scripts.test_benchmark_harness
python3 -m unittest docker.cpython-baseline.scripts.test_benchmark_harness
```

Expected:
- 三个 benchmark 的配置存在性和字段测试通过

- [ ] **Step 5: 提交**

```bash
git add \
  docker/cinderx-test/configs/generators/benchmark.toml \
  docker/cinderx-test/configs/mdp/benchmark.toml \
  docker/cinderx-test/configs/regex_compile/benchmark.toml \
  docker/cpython-baseline/configs/generators/benchmark.toml \
  docker/cpython-baseline/configs/mdp/benchmark.toml \
  docker/cpython-baseline/configs/regex_compile/benchmark.toml
git commit -m "docker: add benchmark metadata configs"
```

## Chunk 2: 让下载、模块加载、参数构造优先走配置

### Task 3: 用配置驱动下载与模块路径

**Files:**
- Modify: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/benchmark_harness.py`
- Modify: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/benchmark_harness.py`
- Modify: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/setup.sh`
- Modify: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test-comparison.sh`
- Test: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/test_benchmark_harness.py`
- Test: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test_benchmark_harness.py`

- [ ] **Step 1: 写失败测试覆盖配置驱动下载清单**

至少覆盖：
- `benchmark_downloads()` 来自 `benchmark.toml`
- `benchmark_module_path()` 使用 `module_dir + entry_file`

- [ ] **Step 2: 运行测试确认当前仍依赖内置名单**

Run:
```bash
python3 -m unittest docker.cinderx-test.scripts.test_benchmark_harness
python3 -m unittest docker.cpython-baseline.scripts.test_benchmark_harness
```

Expected:
- 新增测试失败

- [ ] **Step 3: 修改 harness 与调用脚本，让下载和模块定位优先读配置**

要求：
- shell 只传 benchmark 名
- 下载和模块路径完全来自 `benchmark.toml`

- [ ] **Step 4: 运行测试与脚本语法检查**

Run:
```bash
python3 -m unittest docker.cinderx-test.scripts.test_benchmark_harness
python3 -m unittest docker.cpython-baseline.scripts.test_benchmark_harness
bash -n docker/cinderx-test/scripts/setup.sh
bash -n docker/cpython-baseline/scripts/test-comparison.sh
```

Expected:
- 全部通过

- [ ] **Step 5: 提交**

```bash
git add \
  docker/cinderx-test/scripts/benchmark_harness.py \
  docker/cpython-baseline/scripts/benchmark_harness.py \
  docker/cinderx-test/scripts/setup.sh \
  docker/cpython-baseline/scripts/test-comparison.sh \
  docker/cinderx-test/scripts/test_benchmark_harness.py \
  docker/cpython-baseline/scripts/test_benchmark_harness.py
git commit -m "docker: load benchmark downloads from config"
```

### Task 4: 用配置驱动参数构造

**Files:**
- Modify: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/benchmark_harness.py`
- Modify: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/benchmark_harness.py`
- Test: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/test_benchmark_harness.py`
- Test: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test_benchmark_harness.py`

- [ ] **Step 1: 为 args.mode 写失败测试**

至少覆盖三种模式：
- `fixed_tuple`
- `regex_compile_capture`
- `module_helper`（即使当前 benchmark 未使用，也要把接口测试补上）

- [ ] **Step 2: 运行测试确认当前 bench_args 仍有 benchmark-specific 分支**

Run:
```bash
python3 -m unittest docker.cinderx-test.scripts.test_benchmark_harness
python3 -m unittest docker.cpython-baseline.scripts.test_benchmark_harness
```

Expected:
- 新增 args.mode 测试失败

- [ ] **Step 3: 实现 resolve_bench_args(module, config)**

要求：
- 不再按 benchmark 名称分支
- 只按 `args.mode` 分发

- [ ] **Step 4: 重新运行测试确认三种模式都可用**

Run:
```bash
python3 -m unittest docker.cinderx-test.scripts.test_benchmark_harness
python3 -m unittest docker.cpython-baseline.scripts.test_benchmark_harness
```

Expected:
- args.mode 相关测试通过

- [ ] **Step 5: 提交**

```bash
git add \
  docker/cinderx-test/scripts/benchmark_harness.py \
  docker/cpython-baseline/scripts/benchmark_harness.py \
  docker/cinderx-test/scripts/test_benchmark_harness.py \
  docker/cpython-baseline/scripts/test_benchmark_harness.py
git commit -m "docker: resolve benchmark args from config"
```

## Chunk 3: 收掉内置 benchmark 名单并做 runner 回归

### Task 5: 删除 BENCHMARK_SPECS 和 benchmark-specific 特判

**Files:**
- Modify: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/benchmark_harness.py`
- Modify: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/benchmark_harness.py`
- Test: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/test_benchmark_harness.py`
- Test: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test_benchmark_harness.py`

- [ ] **Step 1: 先写测试，保证新增 benchmark 不需要改脚本名单**

思路：
- 用临时目录构造一个新的 benchmark config
- 证明 harness 可在未知 benchmark 名下正常解析配置

- [ ] **Step 2: 运行测试确认当前仍依赖内置名单**

Run:
```bash
python3 -m unittest docker.cinderx-test.scripts.test_benchmark_harness
python3 -m unittest docker.cpython-baseline.scripts.test_benchmark_harness
```

Expected:
- 新增“未知 benchmark 但有配置”测试失败

- [ ] **Step 3: 删除 BENCHMARK_SPECS 和按 benchmark 名称写死的特判**

要求：
- benchmark 是否受支持，只由配置是否存在决定

- [ ] **Step 4: 重新运行测试确认名单已真正移除**

Run:
```bash
python3 -m unittest docker.cinderx-test.scripts.test_benchmark_harness
python3 -m unittest docker.cpython-baseline.scripts.test_benchmark_harness
```

Expected:
- 全部通过

- [ ] **Step 5: 提交**

```bash
git add \
  docker/cinderx-test/scripts/benchmark_harness.py \
  docker/cpython-baseline/scripts/benchmark_harness.py \
  docker/cinderx-test/scripts/test_benchmark_harness.py \
  docker/cpython-baseline/scripts/test_benchmark_harness.py
git commit -m "docker: remove hardcoded benchmark registry"
```

### Task 6: 回归 runner 脚本和 README

**Files:**
- Modify: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/bench-benchmark.sh`
- Modify: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/test-benchmark.sh`
- Modify: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test-baseline.sh`
- Modify: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test-cinderx.sh`
- Modify: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test-comparison.sh`
- Modify: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/README.md`
- Modify: `/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/README.md`

- [ ] **Step 1: 让 README 与新配置驱动模型保持一致**

至少说明：
- benchmark 元数据来自 `benchmark.toml`
- 新增 benchmark 只需新增配置文件

- [ ] **Step 2: 跑脚本语法检查**

Run:
```bash
bash -n docker/cinderx-test/scripts/bench-benchmark.sh
bash -n docker/cinderx-test/scripts/test-benchmark.sh
bash -n docker/cpython-baseline/scripts/test-baseline.sh
bash -n docker/cpython-baseline/scripts/test-cinderx.sh
bash -n docker/cpython-baseline/scripts/test-comparison.sh
```

Expected:
- 全部通过

- [ ] **Step 3: 跑最终 harness 单测**

Run:
```bash
python3 -m unittest docker.cinderx-test.scripts.test_benchmark_harness
python3 -m unittest docker.cpython-baseline.scripts.test_benchmark_harness
```

Expected:
- 全部通过

- [ ] **Step 4: 提交**

```bash
git add \
  docker/cinderx-test/scripts/bench-benchmark.sh \
  docker/cinderx-test/scripts/test-benchmark.sh \
  docker/cpython-baseline/scripts/test-baseline.sh \
  docker/cpython-baseline/scripts/test-cinderx.sh \
  docker/cpython-baseline/scripts/test-comparison.sh \
  docker/cinderx-test/README.md \
  docker/cpython-baseline/README.md
git commit -m "docs: document config-driven benchmark harness"
```

## 最终验收

- [ ] `docker/cinderx-test` 与 `docker/cpython-baseline` 都能从 `benchmark.toml` 读取 benchmark 元数据
- [ ] 三个已有 benchmark：
  - `generators`
  - `mdp`
  - `regex_compile`
  在新机制下行为与旧机制保持一致
- [ ] 新增 benchmark 时不需要修改 shell 脚本
- [ ] 新增 benchmark 时不需要修改 Python harness 中的 benchmark 名单
- [ ] README 已明确说明新增 benchmark 的最小改动面

Plan complete and saved to `docs/superpowers/plans/2026-03-23-benchmark-harness-config-driven-implementation-plan.md`. Ready to execute?
