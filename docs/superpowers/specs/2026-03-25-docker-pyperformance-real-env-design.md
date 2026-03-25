# Docker Pyperformance 真实环境对齐设计

## 概述

本设计的目标，是把当前基于 Docker 的 benchmark 验证流程调整为更接近真实服务器环境的形态，从而提高 CinderX JIT 正确性问题的复现率与诊断价值。

新的设计分为三层：

1. 环境层
   - Docker 基础镜像、编译器和系统依赖尽量对齐真实环境。
   - 容器内代理行为应与真实使用方式一致。

2. 配置层
   - benchmark 元数据继续保存在 `configs/<benchmark>/benchmark.toml`。
   - 新增 benchmark 仍应以配置变更为主，而不是改动通用脚本。

3. 执行层
   - 正式 benchmark 执行统一使用 `python -m pyperformance run`。
   - Docker 验证不再把直接调用 `bench(*args)` 作为主要正确性/性能验证路径。

本设计的核心目标是缩小以下两者之间的差距：

- 本地 Docker 验证路径
- 真实环境中 aggressive auto-JIT 暴露问题的执行路径

## 问题陈述

当前 Docker benchmark 基础设施虽然已经支持配置驱动的 benchmark 元数据，但执行链路仍然在两个关键点上偏离真实环境：

1. 环境本身还不够接近真实环境。
   - 真实服务器环境基于 `openEuler 24.03 LTS SP1`
   - 真实工具链使用 `gcc 14.2.0`
   - 代理在主机和容器中的行为不同，原先默认的 `127.0.0.1:7890` 在容器内并不成立

2. 执行入口没有覆盖真实 benchmark 路径。
   - 当前 Docker 脚本主要是直接导入 benchmark 模块并调用 `bench(*args)`
   - 但真实调查和真实故障发生在 `python -m pyperformance run` 路径下
   - 这条路径会额外引入 worker、启动阶段、stdlib/import 路径、benchmark 元数据采集等行为，而这些都与 aggressive auto-JIT 的正确性高度相关

因此，当前 Docker 验证很容易低估那些只会在真实 `pyperformance` 链路中暴露出来的 JIT 正确性问题。

## 目标

- 让 Docker 验证环境显著更贴近真实服务器环境
- 把 `python -m pyperformance run` 作为正式 benchmark 执行入口
- 保留并延续当前 benchmark 配置驱动的方向
- 尽量减少 benchmark-specific 逻辑在 shell 脚本中的散落
- 支持以下运行模式：
  - 单 benchmark
  - 指定子集，例如 `all,-dask`
  - 全量 benchmark

## 非目标

- 完全做到与真实生产服务器逐字节、逐行为一致
- 推翻现有 benchmark metadata 设计并从头重写
- 立刻删除所有现有 shell 脚本
- 在本设计阶段内单独解决所有 benchmark-specific 环境问题，例如 `dask`

## 设计方案

### 1. 环境层

Docker 镜像需要向真实服务器环境对齐，使 benchmark 执行环境在系统、工具链和网络行为上都更接近真实情况。

目标环境特征如下：

- 操作系统：`openEuler 24.03 LTS SP1`
- 编译器：`gcc 14.2.0`
- 容器访问主机代理：
  - `http_proxy=http://host.docker.internal:7890`
  - `https_proxy=http://host.docker.internal:7890`

环境层负责：

- 基础包管理器和系统依赖安装
- 编译器/工具链安装
- Python 运行与构建依赖准备
- 代理默认值与使用说明

环境层不负责 benchmark-specific 的适配逻辑。

### 2. 配置层

benchmark-specific 元数据继续放在：

- `docker/cinderx-test/configs/<benchmark>/benchmark.toml`
- `docker/cpython-baseline/configs/<benchmark>/benchmark.toml`

现有配置模型需要扩展，以便驱动真实 `pyperformance` 执行流。

每个 benchmark 配置至少应能描述：

- 对应的 pyperformance benchmark 名称
- 需要准备的 benchmark 文件
- benchmark 预处理方式
- 可选的 benchmark-specific 初始化行为
- 可选的默认排除项或环境说明

建议新增的配置字段包括：

- `pyperformance_benchmark`
- `prepare.mode`
- `prepare.support_files`
- `run.default_excludes`
- `run.extra_env`

目标仍然是：新增一个 benchmark 时，通常只需要新增：

- 一个 `benchmark.toml`
- 一个 `stable.env`

而不需要去改通用 shell 脚本。

### 3. 执行层

正式 benchmark 执行入口统一为：

```bash
python -m pyperformance run ...
```

这条路径将成为以下场景的正式执行方式：

- CinderX benchmark 执行
- stock CPython baseline 执行
- 对比运行

这意味着：

- `benchmark_harness.py` 不再以“直接导入 benchmark 并调用 `bench(*args)`”为主要职责
- shell wrapper 负责组装环境变量与 `pyperformance run` 参数
- 真正的 benchmark 执行交给 pyperformance 本身完成

这样做的价值在于：能够保留真实 worker/runner 执行模型，从而更真实地暴露 aggressive auto-JIT 的正确性问题。

## 职责调整

### benchmark_harness.py

保留的职责：

- 读取和校验配置
- 下载/同步 benchmark 文件
- 准备 benchmark 工作目录
- 生成面向 pyperformance 的元数据

不再作为主要职责的内容：

- 导入 benchmark 模块
- 直接调用 `bench(*args)`

也就是说，harness 将从“执行器”收缩为“准备器 + 命令组装辅助层”。

### Shell 脚本

shell 脚本保留为很薄的 orchestration wrapper：

- 准备环境
- 调用 harness 做 benchmark 预处理
- 执行 `python -m pyperformance run`
- 收集输出和结果文件

这些脚本不应再保存 benchmark-specific 结构知识，只负责选择 benchmark 与运行模式。

## 迁移策略

### 第一阶段：环境对齐

- 更新 Docker 镜像，使其向 openEuler + GCC 14.2.0 靠拢
- 把代理处理改为 `host.docker.internal`
- 在文档中明确主机/容器代理的使用约定

### 第二阶段：配置 schema 扩展

- 为 `benchmark.toml` 增加 pyperformance 相关字段
- 为新增字段补齐 harness 测试

### 第三阶段：harness 角色收缩

- 把 harness 从“直接执行 benchmark”调整为“准备 benchmark”
- 如有必要，保留 direct `bench(*args)` 路径作为诊断辅助路径，但不再作为正式验证入口

### 第四阶段：脚本迁移

- 把正式执行脚本统一改为 `python -m pyperformance run`
- 覆盖以下运行模式：
  - 单 benchmark
  - benchmark 子集
  - 全量运行

### 第五阶段：文档更新

- 更新两套 Docker 目录下的 README
- 明确说明：
  - 为什么要向真实环境对齐
  - 容器内代理如何配置
  - benchmark 预处理如何工作
  - 如何运行单用例 / 子集 / 全量 `pyperformance`

## 风险

### 风险一：Docker 仍与真实环境存在差距

即使切换到 openEuler 和 GCC 14.2.0，仍可能存在以下差异：

- 内核行为
- 权限模型
- 网络拓扑
- 文件系统布局

缓解方式：

- 把 Docker 视为更接近真实环境的近似，而不是完美复制品
- 在文档中明确记录当前已知差异

### 风险二：pyperformance 执行链更复杂

切换到 `pyperformance run` 之后，会引入更多系统行为：

- worker 进程行为
- 环境变量传播
- benchmark 元数据采集副作用

缓解方式：

- 让执行 wrapper 尽可能薄
- 保持 harness 只负责准备工作，不负责过多运行期逻辑

### 风险三：配置字段持续膨胀

如果 `benchmark.toml` 最终演化成一个隐式脚本语言，维护成本会迅速升高。

缓解方式：

- 把 `prepare.mode` 限制在少量受控模式中
- 优先使用明确 schema，而不是自由拼接脚本命令

## 成功标准

当满足以下条件时，可以认为这轮设计成功：

1. Docker benchmark 环境足够接近真实环境，能够更稳定地复现 aggressive auto-JIT 问题
2. 正式 Docker benchmark 执行统一使用 `python -m pyperformance run`
3. 支持单 benchmark、子集和全量运行
4. 新 benchmark 的接入仍以配置变更为主
5. 通用 shell 脚本不需要为了普通 benchmark 新增而持续修改

## 建议

建议按一轮集成改造推进，统一完成以下三件事：

- Docker 环境向真实服务器环境对齐
- benchmark 配置扩展为可驱动 pyperformance 执行
- 正式执行入口迁移到 `python -m pyperformance run`

这比“再补一套脚本”范围更大，但它直接针对了当前验证链路的根缺口，也就是：Docker 验证路径与真实环境执行路径差得太远，从而掩盖了 aggressive auto-JIT 的真实正确性问题。
