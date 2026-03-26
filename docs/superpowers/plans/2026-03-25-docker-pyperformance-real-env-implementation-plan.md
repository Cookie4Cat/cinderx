# Docker Pyperformance 真实环境对齐实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Docker benchmark 验证链路对齐到更接近真实服务器环境的形态，并把正式执行入口统一迁移到 `python -m pyperformance run`。

**Architecture:** 先收敛环境层，保证容器镜像、编译器和代理行为尽量贴近真实环境；再扩展配置层，让 `benchmark.toml` 能驱动 pyperformance 准备流程；最后把现有 shell/harness 执行链路收缩为“准备 benchmark + 调 pyperformance run”的薄封装。

**Tech Stack:** Docker、docker compose、openEuler、GCC 14.2.0、Python 3.14、pyperformance、shell 脚本、配置驱动 benchmark harness

---

## 文件职责梳理

### 需要修改的现有文件

- [docker/cpython-baseline/Dockerfile](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/Dockerfile)
  - 调整基础镜像、系统依赖和编译器，使环境更接近真实服务器
- [docker/cinderx-test/docker-compose.yml](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/docker-compose.yml)
  - 统一代理和容器运行环境
- [docker/cpython-baseline/docker-compose.yml](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/docker-compose.yml)
  - 统一代理和容器运行环境
- [docker/cinderx-test/scripts/benchmark_harness.py](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/benchmark_harness.py)
  - 从直接执行 benchmark 退化成准备层与 pyperformance 参数辅助层
- [docker/cpython-baseline/scripts/benchmark_harness.py](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/benchmark_harness.py)
  - 从直接执行 benchmark 退化成准备层与 pyperformance 参数辅助层
- [docker/cinderx-test/scripts/test-benchmark.sh](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/test-benchmark.sh)
  - 改成单 benchmark 的 pyperformance 正式入口
- [docker/cpython-baseline/scripts/test-baseline.sh](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test-baseline.sh)
  - 改成 stock CPython baseline 的 pyperformance 正式入口
- [docker/cpython-baseline/scripts/test-cinderx.sh](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test-cinderx.sh)
  - 改成 CinderX 版本的 pyperformance 正式入口
- [docker/cpython-baseline/scripts/test-comparison.sh](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test-comparison.sh)
  - 改成基于 pyperformance 结果文件的对比入口
- [docker/cinderx-test/scripts/test_benchmark_harness.py](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/test_benchmark_harness.py)
  - 补 schema 与准备逻辑测试
- [docker/cpython-baseline/scripts/test_benchmark_harness.py](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test_benchmark_harness.py)
  - 补 schema 与准备逻辑测试
- [docker/cinderx-test/README.md](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/README.md)
  - 更新真实环境对齐与 pyperformance 使用说明
- [docker/cpython-baseline/README.md](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/README.md)
  - 更新真实环境对齐与 pyperformance 使用说明

### 需要修改的配置文件

- [docker/cinderx-test/configs/generators/benchmark.toml](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/configs/generators/benchmark.toml)
- [docker/cinderx-test/configs/mdp/benchmark.toml](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/configs/mdp/benchmark.toml)
- [docker/cinderx-test/configs/regex_compile/benchmark.toml](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/configs/regex_compile/benchmark.toml)
- [docker/cpython-baseline/configs/generators/benchmark.toml](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/configs/generators/benchmark.toml)
- [docker/cpython-baseline/configs/mdp/benchmark.toml](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/configs/mdp/benchmark.toml)
- [docker/cpython-baseline/configs/regex_compile/benchmark.toml](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/configs/regex_compile/benchmark.toml)
  - 为 pyperformance 执行新增字段，例如 benchmark 名、准备模式、支持文件与默认排除项

## Chunk 1: 环境层对齐

### Task 1: 收敛真实环境差异并固化为容器配置

**Files:**
- Modify: [docker/cpython-baseline/Dockerfile](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/Dockerfile)
- Modify: [docker/cinderx-test/docker-compose.yml](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/docker-compose.yml)
- Modify: [docker/cpython-baseline/docker-compose.yml](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/docker-compose.yml)
- Test: 本地 `docker compose config`

- [ ] **步骤 1：写出环境层目标差异检查清单**

在计划执行时，先确认并记录以下差异：
- 当前镜像是否为 Debian/Ubuntu 系
- 当前编译器是否不是 GCC 14.2.0
- 当前代理是否仍使用 `127.0.0.1:7890`

预期结果：
- 得到一份明确的差异列表，支撑后续镜像与 compose 调整

- [ ] **步骤 2：调整 Dockerfile 到真实环境目标**

修改 [docker/cpython-baseline/Dockerfile](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/Dockerfile)，使其：
- 尽量对齐 `openEuler 24.03 LTS SP1`
- 安装 GCC 14.2.0 及相关依赖
- 保留当前验证所需 Python/构建依赖

要求：
- 不在这一阶段同时改 benchmark 执行脚本
- 只关注镜像环境本身

- [ ] **步骤 3：统一 compose 中的代理行为**

修改两套 compose 文件：
- [docker/cinderx-test/docker-compose.yml](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/docker-compose.yml)
- [docker/cpython-baseline/docker-compose.yml](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/docker-compose.yml)

把容器代理入口统一为：
- `http://host.docker.internal:7890`
- `https://host.docker.internal:7890`

并确保：
- 不再默认使用 `127.0.0.1:7890`

- [ ] **步骤 4：验证 compose 配置可解析**

Run:
```bash
docker compose -f docker/cinderx-test/docker-compose.yml config
docker compose -f docker/cpython-baseline/docker-compose.yml config
```

Expected:
- 两条命令都成功
- 输出中能看到新的代理环境变量

- [ ] **步骤 5：提交环境层改动**

```bash
git add \
  docker/cpython-baseline/Dockerfile \
  docker/cinderx-test/docker-compose.yml \
  docker/cpython-baseline/docker-compose.yml
git commit -m "docker: align benchmark containers with real environment"
```

## Chunk 2: 配置层扩展

### Task 2: 扩展 benchmark.toml 以驱动 pyperformance 执行

**Files:**
- Modify: [docker/cinderx-test/scripts/benchmark_harness.py](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/benchmark_harness.py)
- Modify: [docker/cpython-baseline/scripts/benchmark_harness.py](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/benchmark_harness.py)
- Modify: 六个 `benchmark.toml`
- Test: 两边的 [test_benchmark_harness.py](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/test_benchmark_harness.py)

- [ ] **步骤 1：为配置 schema 写失败测试**

在两边的 `test_benchmark_harness.py` 里新增失败测试，覆盖：
- `pyperformance_benchmark`
- `prepare.mode`
- `prepare.support_files`
- `run.default_excludes`
- `run.extra_env`

Run:
```bash
python3 -m unittest \
  docker.cinderx-test.scripts.test_benchmark_harness \
  docker.cpython-baseline.scripts.test_benchmark_harness
```

Expected:
- 新增测试先失败
- 失败原因是 schema/解析能力尚未实现

- [ ] **步骤 2：实现新 schema 解析**

修改两边的 [benchmark_harness.py](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/benchmark_harness.py)，新增：
- pyperformance benchmark 名解析
- benchmark 准备模式解析
- 默认排除项解析
- 额外环境变量解析

要求：
- 不在这一步执行 benchmark
- 只补解析与校验能力

- [ ] **步骤 3：更新现有三个 benchmark 的配置**

为以下 benchmark 的两个目录版本都补齐新字段：
- `generators`
- `mdp`
- `regex_compile`

确保配置能表达：
- pyperformance benchmark 名
- 支撑文件
- 准备模式
- 是否需要默认排除项

- [ ] **步骤 4：验证 harness 测试通过**

Run:
```bash
python3 -m unittest \
  docker.cinderx-test.scripts.test_benchmark_harness \
  docker.cpython-baseline.scripts.test_benchmark_harness
```

Expected:
- 新旧测试全部通过

- [ ] **步骤 5：提交配置层改动**

```bash
git add \
  docker/cinderx-test/scripts/benchmark_harness.py \
  docker/cpython-baseline/scripts/benchmark_harness.py \
  docker/cinderx-test/scripts/test_benchmark_harness.py \
  docker/cpython-baseline/scripts/test_benchmark_harness.py \
  docker/cinderx-test/configs/generators/benchmark.toml \
  docker/cinderx-test/configs/mdp/benchmark.toml \
  docker/cinderx-test/configs/regex_compile/benchmark.toml \
  docker/cpython-baseline/configs/generators/benchmark.toml \
  docker/cpython-baseline/configs/mdp/benchmark.toml \
  docker/cpython-baseline/configs/regex_compile/benchmark.toml
git commit -m "docker: extend benchmark configs for pyperformance runs"
```

## Chunk 3: 执行层迁移

### Task 3: 把正式入口统一切到 pyperformance run

**Files:**
- Modify: [docker/cinderx-test/scripts/test-benchmark.sh](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/test-benchmark.sh)
- Modify: [docker/cpython-baseline/scripts/test-baseline.sh](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test-baseline.sh)
- Modify: [docker/cpython-baseline/scripts/test-cinderx.sh](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test-cinderx.sh)
- Modify: [docker/cpython-baseline/scripts/test-comparison.sh](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test-comparison.sh)
- Modify: [docker/cinderx-test/README.md](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/README.md)
- Modify: [docker/cpython-baseline/README.md](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/README.md)

- [ ] **步骤 1：先为 shell 入口写最小回归测试或语法验证脚本**

至少保证以下脚本继续满足：
- `bash -n`
- benchmark 名称通过配置解析
- 能组装出 `pyperformance run` 命令

Run:
```bash
bash -n docker/cinderx-test/scripts/test-benchmark.sh
bash -n docker/cpython-baseline/scripts/test-baseline.sh
bash -n docker/cpython-baseline/scripts/test-cinderx.sh
bash -n docker/cpython-baseline/scripts/test-comparison.sh
```

Expected:
- 语法全部通过

- [ ] **步骤 2：把 cinderx-test 的单 benchmark 入口切到 pyperformance**

修改 [test-benchmark.sh](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/test-benchmark.sh)，使其：
- 通过 harness 完成 benchmark 准备
- 最终执行 `python -m pyperformance run -b <benchmark>`
- 支持环境变量控制 benchmark 名、warmup、samples 等参数

- [ ] **步骤 3：把 baseline/cinderx/comparison 三条入口都切到 pyperformance**

分别修改：
- [test-baseline.sh](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test-baseline.sh)
- [test-cinderx.sh](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test-cinderx.sh)
- [test-comparison.sh](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test-comparison.sh)

要求：
- 单 benchmark 与子集 benchmark 都能运行
- comparison 直接消费 pyperformance 结果文件，而不是 direct bench 结果

- [ ] **步骤 4：验证典型入口**

至少验证以下命令能正常启动：
```bash
docker compose -f docker/cinderx-test/docker-compose.yml run --rm cinderx-test /scripts/test-benchmark.sh
docker compose -f docker/cpython-baseline/docker-compose.yml run --rm cpython-baseline /scripts/test-baseline.sh
docker compose -f docker/cpython-baseline/docker-compose.yml run --rm cpython-baseline /scripts/test-cinderx.sh
```

Expected:
- benchmark 能走到 `python -m pyperformance run`
- 不再走 direct `bench(*args)` 正式路径

- [ ] **步骤 5：更新 README**

更新两份 README，明确写出：
- 真实环境对齐目标
- 代理使用 `host.docker.internal`
- 单 benchmark 运行方式
- `all,-dask` 子集运行方式
- 全量运行方式

- [ ] **步骤 6：提交执行层改动**

```bash
git add \
  docker/cinderx-test/scripts/test-benchmark.sh \
  docker/cpython-baseline/scripts/test-baseline.sh \
  docker/cpython-baseline/scripts/test-cinderx.sh \
  docker/cpython-baseline/scripts/test-comparison.sh \
  docker/cinderx-test/README.md \
  docker/cpython-baseline/README.md
git commit -m "docker: run formal benchmark validation via pyperformance"
```

## Chunk 4: 最终收口验证

### Task 4: 用真实路径验证这套改造

**Files:**
- 不新增代码
- 使用前面各任务产物完成集成验证

- [ ] **步骤 1：验证单 benchmark**

建议至少验证：
- `mdp`
- `regex_compile`

Expected:
- 能通过 Docker 正常启动 `pyperformance run`

- [ ] **步骤 2：验证 benchmark 子集**

Run 一个接近真实环境的子集，例如：
- `all,-dask`

Expected:
- 能跑通到结果收集阶段
- 若失败，失败点应来自 benchmark/环境本身，而不是旧的 direct bench 执行路径

- [ ] **步骤 3：记录已知偏差**

把这轮验证里仍然存在但不属于本次设计直接解决范围的问题记录下来，例如：
- `dask` 环境连通性
- 某些 benchmark 权限限制

- [ ] **步骤 4：提交最终收口说明**

如果需要补 README 或说明文档，再单独提交：

```bash
git add ...
git commit -m "docs: document docker pyperformance validation workflow"
```

Plan complete and saved to `docs/superpowers/plans/2026-03-25-docker-pyperformance-real-env-implementation-plan.md`. Ready to execute?

## 后续代办

- 方案 B：为 CinderX wheel cache 增加自动失效策略。
- Docker 功能测试流程约束：
  - 必须先开启 HIR dump 确认功能正常。
  - 再关闭 HIR dump 跑正式性能测试。
  - 不允许直接使用开启 dump 的结果做性能比较。
- 候选方向：
  - 基于 `/cinderx` 工作树的 commit hash 或源码摘要命名 wheel。
  - 运行脚本在复用前校验 cache 是否与当前源码一致，不一致时提示重新执行 setup。
  - setup 阶段生成 manifest，记录源码版本、Python 版本和构建参数，供运行脚本校验。
