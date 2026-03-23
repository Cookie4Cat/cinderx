# Docker Benchmark Harness 配置驱动设计

## 1. 目标

本设计的目标是把当前 Docker benchmark 验证基础设施收敛成：

- 新增 benchmark 时只改配置，不改脚本
- shell 脚本只做 runner / orchestration
- benchmark 适配层完全外置到配置文件

覆盖范围包括两套现有基础设施：

- `docker/cinderx-test`
- `docker/cpython-baseline`

最终希望达到的使用体验是：

1. 新增一个 benchmark
2. 只新增：
   - `configs/<benchmark>/benchmark.toml`
   - `configs/<benchmark>/stable.env`
3. 不修改 shell 脚本
4. 不修改 Python harness 中的 benchmark 名单或 benchmark 特判逻辑

## 2. 背景与当前问题

当前这两套 Docker 基础设施虽然已经初步支持：

- `generators`
- `mdp`
- `regex_compile`

但新增 benchmark 仍然做不到“只改配置”，原因是 benchmark 的结构知识仍然散落在脚本代码里：

1. benchmark 元数据写死在 `BENCHMARK_SPECS`
   - benchmark 名称
   - `module_dir`
   - `bench_func`
   - `support_files`
   - 下载 URL

2. benchmark 参数构造逻辑写死在 `bench_args()`
   - `regex_compile` 需要先 `capture_regexes()`，这类逻辑现在是代码特判

3. benchmark 下载逻辑仍依赖代码里的结构知识
   - 哪些 benchmark 只有 `run_benchmark.py`
   - 哪些还需要额外 support files

因此当前状态是：

- 新增 benchmark 时不需要改 shell 脚本
- 但仍然必须改 Python harness

这还不满足“新增 benchmark 只改配置”的目标。

## 3. 设计原则

这轮设计遵循以下原则：

1. shell 脚本不懂 benchmark 结构
   - 只知道 benchmark 名称
   - 只负责调用通用 runner

2. benchmark 适配知识全部外置
   - benchmark 文件布局
   - 下载地址
   - 入口函数
   - 参数构造方式
   - 都由配置定义

3. Python harness 只保留通用能力
   - 读配置
   - 下载文件
   - 加载模块
   - 调通用参数解析器

4. 先统一 schema，再考虑代码共享
   - `docker/cinderx-test` 与 `docker/cpython-baseline` 可以先保留两份 harness
   - 但配置 schema、目录结构和行为必须一致

5. 第一版只解决当前需要的问题
   - 不做过度通用的 mini DSL
   - 只支持已经在仓库里出现过的 benchmark 形状

## 4. 目标架构

### 4.1 目录结构

每个 benchmark 目录下至少包含：

```text
configs/
  <benchmark>/
    benchmark.toml
    stable.env
```

例如：

```text
docker/cinderx-test/configs/generators/benchmark.toml
docker/cinderx-test/configs/generators/stable.env

docker/cinderx-test/configs/mdp/benchmark.toml
docker/cinderx-test/configs/mdp/stable.env

docker/cinderx-test/configs/regex_compile/benchmark.toml
docker/cinderx-test/configs/regex_compile/stable.env
```

`docker/cpython-baseline` 保持同样结构。

### 4.2 职责划分

#### shell 脚本

shell 脚本只做：

- 读取 benchmark 名
- 定位配置目录
- 调 Python harness
- 组织 baseline / optimized 比较
- 写结果文件

shell 脚本不再做：

- benchmark 名单维护
- benchmark 结构判断
- benchmark 特判

#### benchmark_harness.py

Python harness 只做：

- 读取 `benchmark.toml`
- 解析 benchmark 元数据
- 下载 benchmark 文件
- 动态加载 benchmark 模块
- 根据配置解析 bench 参数
- 生成结果路径

Python harness 不再做：

- 内置 `BENCHMARK_SPECS`
- 对具体 benchmark 名写分支

#### 配置文件

`benchmark.toml` 负责承载 benchmark 适配知识：

- benchmark 的源码布局
- 下载清单
- bench 入口函数
- bench 参数构造方式

## 5. benchmark.toml 设计

### 5.1 第一版字段

第一版建议支持这些字段：

```toml
name = "regex_compile"
module_dir = "bm_regex_compile"
entry_file = "run_benchmark.py"
bench_func = "bench_regex_compile"

support_files = [
  "bm_regex_effbot.py",
  "bm_regex_v8.py",
]

[[downloads]]
target = "run_benchmark.py"
url = "https://..."

[[downloads]]
target = "bm_regex_effbot.py"
url = "https://..."

[[downloads]]
target = "bm_regex_v8.py"
url = "https://..."

[args]
mode = "regex_compile_capture"
fixed_int = 1
```

`stable.env` 保留现有职责：

- 只负责优化开关
- 不负责 benchmark 元数据

### 5.2 参数模式设计

第一版不做任意 Python 表达式求值，而是只支持少量受控模式。

建议支持：

#### `fixed_tuple`

适用场景：

- `bench_generators(1)`
- `bench_mdp(1)`

示例：

```toml
[args]
mode = "fixed_tuple"
values = [1]
```

#### `regex_compile_capture`

适用场景：

- `bench_regex_compile(1, regexes)`

行为：

- 先调用模块内的 `capture_regexes()`
- 再构造 `(fixed_int, regexes)`

示例：

```toml
[args]
mode = "regex_compile_capture"
fixed_int = 1
capture_func = "capture_regexes"
```

#### `module_helper`

适用场景：

- benchmark 模块内已经有专门 helper 可返回完整参数

行为：

- 调用模块内某个 helper
- helper 返回 `tuple`

示例：

```toml
[args]
mode = "module_helper"
helper = "build_bench_args"
```

### 5.3 为什么不直接支持任意代码

第一版不建议把参数构造设计成“配置里写任意 Python 代码”，原因是：

- 容易失去可维护性
- review 成本高
- 容易重新把适配逻辑藏回不透明的配置里

先用少量稳定模式覆盖当前实际需求，更容易长期维护。

## 6. 通用接口设计

建议两套 harness 都收敛到下面这组接口：

### 6.1 配置读取

- `load_benchmark_config(config_root, benchmark_name)`

返回统一结构对象，例如：

- `name`
- `module_dir`
- `entry_file`
- `bench_func`
- `downloads`
- `support_files`
- `args`

### 6.2 文件下载

- `benchmark_downloads(config)`
- `download_benchmark_files(config, benchmark_root)`

行为：

- 完全以配置中的 `downloads` 为准
- 不再从代码里推导 URL 或 support files

### 6.3 模块加载

- `load_benchmark_module(config, benchmark_root)`

行为：

- 使用 `module_dir + entry_file`
- 临时把 benchmark 目录加入 `sys.path`
- 加载完成后恢复

### 6.4 参数解析

- `resolve_bench_args(module, config)`

行为：

- 按 `args.mode` 分发到通用参数构造器
- 不再按 benchmark 名称分支

### 6.5 结果路径

继续保留现有逻辑：

- `results/<benchmark>/<config-name>/comparison.json`

这一部分已经比较合理，不需要在本轮大改。

## 7. 两套 Docker 的统一策略

### 7.1 需要统一的部分

以下内容必须在两套目录下保持一致：

- `configs/<benchmark>/benchmark.toml` schema
- `stable.env` 的位置和含义
- benchmark 名称
- 参数模式语义
- 结果目录结构

### 7.2 暂不强求共享代码

本轮不强制抽一个跨目录共享的 Python 模块，原因是：

- 当前主要目标是“新增 benchmark 只改配置”
- 不是“立刻消灭重复代码”

只要两边：

- schema 一致
- 行为一致
- 测试一致

就已经满足本轮目标。

后续如果 schema 稳定且重复逻辑明显，再考虑抽到共享位置。

## 8. 迁移策略

### 第一阶段：引入 benchmark.toml

对现有 benchmark 全部补齐：

- `generators`
- `mdp`
- `regex_compile`

目标：

- 配置和当前行为等价
- 现有 benchmark 结果不变

### 第二阶段：让 harness 先“优先读配置”

实现策略建议：

- 先保留现有代码路径作为兜底
- 当 `benchmark.toml` 存在时，优先走配置

这样迁移期更安全，也便于逐个 benchmark 校验。

### 第三阶段：删除内置 benchmark 名单

等三个现有 benchmark 都验证通过后，再删除：

- `BENCHMARK_SPECS`
- 按 benchmark 名称写死的 `bench_args()` 特判

这一步完成后，才算真正达到目标。

## 9. 测试策略

本轮基础设施改动需要补三类测试：

### 9.1 配置解析测试

验证：

- `benchmark.toml` 能正确解析
- 缺字段时能报清晰错误
- 参数模式能正确分发

### 9.2 兼容性测试

对 `generators` / `mdp` / `regex_compile` 三个 benchmark 分别验证：

- 下载清单正确
- 模块路径正确
- 参数构造结果正确

### 9.3 shell runner 集成测试

验证：

- `bench-benchmark.sh`
- `test-benchmark.sh`
- `test-baseline.sh`
- `test-cinderx.sh`
- `test-comparison.sh`

在“只给 benchmark 名”的前提下仍能正常工作。

## 10. 成功标准

本轮设计视为成功，当且仅当最终实现满足：

1. 新增 benchmark 时不修改 shell 脚本
2. 新增 benchmark 时不修改 Python harness 中的 benchmark 名单
3. 只新增：
   - `configs/<benchmark>/benchmark.toml`
   - `configs/<benchmark>/stable.env`
4. 当前已有 benchmark：
   - `generators`
   - `mdp`
   - `regex_compile`
   都能在新机制下保持原有行为

## 11. 当前建议

建议下一步按这个顺序推进：

1. 写实现计划
2. 先做 `benchmark.toml` schema 与解析层
3. 再迁移三条现有 benchmark 配置
4. 最后收掉 `BENCHMARK_SPECS` 与 benchmark-specific 特判

这会把 Docker benchmark 基础设施从“半配置驱动”收敛成真正的“配置驱动”。
