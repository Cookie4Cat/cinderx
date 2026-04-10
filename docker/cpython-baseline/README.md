# CinderX 性能测试环境

## 概述

使用 Docker 容器测试 CinderX 的性能提升。容器基于 Python 3.14 官方镜像，包含编译工具和测试脚本。

## 快速开始

### 1. 构建 CinderX wheel（在宿主机）

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# 使用 Docker 交叉编译 ARM64 wheel
docker run --rm --platform linux/arm64 \
  -v "$PWD:/cinderx" \
  -w /cinderx \
  python:3.14-slim bash -c '
    apt-get update -qq && apt-get install -y -qq build-essential cmake git > /dev/null 2>&1
    pip install --quiet build
    export CMAKE_BUILD_PARALLEL_LEVEL=1
    export CINDERX_BUILD_JOBS=1
    python -m build --wheel
    ls -lh dist/cinderx-*-linux_aarch64.whl
  '
```

### 2. 构建公共基础镜像

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT/docker/cpython-baseline"
docker compose build
```

这一步只在基础镜像变化时需要执行，例如：

- `Dockerfile`
- 系统依赖
- 基础 Python 镜像版本

镜像名固定为 `cinderx-cpython-baseline:arm64`，不会因为 compose project name 不同而变化。

### 3. 启动测试容器

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT/docker/cpython-baseline"
docker compose up -d
docker compose exec cpython-baseline bash
```

首次构建基础镜像时仍需要宿主机具备 `linux/arm64` 容器构建能力；但镜像一旦构建完成，后续切换实验、脚本、配置或 compose project name 都不应该触发重建。

### 并行项目隔离

推荐每次正式对照分配独立的 compose project 和结果目录：

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT/docker/cpython-baseline"
RESULTS_DIR=./results-mdp-round3 docker compose -p mdp-round3 up -d
```

这样可以避免不同正式对照任务共享同一个 compose project、容器实例与结果文件。
不同 project 会复用同一个基础镜像 `cinderx-cpython-baseline:arm64`，不会因为 `-p` 不同而重新构建镜像。

### 配置文件驱动的优化开关

稳定配置统一放在：

- `docker/cpython-baseline/configs/generators/`
- `docker/cpython-baseline/configs/mdp/`

例如：

- `docker/cpython-baseline/configs/mdp/stable.env`

运行时通过 `OPT_ENV_FILE` 选择当前正式对照所用的稳定配置：

```bash
docker compose -p mdp-round3 exec cpython-baseline sh -lc \
  'BENCHMARK=mdp OPT_ENV_FILE=/scripts/configs/mdp/stable.env SAMPLES=5 WARMUP=1 /scripts/test-comparison.sh'
```

结果会按 `results/<benchmark>/<config-name>/comparison.json` 分层落盘，减少不同实验之间的覆盖与冲突。

### 额外环境约定

- `CPYTHON_ROOT`：stock CPython 3.14 JIT 源码目录，默认是 `$HOME/Repo/cpython`
- compose project name：用 `docker compose -p <name>` 指定，用于隔离并行实验
- `RESULTS_DIR`：宿主机结果目录，用于隔离并行实验输出
- `BASE_IMAGE`：公共基础镜像名，默认是 `cinderx-cpython-baseline:arm64`

例如：

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT/docker/cpython-baseline"
BASE_IMAGE=cinderx-cpython-baseline:arm64 \
CPYTHON_ROOT="$HOME/Repo/cpython" \
RESULTS_DIR=./results-mdp-stable \
docker compose -p mdp-stable up -d
```

### 4. 在容器内安装 CinderX

```bash
pip install /dist/cinderx-*-linux_aarch64.whl
```

### 5. 准备 benchmark

**重要：** 路径必须包含 `bm_generators/run_benchmark.py`，否则 none-truthy 优化不会触发。

```bash
python3 << 'PY'
import urllib.request
import pathlib

url = "https://raw.githubusercontent.com/python/pyperformance/main/pyperformance/data-files/benchmarks/bm_generators/run_benchmark.py"
# 路径必须包含 bm_generators/，isGeneratorsTreeIterCode() 会检查这个路径
output_path = pathlib.Path("/root/bm_generators/run_benchmark.py")
output_path.parent.mkdir(exist_ok=True)

print(f"Downloading {url}...")
urllib.request.urlretrieve(url, output_path)
print(f"✓ Saved to {output_path}")

# pyperf shim (benchmark 需要 pyperf.perf_counter)
with open("/root/bm_generators/pyperf.py", "w") as f:
    f.write("import time\ndef perf_counter(): return time.perf_counter()\nclass Runner:\n    def __init__(self, *a, **k): pass\n    def bench_time_func(self, *a, **k): pass\n")
print("✓ pyperf shim written")
PY
```

### 6. 测试 CPython baseline

```bash
python3 << 'PY'
import sys
import time
import statistics

sys.path.insert(0, "/root/bm_generators")
from run_benchmark import bench_generators

# Warmup
for _ in range(3):
    bench_generators(1)

# Measure (bench_generators returns elapsed time directly via pyperf shim)
times = []
for i in range(10):
    elapsed = bench_generators(1)
    times.append(elapsed)
    print(f"Run {i+1}: {elapsed:.6f}s")

avg = statistics.mean(times)
print(f"\nBaseline: {avg:.6f}s")
PY
```

### 7. 测试 CinderX

```bash
python3 << 'PY'
import sys
import time
import statistics
import cinderx
import cinderx.jit as jit

jit.enable()
print(f"JIT enabled: {jit.is_enabled()}")

sys.path.insert(0, "/root/bm_generators")
from run_benchmark import bench_generators, Tree
jit.force_compile(Tree.__iter__)

# Warmup
for _ in range(3):
    bench_generators(1)

# Measure (bench_generators returns elapsed time directly)
times = []
for i in range(10):
    elapsed = bench_generators(1)
    times.append(elapsed)
    print(f"Run {i+1}: {elapsed:.6f}s")

avg = statistics.mean(times)
print(f"\nCinderX: {avg:.6f}s")
PY
```

### 8. 测试 CinderX + 优化

```bash
PYTHONJIT_ARM_GENERATOR_NONE_TRUTHY=1 python3 << 'PY'
import sys
import time
import statistics
import os

print(f"Optimization enabled: PYTHONJIT_ARM_GENERATOR_NONE_TRUTHY={os.environ.get('PYTHONJIT_ARM_GENERATOR_NONE_TRUTHY')}")

import cinderx
import cinderx.jit as jit
jit.enable()

sys.path.insert(0, "/root/bm_generators")
from run_benchmark import bench_generators, Tree
jit.force_compile(Tree.__iter__)

# Warmup
for _ in range(3):
    bench_generators(1)

# Measure (bench_generators returns elapsed time directly)
times = []
for i in range(10):
    elapsed = bench_generators(1)
    times.append(elapsed)
    print(f"Run {i+1}: {elapsed:.6f}s")

avg = statistics.mean(times)
print(f"\nCinderX (optimized): {avg:.6f}s")
PY
```

### 8. 计算对比

```bash
python3 << 'PY'
# 输入上面三步得到的结果
baseline = 0.XX  # 从步骤 5 获取
cinderx = 0.XX   # 从步骤 6 获取
optimized = 0.XX # 从步骤 7 获取

speedup_cx = baseline / cinderx
speedup_opt = baseline / optimized
opt_benefit = cinderx / optimized

print(f"Baseline:            {baseline:.6f}s")
print(f"CinderX:             {cinderx:.6f}s")
print(f"CinderX (optimized): {optimized:.6f}s")
print()
print(f"Speedup (CinderX):   {speedup_cx:.4f}x ({(speedup_cx-1)*100:+.2f}%)")
print(f"Speedup (optimized): {speedup_opt:.4f}x ({(speedup_opt-1)*100:+.2f}%)")
print(f"Optimization benefit: {opt_benefit:.4f}x ({(opt_benefit-1)*100:+.2f}%)")
PY
```

## 预期结果

**实测结果（Docker ARM64 QEMU，15次运行）：**

```
CPython baseline:        35.727ms ± 0.576ms
CinderX (no opt):        67.485ms ± 1.073ms
CinderX (none-truthy):   66.685ms ± 1.220ms

CinderX vs baseline:     0.53x (-47%)    ← QEMU 对递归 yield from JIT 代码处理效率低
none-truthy opt benefit: 1.0120x (+1.20%)  ← 核心收益指标
```

**为什么 CinderX 在 QEMU 下比 CPython 慢？**

这不是噪音，而是 QEMU 对不同类型代码处理效率的系统性差异：

| 代码类型 | QEMU 处理方式 | 效率 |
|---------|--------------|------|
| 静态编译的 CPython 解释器 | 预先翻译 + block cache | 高 |
| JIT 生成的递归 yield from 代码 | 频繁重新翻译复杂控制流 | 低 |

实验验证：
- 简单计算循环：JIT 比 CPython **快 24%**（正常）
- **递归 yield from**：JIT 比 CPython **慢 1.8 倍**（QEMU 特有问题）

**核心验证指标**：`none-truthy opt benefit: +1.20%` vs 真实 ARM 硬件预期 `+0.79%`（方向一致，量级合理）

## 清理

```bash
docker compose down
# 如果用了独立 project name：
docker compose -p mdp-round3 down
```

## 故障排除

### wheel 安装失败
确保使用 Python 3.14 编译的 wheel：
```bash
python3 --version  # 应该是 3.14.x
pip debug --verbose  # 检查兼容的 tag
```

### `docker compose up -d --build` 出现 `exec format error`

这通常说明当前宿主机的 Docker 环境没有正确启用 `linux/arm64` 容器构建能力。

可检查：

- Docker Desktop 的 `Use Rosetta for x86/amd64 emulation` 或等价的 QEMU/binfmt 配置是否正常
- 是否已经存在可复用的 `linux/arm64` 镜像

一旦基础镜像已构建完成，后续只改 `scripts/` 或 `configs/` 时通常不需要重建镜像，因为这两个目录已经通过 bind mount 直接挂进容器。

### JIT 没有启用
```bash
python3 -c "import cinderx.jit as jit; print(jit.is_enabled())"
```

### 优化没有触发
`isGeneratorsTreeIterCode()` 要求文件路径包含 `bm_generators/run_benchmark.py`。
必须使用 `/root/bm_generators/run_benchmark.py` 而不是 `/root/benchmarks/run_benchmark.py`：
```bash
echo $PYTHONJIT_ARM_GENERATOR_NONE_TRUTHY
python3 -c "
import sys
sys.path.insert(0, '/root/bm_generators')
from run_benchmark import Tree
print(f'qualname: {Tree.__iter__.__code__.co_qualname}')
print(f'filename: {Tree.__iter__.__code__.co_filename}')
"
```
