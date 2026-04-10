# CinderX ARM64 Docker Test Environment

这个目录用于日常实验型容器测试。它与 `docker/cpython-baseline` 的职责不同：

- `docker/cinderx-test`：快速实验、频繁切换 benchmark 与优化开关
- `docker/cpython-baseline`：正式对照 `stock CPython JIT vs CinderX JIT`

## 快速开始

### 1. 构建 ARM64 wheel

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
./docker/cinderx-test/scripts/build-wheel.sh
```

### 2. 启动实验容器

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT/docker/cinderx-test"
docker compose -p cinderx-exp up -d
```

### 3. 准备 benchmark 并安装 CinderX

```bash
docker compose -p cinderx-exp exec cinderx-arm64 sh -lc \
  'BENCHMARK=generators /scripts/setup.sh'
```

### 4. 运行 smoke test

```bash
docker compose -p cinderx-exp exec cinderx-arm64 /scripts/smoke.sh
```

### 5. 跑 benchmark 对比

```bash
docker compose -p cinderx-exp exec cinderx-arm64 sh -lc \
  'BENCHMARK=generators /scripts/test-benchmark.sh'
```

## 支持的 benchmark

当前已支持：

- `generators`
- `mdp`

benchmark 的元数据在：

- `docker/cinderx-test/scripts/benchmark_harness.py`

## 配置文件驱动的优化开关

稳定与实验开关统一放在：

- `docker/cinderx-test/configs/generators/`
- `docker/cinderx-test/configs/mdp/`

例如：

- `docker/cinderx-test/configs/generators/stable.env`
- `docker/cinderx-test/configs/mdp/stable.env`
- `docker/cinderx-test/configs/mdp/experimental-round4.env`

运行 `mdp stable`：

```bash
docker compose -p cinderx-exp exec cinderx-arm64 sh -lc \
  'BENCHMARK=mdp OPT_ENV_FILE=/scripts/configs/mdp/stable.env SAMPLES=5 WARMUP=1 /scripts/test-benchmark.sh'
```

运行 `mdp experimental-round4`：

```bash
docker compose -p cinderx-exp exec cinderx-arm64 sh -lc \
  'BENCHMARK=mdp OPT_ENV_FILE=/scripts/configs/mdp/experimental-round4.env OPT_CONFIG_NAME=experimental-round4 SAMPLES=5 WARMUP=1 /scripts/test-benchmark.sh'
```

## 并行项目隔离

隔离方式使用 compose project name 和结果目录，而不是固定容器名：

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT/docker/cinderx-test"
RESULTS_DIR=./results-mdp docker compose -p mdp-exp up -d
RESULTS_DIR=./results-generators docker compose -p generators-exp up -d
```

这样多组实验可以共享同一个基础镜像 `python:3.14-slim`，但实例、网络、缓存和结果目录彼此隔离。

## 常用命令

单次跑某个 benchmark：

```bash
docker compose -p cinderx-exp exec cinderx-arm64 sh -lc \
  'BENCHMARK=mdp SAMPLES=10 WARMUP=3 /scripts/bench-benchmark.sh'
```

兼容旧入口：

```bash
docker compose -p cinderx-exp exec cinderx-arm64 /scripts/bench-generators.sh
docker compose -p cinderx-exp exec cinderx-arm64 /scripts/test-generators.sh
```

交互式进入容器：

```bash
docker compose -p cinderx-exp exec cinderx-arm64 bash
```

## 结果路径

对比结果会按 benchmark/config 分层落盘：

- `/results/<benchmark>/<config-name>/comparison.json`

例如：

- `/results/generators/stable/comparison.json`
- `/results/mdp/stable/comparison.json`
- `/results/mdp/experimental-round4/comparison.json`

## 环境变量

- `BENCHMARK`：要运行的 benchmark，例如 `generators`、`mdp`
- `OPT_ENV_FILE`：优化开关配置文件路径
- `OPT_CONFIG_NAME`：结果标签；默认取 `.env` 文件名
- `SAMPLES`：采样次数，默认 `10`
- `WARMUP`：预热次数，默认 `3`
- `RESULTS_DIR`：宿主机结果目录
- `BASE_IMAGE`：公共基础镜像名，默认 `python:3.14-slim`

## 注意事项

1. Docker ARM64 仿真依赖 QEMU，性能数据只适合做方向验证，不适合作为正式基线。
2. `generators` 的路径仍要求包含 `bm_generators/run_benchmark.py`，当前 `setup.sh` 已按真实 benchmark 目录结构准备。
3. 这套容器的基础镜像应该保持稳定复用；benchmark 脚本、配置、wheel 与结果都通过挂载提供，不应因为实验切换而重建镜像。
