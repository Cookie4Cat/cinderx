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

## 附录：使用 gdb 定位 AArch64 deopt_idx 问题的过程记录

这一节专门记录 `mdp + PYTHONJITAUTO=2 + DIAG=1` 下，围绕 `prepareForDeopt()` / AArch64 deopt trampoline 的定位过程。目的不是复述每次试验，而是沉淀：

- 已经验证有效的调试入口
- 已经被证伪的假设
- 当前可以复用的中间结论

### 1. 统一调试入口

调试入口固定为 Docker 持久容器中的最终 Python 命令，而不是 shell wrapper：

- 容器：`cinderx-native-debug`
- 入口脚本：
  - [run-native-gdb.sh](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/run-native-gdb.sh)

原因：
- `test-benchmark.sh` 会优先安装共享 wheel cache 中的 wheel，容易覆盖手工重装的调试 wheel
- 直接对最终 `python -m pyperformance run ...` 挂 `gdb`，才能确保看到的是当前容器里实际执行的 `_cinderx.so`

### 2. 最初观察到的坏现场

在 [prepareForDeopt()](/Users/luchen/Agents-Repo/Codex/cinderx/cinderx/Jit/codegen/gen_asm.cpp) 行号断点上，针对坏现场加条件 `deopt_idx > 1000`，首次稳定抓到：

- `code_runtime->deopt_metadatas_.size() == 7`
- `code_runtime->frameSize() == 240`
- 对应 runtime：
  - `FileFinder.__init__.<locals>.<genexpr>`
  - 文件：`<frozen importlib._bootstrap_external>`
  - `co_firstlineno = 1340`

但现场参数却是：
- `deopt_idx` 为大地址/指针样式值
- `x3` 常常是一个较小的整数，比如 `0x1fc`

这已经证明：
- 当前 `deopt_idx` 不可能是这个 runtime 合法生成出来的本地索引
- 问题更可能在 AArch64 deopt trampoline 的参数搬运链路，而不是 `CodeRuntime::addDeoptMetadata()` 本身

### 3. 已经验证过的 gdb 抓取方法

有效的方法有两类：

1. 在 [prepareForDeopt()](/Users/luchen/Agents-Repo/Codex/cinderx/cinderx/Jit/codegen/gen_asm.cpp) 行号断点上，加条件 `deopt_idx > 1000`
   - 打印：
     - `deopt_idx`
     - `code_runtime`
     - `regs`
     - live `x0/x1/x2/x3/x14/x29/sp`
     - `code_runtime->deopt_metadatas_.size()`
     - 对应 `PyCodeObject` 的 `co_name/co_qualname/co_filename/co_firstlineno`
   - 并反汇编 caller 附近指令

2. 直接在 caller 附近看 stage2 到 `prepareForDeopt()` 的指令序列
   - 这是后来最有价值的方法
   - 能直接看到 `x2/x3` 分别是从哪些槽位读出来的

### 4. 已经证伪的方向

下面这些方向已经被 `gdb` 明确否掉，后续不要再回头反复试：

#### 4.1 “deopt metadata 序列生成错了”

对坏 runtime：
- `FileFinder.__init__.<locals>.<genexpr>`

在代码生成阶段抓到的 `deopt_meta_index` 序列是：
- `0, 1, 2, 3, 4, 4, 5, 6`

这和 `code_runtime->deopt_metadatas_.size() == 7` 是自洽的。  
因此：
- 问题不在 `generateDeoptExits()` 生成的 index 来源
- 也不在 `addDeoptMetadata()` 的本地编号逻辑

#### 4.2 “stage1 元数据槽位顺序反了”

曾经怀疑：
- `meta_base + 48` 与 `meta_base + 56`
- 在 stage1 里被反向解释成了 `{saved_pc, deopt_idx}` / `{deopt_idx, saved_pc}`

为此做过一次实验性 patch，把 stage2 读取顺序改成：
- `x2 <- [x14, #48]`
- `x3 <- [x14, #56]`

`gdb` 现场表明：
- `meta_base + 56` 恰好是小整数 `0x1`
- 更像真实 `deopt_idx`
- 而 `meta_base + 48` 仍然是大地址，更像 `saved_pc`

这说明：
- **原始 stage1 元数据顺序其实是对的**
- 简单交换 `+48/+56` 不是根因

这个实验 patch 已被回退，不应再作为主线方向。

### 5. 当前最重要的 caller 级证据

在恢复到基线顺序后，`gdb` 抓到的 stage2 caller 关键反汇编是：

```asm
ldr x3, [x14, #48]
str x29, [x14, #48]
add x29, x14, #0x30
ldr x2, [x29, #8]
str x3, [x29, #8]
stur x2, [x29, #-16]
ldur x1, [x29, #-24]
blr  prepareForDeopt
```

从现场槽位看：

- `meta_base == x14`
- `[x14 + 48]` 是原 stage1 元数据对中的一个槽
- `[x29 + 8]` 与 `[x14 + 56]` 是同一个逻辑槽位
- `prepareForDeopt()` 里看到的坏 `deopt_idx`，来自：
  - `ldr x2, [x29, #8]`

也就是说，当前问题已经缩小到：
- **AArch64 stage2 在把 stage1 元数据重排成 `prepareForDeopt()` 调用约定时，`x2` 的来源仍然不对**

### 6. 为什么行号断点看到的寄存器不一定可信

一个关键经验是：
- 在 C++ 源码行号断点停住时，寄存器可能已经被函数 prologue 或前几条指令改写

因此，后续若需要继续确认：
- `prepareForDeopt()` 真正被调用时的参数寄存器

优先级应当是：
1. 看 caller 在 `blr prepareForDeopt` 前的最后几条指令
2. 再和 live `x0/x1/x2/x3` 对照
3. 最后才参考源码行号断点处看到的局部变量值

### 7. 当前阶段性结论

截至目前，可以认为已经坐实的结论是：

- 问题不在本地 deopt metadata 编号生成
- 问题也不在简单的 stage1 `{saved_pc, deopt_idx}` 槽位顺序
- 真正的问题仍位于：
  - [gen_asm.cpp](/Users/luchen/Agents-Repo/Codex/cinderx/cinderx/Jit/codegen/gen_asm.cpp)
  - AArch64 stage2 trampoline 到 `prepareForDeopt()` 的参数搬运链

更具体地说：
- 需要继续确认的是：
  - caller 在 `blr prepareForDeopt` 之前，`x2` 为什么会从当前这个槽位装载
  - 以及该槽位在这条路径上为什么没有持有合法的 `deopt_idx`

### 7.1 基线 wheel 重新安装后的最新入口现场

在回退掉实验性 patch、重新编译并重装**基线 wheel**之后，再次对 `prepareForDeopt` 入口打断，拿到的现场是：

- `x2` 仍然是大地址样式值
- `x3 = 0x1fc`
- 对应 caller 反汇编恢复成了基线顺序：

```asm
ldr x3, [x14, #48]
str x29, [x14, #48]
add x29, x14, #0x30
ldr x2, [x29, #8]
str x3, [x29, #8]
stur x2, [x29, #-16]
ldur x1, [x29, #-24]
blr  prepareForDeopt
```

同时现场槽位为：

- `[x14 + 48]` 对应 `x3 = 0x1fc`
- `[x14 + 56]` / `[x29 + 8]` 对应 `x2 = 大地址`

这个基线现场说明两点：

1. 之前“交换 `+48/+56` 读取顺序”的实验结果确实不应再作为依据  
   因为那一轮抓到的是旧 wheel，而不是回退后的基线 wheel。

2. 在当前基线下，真正的问题是：
   - `stage2` 确实按当前源码约定去取：
     - `x3 <- [meta_base + 48]`
     - `x2 <- [fp + 8]`，其中 `fp = meta_base + 48`
   - 但此时：
     - `meta_base + 48` 里是小整数 `0x1fc`
     - `meta_base + 56` 里却是大地址

因此，当前需要继续回答的问题不是“caller 是否读错了偏移”，而是：
- **为什么进入 stage2 时，stage1 元数据对本身已经呈现出 `{0x1fc, 大地址}` 这种形状**
- 也就是更偏向：
  - stage1 写入内容不对
  - 或 stage1 写入时机/寄存器来源不对

### 7.2 入口断点进一步坐实的事实

后续继续在 **基线 wheel** 上，对 `prepareForDeopt` 函数入口本身打断，而不是源码行号断点，确认了：

- 坏值在函数入口就已经存在于 `x2`
- 不是 `prepareForDeopt()` 的 prologue 改坏了参数

这次入口现场同时给出了 caller 的稳定反汇编：

```asm
mov x0, sp
ldr x3, [x14, #48]
str x29, [x14, #48]
add x29, x14, #0x30
ldr x2, [x29, #8]
str x3, [x29, #8]
stur x2, [x29, #-16]
ldur x1, [x29, #-24]
blr  prepareForDeopt
```

并且入口现场稳定表现为：

- `x3 = 0x1fc`
- `x2 = 大地址`

### 7.3 新发现：源码行上的 `deopt_idx` 变量显示与 caller 现场不一致

继续在同一条 `gdb` 主线上命中 `prepareForDeopt()` 时，拿到了一个新的分叉信号：

- 当前源码行显示：
  - `code_runtime = 0x2306c3b0`
  - `deopt_idx = 0xffff9ab9a240`
- 同时 caller 现场显示：
  - `x14 = meta_base = 0xffffc47d6850`
  - `meta_base + 24 = 0x2306c3b0`
  - `meta_base + 32 = 0xffff9ab9a240`
  - `meta_base + 48 = 0xffff9bf187dc`
  - `meta_base + 56 = 0x1fc`

而 caller 反汇编明确显示：

```asm
ldr x3, [x14, #48]
add x29, x14, #0x30
ldr x2, [x29, #8]
blr prepareForDeopt
```

也就是说，从 caller 角度看：

- `x2` 的来源应当是 `meta_base + 56`
- 它应当对应小整数 `0x1fc`

但当前源码行上的 `deopt_idx` 局部变量却显示成了：

- `meta_base + 32`

这说明现在必须把下面两种情况区分开：

1. caller 真正传给 `prepareForDeopt` 的入口实参已经错了；
2. 断在源码行 225 时，受 prologue / 优化 / 调试信息影响，当前源码行上的 `deopt_idx` 变量显示已经不再可信。

因此后续定位顺序需要调整为：

1. 继续优先使用 `prepareForDeopt` 的**函数入口断点**，而不是源码行号断点；
2. 在入口处只看 live `x0/x1/x2/x3`；
3. 只有确认入口实参本身就错了，才继续向 caller / continuation 链回溯。

### 7.3 pyperformance 的 venv 根目录会受当前工作目录影响

这次继续用 `run-native-gdb.sh` 追 `linkJump()` 时，先撞到了一次与 JIT 无关的环境噪音：

- `pyperformance._venv.VenvCreationFailedError`
- 目标目录：
  - `/cinderx/venv/cpython3.14-119035a0db1a-compat-31b33d68c68a`

确认后发现：

- `pyperformance._venv.get_venv_root()` 默认使用相对目录 `venv/<runid>`
- 如果当前工作目录是 `/cinderx`，它就会把 venv 建到：
  - `/cinderx/venv/<runid>`
- 因此在同一个容器里反复从 `/cinderx` 目录启动 `gdb + pyperformance run`，很容易被残留 venv 干扰

这不是新的 JIT 现象，但它会中断 gdb 复现，后续调试时应优先：

- 改到新的工作目录（例如 `/tmp`）再启动 `pyperformance run`
- 或显式规避同名 venv 目录

不要把这类 `VenvCreationFailedError` 误判成新的 native/JIT blocker。

### 7.4 关键 one-run 证据：实际命中的是 stage1 stub 里的 `bl`，不是 `entry`

在唯一工作目录下重跑 one-run gdb 脚本后，针对坏 runtime：

- `importlib._bootstrap_external:FileFinder.__init__.<locals>.<genexpr>`

抓到了同一进程内的 stage1/stage2 地址：

- `base = 0xffff97b7bf80`
- `stage1 = 0xffff97b7c294`
- 可疑 stub 的：
  - `entry = 0xffff97b7c2e4`
  - `stp   = 0xffff97b7c2ec`
  - `bl    = 0xffff97b7c2f0`
  - `stage2 = 0xffff97b7c314`

然后在同一轮运行里，对 `entry / stp / bl / stage2` 四个地址都下临时断点，命中顺序是：

- **命中 `bl`**
- 紧接着命中 `stage2`
- **没有命中 `entry`**
- **没有命中 `stp`**

现场输出是：

- `HIT bl pc=0xffff97b7c2f0 sp=0xffffc74d2620 x12=0 x13=0xffff98679100 x30=0xffff97b7c38c`
- `HIT stage2 pc=0xffff97b7c314 sp=0xffffc74d2620 x12=0 x13=0xffff98679100 x30=0xffff97b7c2f4`

这个证据直接说明：

- 当前坏路径并不是从 stage1 stub 的开头进入
- 也不是从 `stp` 进入
- 而是**直接跳到了 stub 中间的 `bl stage2` 指令**

因此当前最强结论已经不是“stage1 生成的 `mov/adr/stp` 有问题”，而是：

- **deopt patchpoint 最终被链接/解析到了 stage1 stub 的内部地址**
- 对这个坏 case 来说，目标地址至少偏到了 `bl` 这一条指令

这也解释了之前所有矛盾现象：

- 为什么 `x30` 看起来像某个 `after` 地址
- 为什么 `stage2` 入口时 `x12/x13` 根本不是 stub 里应有的值
- 为什么栈顶那对元数据看起来像垃圾，而不是 `{saved_pc, deopt_idx}`

后续主线应转向：

- 继续确认 **谁** 把 patchpoint 目标解析成了 `bl` 地址
- 以及这个偏移是来自：
  - `code.labelOffsetFromBase(udp.deopt_exit)` 结果本身
  - 还是 `JumpPatcher::linkJump()` 接收到的 `jump_target`
  - 还是更早的 `udp.deopt_exit` label 绑定就已经偏了

### 7.5 新分叉结论：坏 runtime 根本没有走 patcher 路径

进一步直接在：

- `NativeGenerator::linkDeoptPatchers(...)`

上对坏 runtime 做过滤，打印：

- `env_.deopt_exits.size()`
- `env_.pending_deopt_patchers.size()`

结果是：

- `deopt_exits = 8`
- `pending_patchers = 0`

这说明：

- `FileFinder.__init__.<locals>.<genexpr>` 这个坏 runtime 虽然有 8 个 deopt exits
- 但**没有任何 pending deopt patcher**

因此当前坏路径并不是：

- `DeoptPatchpoint -> JumpPatcher::linkJump() -> stage1`

而是：

- **普通 guard / 直接分支**
- 直接跳到了 stage1 deopt stub 相关地址

这也解释了为什么前一轮在 `linkJump()` 上按坏 runtime 过滤时完全没有命中：

- 不是 gdb 失灵
- 而是这个 runtime 在这条路径上本来就没有 patcher 要 link

所以主线已经进一步收窄为：

- 问题出在“直接分支到 deopt exit label”的代码生成/绑定路径
- 不再应该优先怀疑 `JumpPatcher::linkJump()`
- `[x14 + 48]` 在 caller 覆盖前的原值，会被读入 `x3`
- `[x14 + 56]` / `[x29 + 8]` 会被读入 `x2`

这进一步说明：

1. stage2 当前的读槽逻辑与源码是一致的  
   也就是：
   - `saved_pc <- meta_base + 48`
   - `deopt_idx <- meta_base + 56`

2. 真正值得继续怀疑的点已经进一步收窄为：
   - **stage1 实际写入到这两个槽位的内容，与我们源码注释所假设的语义不一致**

换句话说，主问题已经更偏向：
- stage1 写错值
- 或 stage1 里用于 `stp(...)` 的两个寄存器在运行时不是我们以为的那一对

### 7.3 回到基线后再次确认：坏 `deopt_idx` 仍然直接进入 `prepareForDeopt()`

在完全回退掉“stage2 交换读取顺序”的实验性 patch、重新编译并重装**基线 wheel**后，再次运行针对坏 `genexpr` 的 `gdb batch`，新的基线现场仍然直接表现为：

- 最后一个成功进入编译的坏 runtime：
  - `importlib._bootstrap_external:FileFinder.__init__.<locals>.<genexpr>`
- 随后直接在：
  - [prepareForDeopt()](/Users/luchen/Agents-Repo/Codex/cinderx/cinderx/Jit/codegen/gen_asm.cpp)
  - 第 225 行
  - 以巨大的 `deopt_idx` 进入
- 当前现场参数：
  - `code_runtime = 0x80e33b0`
  - `deopt_idx = 281472828350976`

这条证据的意义是：

1. 巨大 `deopt_idx` 不是实验 patch 带来的假象  
2. 问题仍然稳定地落在同一个坏 runtime：
   - `FileFinder.__init__.<locals>.<genexpr>`
3. 当前主线不应再回到“是不是 stage2 交换顺序”的旧假设上，而应继续围绕：
   - caller 在 `blr prepareForDeopt` 前的 live 寄存器
   - stage1 向元数据槽位实际写入了什么
   继续往下追

这一轮也顺便说明：

- 试图直接在 `generateDeoptExits()` 里抓 finalized deopt exit 偏移的 `gdb batch`
- 至少在这次运行中，并没有先于崩溃输出足够信息

因此当前最有效的抓手仍然是：
- `prepareForDeopt` 入口断点
- caller 反汇编
- live `x2/x3/x14/x29/sp` 现场

### 7.4 新的基线快照：坏现场稳定复现，caller/live register 形状一致

在同一份基线 wheel 上，再次运行：

- [mdp-prepare-entry.gdb](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/mdp-prepare-entry.gdb)

得到的现场与上一轮趋势一致，而且这次 live register、caller 反汇编和栈槽都一起拿到了：

- `ENTRY-BAD`
  - `x1 = 0x1dd18500`
  - `x2 = 0xffffb12626c0`
  - `x3 = 0x1fc`
  - `x14 = 0xfffff46d70a0`
  - `x29 = 0xfffff46d70d0`
- 对应 caller 反汇编仍然是：

```asm
mov x0, sp
ldr x3, [x14, #48]
str x29, [x14, #48]
add x29, x14, #0x30
ldr x2, [x29, #8]
str x3, [x29, #8]
stur x2, [x29, #-16]
ldur x1, [x29, #-24]
blr prepareForDeopt
```

这说明两件事：

1. 这条坏路径已经可以**稳定复现成同一种 caller 形状**  
2. 当前最值得继续追的，不再是“prepareForDeopt 入口是不是偶发读坏”，而是：
   - `x14` 在 caller 中到底代表什么
   - 这段 caller 代码之前，是谁把那对槽位准备成了现在这种内容

需要特别注意的是，这一轮 live register 和内存槽位之间仍然出现了“语义对不上”的迹象：

- 现场看到：
  - `x2 = 大地址`
  - `x3 = 0x1fc`
- 但 caller 的读法又是：
  - `x3 <- [x14 + 48]`
  - `x2 <- [x29 + 8]`

这意味着后续不能再只看一小段 caller 尾部，而要继续往前反汇编，确认：

- `x14` 是在哪里建立的
- `x29` 在 caller 中原本是谁
- 以及在进入这几条 `ldr/str` 之前，那对槽位的实际布局是谁写的

### 7.5 `x2/x3` 与内存并不矛盾：caller 尾部会当场改写那对槽位

继续在基线 wheel 上，对 [prepareForDeopt()](/Users/luchen/Agents-Repo/Codex/cinderx/cinderx/Jit/codegen/gen_asm.cpp) 函数入口本身打断，并把 caller 扩大到更长的反汇编窗口后，可以把之前那个“`x2/x3` 和内存好像对不上”的疑点解释清楚：

caller 的关键尾部仍然是：

```asm
ldr x3, [x14, #48]
str x29, [x14, #48]
add x29, x14, #0x30
ldr x2, [x29, #8]
str x3, [x29, #8]
stur x2, [x29, #-16]
ldur x1, [x29, #-24]
blr prepareForDeopt
```

而这几条指令的真实效果是：

1. `x3` 先取 **原始** `slot48`
2. 随后 `slot48` 立刻被旧 `x29` 覆盖
3. `x2` 再取 **原始** `slot56`
4. 随后 `slot56` 又被 `x3` 覆盖成原始 `slot48`

所以在 `prepareForDeopt` 入口看到：

- `x3 = 0x1fc`
- `x2 = 大地址`

而同时内存里已经变成：

- `slot48 = 旧 x29`
- `slot56 = 0x1fc`

这并不矛盾，反而说明 caller 的尾部逻辑是自洽的。真正的原始值应该理解成：

- **原始 `slot48` = `0x1fc`**
- **原始 `slot56` = 大地址**

这条结论非常关键，因为它把当前主问题进一步收窄成：

- stage2 当前并不是“读错了 caller 改写后的内存”
- 真正有问题的是：
  - stage1 在进入这段 caller 前，就已经把那对原始槽位写成了 `{0x1fc, 大地址}`

也就是说，后续主线应继续围绕：

- `0x1fc` 是否是某个 stage1 `after` label / 本地 offset
- 为什么原始 `slot56` 会是一个大地址，而不是合法的小 `deopt_idx`

### 7.6 关键翻案：stage1 本身写入的是正确形状，问题发生在 global trampoline 之后

继续在坏 `genexpr` 的 finalized 阶段，用 `gdb` 直接反汇编出对应的 stage1 trampolines 后，已经可以明确看到：

```asm
mov x12, #<small deopt_meta_index>
adr x13, <after>
stp x13, x12, [sp, #-16]!
bl  <stage2 trampoline>
```

对这条坏 runtime，实际反汇编出来的序列就是：

```asm
0xffff...c298: mov x12, #0
0xffff...c29c: adr x13, 0xffff...c2a4
0xffff...c2a0: stp x13, x12, [sp, #-16]!
0xffff...c2a4: mov x12, #1
0xffff...c2a8: adr x13, 0xffff...c2b4
0xffff...c2ac: stp x13, x12, [sp, #-16]!
...
0xffff...c304: mov x12, #6
0xffff...c308: adr x13, 0xffff...c314
0xffff...c30c: stp x13, x12, [sp, #-16]!
```

这条证据已经足够推翻之前那个“可能是 stage1 自己写错了 `{saved_pc, deopt_idx}`”的怀疑：

1. stage1 写入顺序是对的  
   - 第一个槽是 `after` 的绝对地址
   - 第二个槽是小的 `deopt_meta_index`

2. `0x1fc` 这种小 offset **不是** stage1 直接写进去的原始值  
3. 巨大的 `deopt_idx` 也不是 stage1 直接写进去的小索引

因此，当前主问题已经进一步收窄为：

- **global deopt trampoline / stage2 到 `prepareForDeopt()` 之间的 marshalling 把这对值改坏了**

这意味着后续不该再回到：
- “stage1 `stp(saved_pc, deopt_idx)` 顺序是否反了”
- “stage1 `adr after` 是否拿错标签”

而应该继续集中在：
- global trampoline 如何保存/搬运 stage1 留在栈顶的那对值
- 以及它如何最终生成 caller 里看到的：
  - 原始 `slot48 = 0x1fc`
  - 原始 `slot56 = 大地址`

### 7.7 新证据：deopt label 绑定和 direct guard 跳转都正确，stage2 物化 `saved_pc` 时才偏到 `bl`

继续在坏 runtime

- `importlib._bootstrap_external:FileFinder.__init__.<locals>.<genexpr>`

上用 `gdb` 抓两个阶段后，可以把问题再缩小一层：

1. 在 `linkDeoptPatchers()` 阶段，`env_.deopt_exits` 的 label 绑定已经是正确的 stage1 入口：
   - `label 28 -> off 788`
   - `label 31 -> off 804`
   - `label 34 -> off 820`
   - `label 37 -> off 836`
   - `label 40 -> off 852`
   - `label 42 -> off 868`
   - `label 45 -> off 884`
   - `label 48 -> off 900`

   这些 offset 正好对应 stage1 stub 的入口，而不是其中的 `stp` 或 `bl`。

2. 在同一份 finalized 反汇编里，direct guard 的分支目标也是正确的：

   ```asm
   0xffff9476c164:  b   0xffff9476c2e4
   ```

   其中：
   - `0xffff9476c2e4`
   - 正是 `EXIT1 idx=1 label=31 off=804`
   - 也就是 stage1 stub 的入口

3. 但随后在 stage2 / global trampoline 相关代码里，又能看到：

   ```asm
   0xffff9476c39c:  adr x28, 0xffff9476c2f0
   0xffff9476c3a0:  str x28, [sp, #16]
   ```

   这里写入栈的地址是：
   - `0xffff9476c2f0`

   它对应的是 stage1 stub 里的：

   ```asm
   0xffff9476c2f0:  bl  0xffff9476c314
   ```

   而不是该 stub 正确的 `after` 标签：
   - `0xffff9476c2f4`

这条证据说明：

1. direct guard 分支到 deopt exit label 的绑定没有错  
2. `env_.deopt_exits[i].label` 也没有被错误绑到 `bl` 那一格  
3. 真正偏移到 `bl` 地址的时机，发生在 **stage2 / global trampoline 物化 `saved_pc`** 的时候

因此当前主线已进一步收窄为：

- 不再优先怀疑 `TranslateGuard()` 的 direct branch target
- 不再优先怀疑 `deopt_exit.label` 的 bind offset
- 应集中检查 AArch64 stage2 / global deopt trampoline：
  - 为什么它在这条路径上把 `saved_pc` 设成了 `c2f0`
  - 而不是 stage1 `after` 的 `c2f4`

### 7.8 新证据：坏 deopt 路径在进入 `prepareForDeopt()` 前绕过了整个 stage1

继续用 `gdb`，在同一轮 `linkDeoptPatchers()` 命中坏 runtime 后，动态读取它真实的 8 个 stage1 entry 地址，并对这 8 个入口全部下断点；同时对 [prepareForDeopt()](/Users/luchen/Agents-Repo/Codex/cinderx/cinderx/Jit/codegen/gen_asm.cpp) 的坏 `deopt_idx > 1000` 现场下断点。

结果是：

- 能稳定命中：
  - `HIT prepareForDeopt ... deopt_idx=0xffff95f6a100`
- 但在这之前：
  - `HIT entry0`
  - `HIT entry1`
  - `HIT entry2`
  - `...`
  - `HIT entry7`
  **一个都没有出现**

这条证据非常关键，因为它说明：

1. 当前这条坏 deopt 路径不是“进了某个 stage1 stub，再在 stage1 里把 metadata 写坏”  
2. 也不是“只错过了某一个 entry，其它 entry 仍可能被走到”  
3. 而是：**在进入 `prepareForDeopt()` 之前，控制流直接绕过了整个 per-exit stage1 层**

这会把主线继续收窄成：

- 不是 stage1 `mov/adr/stp/bl` 序列本身
- 不是某个 `deopt_exit.label` 绑定到 stage1 入口后又在 stage1 里坏掉

而是更像：

- 某条路径直接跳到了 stage2 / global trampoline
- 或某条路径直接构造了 `prepareForDeopt()` 所需参数，却没有经过 stage1 的 metadata marshalling

因此后续调试重点应改为：

- 谁在绕过 stage1
- 它直接跳到的是：
  - per-function stage2 label
  - global deopt trampoline
  - 还是别的共享 stub

### 7.9 新证据：坏路径不是“正常进 stage2”，而是落到某个 stage1 stub 的 `bl` 指令上

继续用 `gdb`，这次不再只看 `prepareForDeopt()`，而是在坏 runtime 的 per-function stage2 入口直接看栈顶和关键寄存器。

在命中 stage2 入口时，现场是：

- `pc = 0xffffb89dc354`
- `sp = 0xffffe013f9b0`
- `x12 = 0`
- `x13 = 0xffffb94d9100`
- `x30 = 0xffffb89dc334`

同时栈顶 6 个槽是：

```text
[sp + 0x00] = 0x00000000000001fc
[sp + 0x08] = 0x0000ffffb876a100
[sp + 0x10] = 0x0000ffffb9dd33a0
[sp + 0x18] = 0x0000ffffb9e4dd70
[sp + 0x20] = 0x0000000000000000
[sp + 0x28] = 0x8000000000000001
```

这组值和“正常经过 stage1 `mov/adr/stp` 后再 `bl stage2`”完全对不上：

- 如果正常经过 stage1，stage2 入口前：
  - `x12` 应该还是小的 `deopt_meta_index`
  - `x13` 应该还是 `after` 标签地址
  - `[sp] / [sp+8]` 应该就是 `{saved_pc, deopt_idx}`

但现场里：
- `x12/x13` 已经是垃圾值
- `[sp] / [sp+8]` 也已经是垃圾元数据对

更关键的是：
- `x30 = 0xffffb89dc334`

这说明 stage2 是被一条 **返回地址为 `c334` 的 `bl`** 调进来的。结合这类 stage1 stub 的布局，可以把它解释为：

- 控制流不是从某个 stage1 stub 的入口开始执行
- 而是**直接落到了某个 stage1 stub 的 `bl stage2` 指令上**
- 因此前面的：
  - `mov x12, #deopt_idx`
  - `adr x13, after`
  - `stp x13, x12, [sp, #-16]!`
  根本没有执行

这条证据比“没有命中 entry 断点”更强，因为它直接来自 stage2 入口现场本身。

因此当前主线已经可以继续收窄为：

- 不是 stage1 模板本身生成错了
- 不是 stage2 shuffle 自己先把一对正确元数据读坏了

而是：

- **某条控制流把 PC 直接送进了 stage1 stub 的 `bl stage2` 指令，而不是送到该 stub 的入口**

后续最值得继续查的是：

- 谁把目标地址算成了 `stub_bl`
- 它对应的是否是：
  - 某个 direct deopt branch
  - 某个 hard-exit / helper 跳转
  - 某个共享 label / relocation 错绑

### 7.10 新证据：坏落点稳定指向 `exit5`（第二个 `idx=4`）的 `bl` 指令

继续对坏 runtime 做交叉对比后，出现了一个非常强的稳定模式：

1. 早前旧 run 里看到的坏地址：
   - `0x...c2f0`

2. 新 run 里在 stage2 入口看到：
   - `x30 = 0x...c334`

把它们都换算回各自 run 的 stage1 布局后，二者都落在同一种位置上：

- **`exit5` 那条 stage1 stub 的 `bl stage2` 指令**

而 `exit5` 对应的是：
- 第二个 `deopt_meta_index = 4`

也就是说，当前坏模式不是“随机落到某个 stub 的中间”：
- 它反复落在同一类位置
- 即：**重复 `idx=4` 中第二条 exit 的 `bl`**

结合已经确认过的 `env_.deopt_exits` 排序结果：

- `EXIT4 idx=4 label=40 off=852`
- `EXIT5 idx=4 label=42 off=868`

可以把当前怀疑继续收窄到：

1. 不是所有 deopt exit 都有同样风险  
2. 问题与 **重复 `deopt_meta_index`** 很可能相关  
3. 更像是某条链路在处理 deopt exit 时：
   - 没完全按 `label` 处理
   - 而是在某个阶段混入了 `deopt_meta_index` 级别的歧义
   - 并最终把控制流送进了第二个 `idx=4` stub 的 `bl` 指令

因此后续源码排查应优先查：

- 哪里会用 `deopt_meta_index` 而不是 `label`
- 哪里会在 duplicate `idx` 存在时仍假定“一对一映射”

### 7.11 新证据：坏路径直接命中 `EXIT5` 的 `bl`，没有执行它前面的 `mov/adr/stp`

继续在同一个坏 runtime 上，把 `EXIT5` 这条 stub 的四条关键指令都设成独立断点：

- `mov x12, #idx`
- `adr x13, after`
- `stp x13, x12, [sp, #-16]!`
- `bl stage2`

最新一轮 `gdb` 输出是：

```text
EXIT5-FLOW base=0xffffb028bf80 entry=0xffffb028c2e4 adr=0xffffb028c2e8 stp=0xffffb028c2ec bl=0xffffb028c2f0 idx=4
HIT exit5 bl pc=0xffffb028c2f0 sp=0xffffe78b4c70 x12=0 x13=0xffffb0d89100 x30=0xffffb028c38c
HIT prepareForDeopt pc=0xffffb085164c regs=0xffffe78b4a40 code_runtime=0x234da3b0 deopt_idx=0xffffb001a100
```

而在这次命中之前：

- 没有命中 `EXIT5` 的 `mov`
- 没有命中 `EXIT5` 的 `adr`
- 没有命中 `EXIT5` 的 `stp`

这条证据把“坏路径绕过 stage1”的判断再向前推进了一层：

1. 不是单纯“看起来像落在 `bl` 附近”  
2. 而是 **控制流真的直接落在了 `EXIT5` 的 `bl stage2` 指令上**  
3. 因此 `x12/x13` 在这时仍然是脏值：
   - `x12 = 0`
   - `x13 = 0xffffb0d89100`
4. 所以后面 `prepareForDeopt()` 看到的大地址 `deopt_idx`，并不是 stage1 正常 `mov/adr/stp` 后再被 stage2 读坏，而是：
   - stage1 的 metadata setup 根本没有执行
   - stage2 直接消费了无效寄存器/栈现场

这条证据当前是最强的 caller-side 结论，因此后续优先级应继续放在：

- 谁把控制流直接送进了 `EXIT5` 的 `bl`
- 为什么偏偏是第二个重复 `idx=4` 的那条 exit

### 7.12 新证据：坏 runtime 的函数尾部有一段显式把 `EXIT5` 的 `bl` 地址写入栈槽的代码

继续对同一轮坏 runtime 反汇编后，除了函数体里的 direct deopt 分支：

```text
0x...c19c: b 0x...c314
0x...c1a4: b 0x...c324
0x...c1c4: b 0x...c334
```

还发现了函数尾部有一段更可疑的序列：

```text
0xffffb1b2c3d0: mov x28, #0x6370
0xffffb1b2c3d4: movk w28, #0x104b, lsl #16
0xffffb1b2c3d8: str x28, [sp, #24]
0xffffb1b2c3dc: adr x28, 0xffffb1b2c330
0xffffb1b2c3e0: str x28, [sp, #16]
0xffffb1b2c3e4: mov x28, #0xd040
0xffffb1b2c3e8: movk x28, #0xb1b1, lsl #16
0xffffb1b2c3ec: movk x28, #0xffff, lsl #32
0xffffb1b2c3f0: br x28
```

其中：

- `0xffffb1b2c330`
  - 正是 `EXIT5` 的 `bl stage2` 指令地址
- 它被显式写进了：
  - `[sp, #16]`

这条证据非常重要，因为它说明：

1. 当前坏函数里不只是“控制流碰巧落到 `EXIT5 bl`”  
2. 而是**代码里存在一条显式构造 `EXIT5 bl` 地址并写入栈槽的路径**
3. 后续 deopt/跳板链路里看到的 `0x...c330`，很可能就来自这里，而不是来自 stage1 正常执行后的 `saved_pc`

因此当前排查方向继续收窄为：

- 这段尾部 stub 是什么语义
- 它为何把 `EXIT5` 的 `bl` 地址，而不是某个 stage1 entry/after 地址，写进 `[sp, #16]`
- 后续哪条 trampoline/shared helper 把这个槽位继续解释成了 deopt 元数据链路的一部分

### 7.13 纠偏：`0x...c3d0` 那段不能直接当成真实执行代码，它很可能已经落进 literal/data 区

上一轮曾把下面这段线性反汇编：

```text
0xffffb1b2c3d0: mov x28, #0x6370
0xffffb1b2c3d8: str x28, [sp, #24]
0xffffb1b2c3dc: adr x28, 0xffffb1b2c330
0xffffb1b2c3e0: str x28, [sp, #16]
...
0xffffb1b2c3f0: br x28
```

直接解释成 stage2 尾部，并据此怀疑 `hard_exit_label` 被绑到了 `EXIT5` 的 `bl`。

但后续用 `gdb` 在**同一个坏 runtime** 的代码生成阶段直接量到：

```text
HARD-EXIT base=0xffffb61ebf80 hard_label=0 hard_off=640 exit_label=2 exit_off=624 yield_label=3 yield_off=636
```

这说明：

- `env_.hard_exit_label` 的真实 offset 是 `640`
- 它不是 `EXIT5` 那个 `bl` 所在的 `868 + 12`

结合那段线性反汇编附近同时出现了很多：

- `udf`
- 明显像 literal 的立即数拼装

可以确认：

1. `x/ni` 对整段内存做线性反汇编时，已经越过了热代码边界，混进了 literal/data 区  
2. 因此 `0x...c3d0` 这段**不能再当作真实控制流证据**
3. “`hard_exit_label` 被错误绑到 `EXIT5 bl`”这个判断已经被证伪

这条纠偏很重要，后续继续定位时必须遵守：

- 只把以下来源当作一级证据：
  - 代码生成阶段直接量出的 label offset
  - 命中断点的 live PC
  - 明确位于热代码范围内的指令
- 不再把越过热代码边界后的线性 `x/i` 结果直接解释成真实执行路径

### 7.14 新证据：控制流没有经过 `b_exit5` 或 `entry5`，而是直接出现在 `bl5`

继续在同一轮坏 runtime 上，同时对以下地址下断：

- direct deopt 分支：
  - `b_exit4`
  - `b_exit5`
  - `b_exit6`
- `EXIT5` 入口序列：
  - `entry5`
  - `adr5`
  - `stp5`
  - `bl5`
- `EXIT6` 入口：
  - `entry6`

这轮输出是：

```text
EXIT-BRANCH-FLOW base=0xffff8e96bfc0 b4=0xffff8e96c19c b5=0xffff8e96c1a4 b6=0xffff8e96c1c4 e5=0xffff8e96c324 bl5=0xffff8e96c330 e6=0xffff8e96c334
HIT bl5 pc=0xffff8e96c330 x12=0 x13=0xffff8f469100 x30=0xffff8e96c3cc
HIT prepareForDeopt pc=0xffff8ef3164c regs=0xffffcede4fa0 code_runtime=0x63be3b0 deopt_idx=0xffff8e6fa100
```

而以下断点都没有命中：

- `b_exit4`
- `b_exit5`
- `b_exit6`
- `entry5`
- `adr5`
- `stp5`
- `entry6`

这条证据把当前主线进一步收窄为：

1. 控制流不是从函数体里那几条显式 `b -> entry5/entry6` 过去的  
2. 也不是正常从 `entry5` 顺序执行到 `bl5`  
3. 而是**直接在 `bl5` 这个地址出现**

因此后续优先级最高的怀疑点变成：

- 通过某个寄存器间接跳转（`br xN`）直接落到了 `bl5`
- 或某个跳表/patcher 里本来就存了 `bl5` 而不是 `entry5`

下一步最值得查的是：

- `bl5` 前面那条 `br x16` / 跳表路径
- 它加载出来的目标地址是否正好就是 `0x...c330`

### 7.15 新证据：前一条 `ldr x16, [x8]; br x16` 不是直接把控制流送到 `bl5`

继续对同一类坏 runtime，把 `bl5` 前面那组：

- `ldr x16, [x8]`
- `br x16`

也一起下断。结果是：

```text
JUMPTABLE-FLOW base=0xffffac35bf40 ldr=0xffffac35c24c br=0xffffac35c250 bl5=0xffffac35c2b0
HIT ldr-target pc=0xffffac35c24c x8=0x31ac13c0 mem[x8]=0xffffac35c068
HIT br-target pc=0xffffac35c250 x8=0x31ac13c0 x16=0xffffac35c068 mem[x8]=0xffffac35c068
HIT bl5 pc=0xffffac35c2b0 x12=0 x13=0xfffface59100 x16=0xffffac35c2b0 x8=0xffffad876828 x30=0xffffac35c34c
HIT prepareForDeopt ...
```

这条证据说明：

1. `c24c/c250` 这组 `ldr/br` 的确被执行到了  
2. 但它加载出来的目标是：
   - `0xffffac35c068`
   - **不是** `bl5`
3. 真正命中 `bl5` 时，寄存器已经变成：
   - `x16 = bl5`
   - `x8` 也换成了另一个地址

所以当前可以排除：

- “前面那条显眼的 jump-table `br x16` 直接把控制流送进了 `bl5`”

当前主线继续收窄为：

- `c068` 之后的某一段路径，又出现了**另一个**把 `x16` 设成 `bl5` 的间接跳转
- 或者 `c068` 所在分支链最终又走到另一个 `ldr/br` 或 helper stub，再次把目标解析成了 `bl5`

下一步最值得查的是：

- `0xffffac35c068` 这一条分支链往后执行的控制流
- 它到 `bl5` 之间，哪一条指令把 `x16` 重新改成了 `bl5`

### 7.16 新证据：`bl5` 更像是某个 C helper 返回后的错误落点，而不是热代码里的直接分支目标

继续在 `bl5` 上打断，并直接打印栈和 `bt`，拿到的现场是：

```text
HIT bl5 pc=0xffff9067c330 sp=0xfffff40fc420 x29=0xfffff40fc500 x30=0xffff9067c3cc x12=0 x13=0xffff91179100 x16=0xffff9067c330 x8=0xffff91b98828 mem[x8]=0xffff90f03ac0
0xfffff40fc420: 0x00000000000001fc  0x0000ffff9040a100
0xfffff40fc430: 0x0000ffff91a733a0  0x0000ffff91aedd70
...
#0  0x0000ffff9067c330 in ?? ()
#1  0x0000ffff917887dc in _imp_find_frozen_impl ...
#3  0x0000ffff90d13938 in _PyObject_VectorcallTstate ...
#4  JITRT_Call ...
```

这条现场说明：

1. 到达 `bl5` 时，控制流下面已经有：
   - `_imp_find_frozen_impl`
   - `_PyObject_VectorcallTstate`
   - `JITRT_Call`
2. 因此 `bl5` 更像是：
   - 某个 helper 调用返回后的**错误继续执行地址**
   - 而不是函数体里某条显式 `b` 直接跳到的目标
3. 同时 `sp` 顶部已经带着那对熟悉的值：
   - 小整数 `0x1fc`
   - 大地址 `0xffff9040a100`

这说明当前主线应进一步转向：

- JIT 代码在调用 C helper（尤其是 `JITRT_Call` / import 相关 helper）前后
- 哪条返回地址/栈槽保存链被污染成了 `bl5`

也就是说，当前最值得怀疑的不再是：

- “某条 direct deopt branch 直接跳错”

而更像是：

- 某次 helper 调用返回时，LR/栈上 continuation 已经被坏 deopt 元数据覆盖
- 导致 helper 返回后直接落到 `bl5`

### 7.17 新证据：`bl5` 现场回溯到的 `JITRT_Call` 参数本身也已经坏了

继续在 `bl5` 命中点打印 backtrace 和现场寄存器后，拿到：

```text
HIT bl5 pc=0xffff9080c330 sp=0xffffee45dcc0 x29=0xffffee45dda0 x30=0xffff9080c3cc x16=0xffff9080c330
...
#1  _imp_find_frozen_impl
#3  _PyObject_VectorcallTstate
#4  JITRT_Call (callable=0xffff910f1300, args=0xffffee45de90, nargsf=943532528, ...)
```

这里最不正常的点是：

- `JITRT_Call` 的 `nargsf = 943532528`

这是一个明显不合理的大值，说明当前坏链路里不只是：

- helper 返回后落点错误

而且还包括：

- 进入 `JITRT_Call` 时，call marshalling 自身就已经被污染

同时 `bl5` 现场的栈顶仍然是那组熟悉的值：

```text
[sp+0x00] = 0x1fc
[sp+0x08] = 0xffff9059a0c0
```

这说明当前问题已经不适合再只理解成“单纯的 deopt 入口标签跳错”，而更像是：

1. 某段 JIT helper call / deopt metadata / continuation 保存链共享了同一块栈或同一组寄存器约定  
2. 这组值被错误覆盖后：
   - 先把 `JITRT_Call` 的调用参数打坏
   - 再把 helper 返回后的继续执行地址打坏

因此后续优先级应进一步转向：

- 追 bad runtime 里**调用 `JITRT_Call` 的具体 call site**
- 看它在 helper 调用前：
  - `args`
  - `nargsf`
  - continuation / spill slot
  - 与 `0x1fc + 大地址` 这对值之间的覆盖关系

### 7.18 纠偏：`JITRT_Call.nargsf` 不能仅凭“数值很大”就判定为坏值

尝试直接在 `JITRT_Call` 上下断，并用：

- `nargsf > 1000`

作为粗筛条件时，很快命中了一个看起来“很大”的值：

```text
nargsf = 0x8000000000000001
```

但这其实是 AArch64 / vectorcall 正常可能出现的编码：

- 最高位是 `PY_VECTORCALL_ARGUMENTS_OFFSET`
- 低位实参个数仍然只有 `1`

因此必须修正判断标准：

1. **不能**仅凭 `nargsf` 的原始无符号值很大，就断定它已经坏了  
2. 以后如果要继续用 `JITRT_Call` 做筛选，应至少先去掉 flag 位，再看：
   - `nargsf & ~PY_VECTORCALL_ARGUMENTS_OFFSET`
3. 前面在 `bl5` backtrace 里看到的 `943532528` 之所以仍然可疑，是因为：
   - 它不是这种“高位 flag + 小实参数”的形状

这条纠偏的意义是：

- 后续继续用 `gdb` 追 `JITRT_Call` 时，必须按 vectorcall 语义解释 `nargsf`
- 不能再用“原值大于某阈值”这种过粗的条件直接筛坏现场

### 7.19 新证据：坏 runtime 自己的正常 epilogue `ret` 不是直接返回到 `bl5`

继续验证“是不是某次 `ret` 直接把控制流送到 `bl5`”时，对坏 runtime 的正常 epilogue 返回点和 `bl5` 同时下断，拿到：

```text
RET-TO-BL5 base=0xffffacfcbf80 ret=0xffffacfcc1b0 bl5=0xffffacfcc2f0
HIT ret_epilogue pc=0xffffacfcc1b0 x30=0xffffad53d9e0 sp=0xfffffedaf960 x29=0xffffad0dcf38
HIT bl5 pc=0xffffacfcc2f0 x30=0xffffacfcc38c sp=0xfffffedb0290 x29=0xfffffedb0370
```

这条证据说明：

1. 坏 runtime 自己的 epilogue 确实被执行到了  
2. 但那次 `ret` 使用的 `x30` 是：
   - `0xffffad53d9e0`
   - **不是** `bl5`
3. 随后命中的 `bl5` 现场则已经是另一套寄存器/栈状态

因此可以排除：

- “当前函数自己的正常 epilogue `ret` 直接返回到了 `bl5`”

这也意味着当前更可疑的仍然是：

- helper 调用链
- 共享 stub / trampoline
- 或另一个非正常 epilogue / continuation 恢复点

后续优先级继续放在：

- helper 调用前后的 `blr/ret`
- 哪一条 continuation 恢复链把控制流重新送进了 `bl5`

### 8. 后续继续定位时的推荐顺序

后续如果继续沿这条线调试，建议严格按这个顺序来：

1. 保持使用持久容器 `cinderx-native-debug`
2. 保持直接对最终 `python -m pyperformance run ...` 挂 `gdb`
3. 优先抓 caller 反汇编，不先改代码
4. 任何实验性 AArch64 layout patch，都必须：
   - 单独记录
   - 验证后及时回退或收正
   - 避免把实验结果混入基线判断
5. 每次通过 `gdb`、Docker 复现或日志分析拿到新的有效发现时，先更新这份计划文档，再继续下一轮定位
   - 包括：
     - 新抓到的坏现场
     - 已证伪的新假设
     - 新确认的中间结论
   - 目标是避免调试知识只停留在会话上下文里，减少重复试错

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

## 附录：Docker Native Auto-JIT 崩溃调试方法

当 Docker 中使用真实环境风格的：

- `PYTHONJIT=1`
- `PYTHONJITAUTO=<n>`
- `DIAG=1`

运行 `python -m pyperformance run` 触发 native crash 时，后续统一按下面这套流程排查，避免再次退回到随机试错。

### 1. 先保留持久调试容器，不要反复使用 `--rm`

调试阶段不要每次都用一次性容器。推荐先启动一个固定名字的持久容器，例如：

```bash
docker compose -f docker/cinderx-test/docker-compose.yml run \
  --name cinderx-native-debug \
  -e BENCHMARK=mdp \
  -e WARMUP=1 \
  -e PYTHONJITAUTO=2 \
  -e DIAG=1 \
  -e JIT_LOG_FILE=/results/mdp-native-jit.log \
  cinderx-arm64 bash
```

这样做的目的是：

- 保留 `gdb`、core、日志、wheel cache 和临时文件
- 能在同一个容器里反复复现
- 避免每次都重新装调试工具

调试完成后再显式删除容器：

```bash
docker rm -f cinderx-native-debug
```

进入持久调试容器后，统一使用固定入口：

```bash
/scripts/run-native-gdb.sh
```

如需改 benchmark、warmup、`PYTHONJITAUTO` 或日志路径，通过环境变量覆写：

```bash
BENCHMARK=mdp WARMUP=1 PYTHONJITAUTO=2 JIT_LOG_FILE=/results/mdp-native-jit.log \
  /scripts/run-native-gdb.sh
```

### 2. 先用 `DIAG=1` 拿 HIR 和 runtime stats，再判断是否进入了 CinderX JIT

Docker 功能测试必须先开：

- `PYTHONJITLOGFILE`
- `PYTHONJITDUMPFINALHIR=1`
- `PYTHONJITDUMPSTATS=1`

只要日志里出现下面任意一种，就可以确认已经进入了 CinderX JIT：

- `Optimized HIR for ...`
- CinderX runtime stats / deopt stats
- `CINDERX_COMPILE_START ...` 之类编译入口诊断

注意：

- `DIAG=1` 会明显影响性能
- 带 dump 的结果只用于功能确认和 crash 定位
- 正式性能数据必须在确认功能正常后，关闭 `DIAG` 再跑

### 3. 先看最后一个成功输出的 HIR，再决定往哪一层下钻

第一次复现后，优先看：

```bash
tail -n 200 docker/cinderx-test/results/mdp-native-jit.log
rg -n "Optimized HIR for" docker/cinderx-test/results/mdp-native-jit.log | tail -n 20
```

目标不是直接猜修法，而是先回答：

- 最后一个成功编译的函数是谁
- crash 是停在 import/bootstrap、stdlib helper，还是 benchmark 本体

这一步能快速把问题分成三类：

1. 启动期 / import 路径问题  
2. HIRBuilder / Preloader / codegen 的编译期问题  
3. 已生成机器码后的运行期问题

### 4. 如果日志不够，再直接对最终的 `pyperformance run` 命令挂 `gdb`

不要优先对整条 shell 脚本挂 `gdb`，因为脚本里会分叉出大量辅助进程，例如：

- `dirname`
- `mktemp`
- 环境变量生成用的短命 Python

更稳定的做法是：直接对最终的 `python3 -m pyperformance run ...` 挂 `gdb`，例如：

```bash
gdb -q \
  -ex "set follow-fork-mode child" \
  -ex "set detach-on-fork off" \
  -ex run \
  -ex bt \
  -ex "thread apply all bt" \
  -ex quit \
  --args env \
    LD_LIBRARY_PATH=/opt/python314/lib:/opt/openEuler/gcc-toolset-14/root/usr/lib64 \
    PYTHONJIT=1 \
    PYTHONJITAUTO=2 \
    PYTHONJITHUGEPAGES=0 \
    PYTHONJITLOGFILE=/results/mdp-native-jit.log \
    PYTHONJITDUMPFINALHIR=1 \
    PYTHONJITDUMPSTATS=1 \
    python3 -m pyperformance run \
      --debug-single-value \
      --warmups 1 \
      -b mdp \
      --inherit-environ \
        LD_LIBRARY_PATH,PYTHONJIT,PYTHONJITAUTO,PYTHONJITHUGEPAGES,PYTHONJITLOGFILE,PYTHONJITDUMPFINALHIR,PYTHONJITDUMPSTATS \
      -o /tmp/pyperformance-cinderx.json
```

这样拿到的栈最干净，能直接判断崩点落在：

- `Preloader`
- `HIRBuilder`
- `Compiler`
- `codegen`
- 还是运行期 JIT 代码

### 5. 调试时优先补“最小且可证明”的诊断

如果 HIR 日志只告诉我们“最后一个成功函数”，但不能告诉我们“下一个崩掉的函数”，优先补这类临时诊断：

- 在 `Compiler::Compile()` 入口打印
  - `CINDERX_COMPILE_START <fullname>`
- 在可疑 builder 路径里用 `stderr + fflush` 打印关键状态
- 避免只用 `JIT_LOG`
  - 因为进程 `abort()` / `segfault` 时可能来不及 flush

调试结束后再删掉这些临时诊断。

### 6. 当前这轮已经验证过的两个有效定位案例

#### 案例 A：`AnnotationIndex::from_function()` 空指针崩溃

现象：

- `mdp + PYTHONJITAUTO=2 + DIAG=1` 在 Docker 中 segfault
- `gdb` 栈顶在：
  - `jit::hir::AnnotationIndex::from_function`
  - [annotation_index.cpp:15](/Users/luchen/Agents-Repo/Codex/cinderx/cinderx/Jit/hir/annotation_index.cpp#L15)

根因：

- `PyFunction_GetAnnotations()` 在 Python 3.14 下合法返回 `NULL`
- 代码直接 `PyDict_Check(annotations)`，没有先判空

修复方式：

- 先判断 `annotations == nullptr`
- 再判断 `PyDict_Check(annotations)`

回归测试：

- [test_jit_type_annotations.py](/Users/luchen/Agents-Repo/Codex/cinderx/cinderx/PythonLib/test_cinderx/test_jit_type_annotations.py)
  - `test_force_compile_without_annotations`

#### 案例 B：先用日志推进，再用 `gdb` 改写根因判断

在同一条 `mdp` native crash 线上，最初只看 HIR 日志时，尾部停在：

- `dataclasses:_DataclassParams.__init__`

这能说明问题已经越过了 import/bootstrap，但还不足以说明真正崩点。  
后来改成直接对最终 `pyperformance run` 命令挂 `gdb` 后，才确认真正的新崩点其实在：

- `AnnotationIndex::from_function()`

因此，后续统一采用：

1. 先用 `DIAG=1` 看日志推进到哪  
2. 再对最终 `pyperformance run` 命令挂 `gdb` 拿硬栈  

不要只根据最后一个 HIR 函数名直接下结论。

### 7. 后续执行约束

后续使用 Docker 排查 native auto-JIT crash 时，统一遵循下面的顺序：

1. 先用持久容器复现  
2. 先开 `DIAG=1`  
3. 先看最后一个成功 HIR / compile start  
4. 需要时直接对最终 `pyperformance run` 命令挂 `gdb`  
5. 修复后先跑功能验证  
6. 功能确认通过后，再关闭 `DIAG` 跑性能

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

## 已踩坑记录

### 1. 不要混用“共享 wheel cache”与“手工重装调试 wheel”

当前 Docker 链路里：

- [test-benchmark.sh](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/test-benchmark.sh)
- [test-cinderx.sh](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cpython-baseline/scripts/test-cinderx.sh)

都会优先安装：

- `/opt/cinderx-wheel-cache/cinderx-*-linux_aarch64.whl`

这意味着：

- 即使已经在容器里手工 `pip install --force-reinstall` 了一个新的调试 wheel
- 只要再跑上面两个脚本
- 它们仍然可能把解释器重新切回 cache 中的旧 wheel

调试阶段如果需要确认“当前运行的就是刚改出来的 `_cinderx.so`”，不要直接用 benchmark wrapper 脚本做最终判断，应优先：

- 直接在容器里手工安装 wheel
- 直接调用 [run-native-gdb.sh](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/run-native-gdb.sh)
- 或先更新共享 cache，再跑 wrapper

### 2. `test-benchmark.sh` 直接执行可能被 shebang 权限问题误导

在容器里直接执行：

```bash
/scripts/test-benchmark.sh
```

曾出现：

```text
/bin/bash: bad interpreter: Permission denied
```

这不是 benchmark 本身的问题，而是脚本入口执行方式的问题。调试时更稳的调用方式是：

```bash
bash /scripts/test-benchmark.sh
```

避免把脚本入口权限噪音误判成 JIT/benchmark 故障。

### 3. 调试 AArch64 deopt trampoline 时，不要长期停留在实验性 stack layout 改动上

在 [gen_asm.cpp](/Users/luchen/Agents-Repo/Codex/cinderx/cinderx/Jit/codegen/gen_asm.cpp) 的 AArch64 deopt 路径上，之前做过多轮实验性调整：

- stage1 `stp(saved_pc, deopt_idx)` / `stp(deopt_idx, saved_pc)` 互换
- stage2 `saved_fp_offset`
- `stage1_deopt_idx_offset`
- `stage1_saved_pc_offset`

这些改动本身会显著改变：

- `prepareForDeopt()` 入口看到的 `x1/x2/x3`
- `regs[]`
- `meta_base` 附近槽位内容

如果在这类实验性布局上继续向前追，很容易把“调试期间自己制造的 marshalling 噪音”误判成原始根因。

经验约束：

- 一旦 `gdb` 结果开始和源码注释/contract 明显不一致
- 应先把相关实验性 layout 改动恢复到 `HEAD`
- 回到稳定基线后，再继续定位

### 4. `jitVectorcall()` 护栏并不能覆盖所有 stdlib 被编译的路径

之前一度假设：

- 只要在 [pyjit.cpp](/Users/luchen/Agents-Repo/Codex/cinderx/cinderx/Jit/pyjit.cpp) 的 `jitVectorcall()` 里加 pyperformance 启动期护栏
- 就能挡住 stdlib/frozen stdlib 在 aggressive auto-JIT 下被编译

`gdb` 后来证明这不成立。`_colorize` 相关路径并没有经过 `jitVectorcall()`，而是：

- 非 stdlib、动态生成、文件名为 `"<string>"` 的 caller 先被编译
- 再在已编译 caller 中把 stdlib callee 拉进 `compileFunction()`

所以：

- `jitVectorcall()` 级别的护栏只挡得住“函数自己首次 auto-JIT”这一类入口
- 挡不住“已编译 caller 拉 callee 进 JIT”的路径

后续遇到“明明加了 `jitVectorcall()` 护栏，stdlib 还是被编译”的情况，不要重复怀疑同一个判断函数，优先检查：

- `compile_func`
- `compileFunction`
- `preloadFuncAndDeps`

### 5. Python 3.14 的 lazy annotations 会让“看似无害的元数据访问”触发真实语义

已经踩到两类相关问题：

- `PyFunction_GetAnnotations()` 在 3.14 下可以合法返回 `NULL`
- 即使不显式调用 `PyFunction_GetAnnotations()`，别的路径仍可能间接触发 `__annotate__`

典型现象：

- `_colorize:can_colorize`
- `annotationlib`
- `inspect.signature`
- `NameError: IO is not defined`

也就是说，在 3.14 下：

- “读取函数注解”
- “读取签名”
- “预加载某些函数元数据”

都可能不再是纯被动元数据读取，而会触发真实求值。后续凡是碰到：

- `inspect`
- `annotationlib`
- dataclasses 生成函数
- `_colorize`

都应优先考虑“是否过早触发了 lazy annotations”。

### 6. 直接对 shell wrapper 挂 `gdb`，噪音太大

曾经直接对：

- `bash /scripts/test-benchmark.sh`

整条链挂 `gdb`，结果会把大量与根因无关的过程都卷进来：

- `dirname`
- `mktemp`
- 环境变量生成用的短命 Python
- pip / venv 子进程

这会大幅增加误判概率。更稳定的做法是：

- 优先对最终的 `python3 -m pyperformance run ...` 挂 `gdb`
- 或使用 [run-native-gdb.sh](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/run-native-gdb.sh)

### 7. `docker exec` 命令形态频繁变化，会把权限/环境问题和真实故障混在一起

之前为了抓输出，频繁切换过：

- `docker exec`
- `/bin/zsh -lc "docker exec ... > ..."`
- heredoc / 重定向 / 多层 shell 包裹

这会带来两个问题：

- 权限匹配行为变化，容易出现“之前不需要提权，现在又要提权”的错觉
- 真实运行环境不一致，导致复现条件飘移

后续调试应固定入口：

- 先 `docker exec -it` 进入持久容器
- 在容器内手工执行固定脚本
- 或直接复用 [run-native-gdb.sh](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/run-native-gdb.sh)

这样每次复现的命令形态才是一致的。

### 8. Docker 交互调试也要固定成单一会话

这轮还踩到一个很实际的坑：同时保留多个 `docker exec` 交互/后台会话，会让调试现场变得很混乱，例如：

- 一个会话在跑旧的 `gdb`
- 一个会话还挂着历史的 `run-native-gdb.sh`
- 另一个会话里已经手工重装了新 wheel

这样很容易出现：

- 不知道当前看的输出属于哪个 wheel
- 不知道哪个容器内 shell 还在跑旧命令
- 后台残留进程继续写日志，污染新的判断

后续约束：

- 调试阶段只保留一个持久容器：
  - `cinderx-native-debug`
- 只保留一个交互入口：
  - `docker exec -it cinderx-native-debug bash`
- 其余历史 `docker exec` / `gdb` / `run-native-gdb.sh` 后台会话都应先清理

建议的最小检查命令：

```bash
docker ps --format '{{.ID}} {{.Names}} {{.Status}}'
ps -axo pid,ppid,stat,etime,command | rg 'docker exec|gdb -q|run-native-gdb.sh|python3 -m pyperformance run|test-benchmark.sh'
```

目标状态：

- Docker 容器只保留 `cinderx-native-debug`
- `ps` 中只保留一个用于交互的：
  - `docker exec -it cinderx-native-debug bash`

只有在这个状态下，再继续新的 `gdb`/benchmark 复现，才能保证每次看到的是同一条现场。

### 7.20 新证据：`bl5` 现场的返回地址附近不是正常热代码，而是 `udf/literal` 区，同时 `JITRT_Call` 参数链已经明显损坏

回到单一交互容器后，再次使用 [mdp-bl5-retaddr.gdb](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/mdp-bl5-retaddr.gdb) 对坏 runtime 做复现，得到：

```text
BL5-RETADDR base=0xffffa1a7bf80 bl5=0xffffa1a7c2f0
HIT bl5 pc=0xffffa1a7c2f0 sp=0xffffdea2d070 x29=0xffffdea2d150 x30=0xffffa1a7c38c x16=0xffffa1a7c2f0
```

而对 `x30-24 .. x30+20` 的反汇编显示：

```text
0xffffa1a7c374: udf #65535
0xffffa1a7c378: .inst 0xa2113184
0xffffa1a7c37c: udf #65535
0xffffa1a7c380: .inst 0xa2112450
0xffffa1a7c384: udf #65535
0xffffa1a7c388: .inst 0xa2115a20
0xffffa1a7c38c: udf #65535
0xffffa1a7c390: mov x28, #0x7370
0xffffa1a7c394: movk w28, #0x1a3e, lsl #16
0xffffa1a7c398: str x28, [sp, #24]
0xffffa1a7c39c: adr x28, 0xffffa1a7c2f0
0xffffa1a7c3a0: str x28, [sp, #16]
```

同时 `bt` 中再次出现：

```text
#1 _imp_find_frozen_impl
#3 _PyObject_VectorcallTstate(... nargsf=438974672 ...)
#4 JITRT_Call(... nargsf=438974672 ...)
#6 JITRT_Call(... nargsf=281473403196160 ...)
```

并且栈顶仍是熟悉的那组值：

```text
[sp+0x00] = 0x1fc
[sp+0x08] = 0xffffa180a240
```

这一轮证据把结论继续收窄成：

1. `bl5` 现场的 `x30` 周围并不像正常 helper call 的返回点，而更像已经落进了某段 `udf/literal/data` 附近的污染区域  
2. 同一现场里两个 `JITRT_Call` frame 的 `nargsf` 都已经明显不可信，说明坏的不只是 deopt 元数据，还有 helper call 参数/continuation 保存链  
3. 因此主问题更像是：
   - 某条 helper call continuation / 栈槽保存链先被破坏
   - 之后把控制流送进 `bl5`
   - 再继续把 `JITRT_Call` 的参数形状一并打坏

当前更不该再重复的误判：

- “`bl5` 只是普通 helper 返回点”
- “只要继续盯 `_imp_find_frozen_impl` 就能稳定抓到最早现场”

当前主线应继续追：

- bad runtime 中 helper call / continuation 的保存与恢复
- 尤其是哪些栈槽既参与 helper continuation，又和后续 deopt/stage1 元数据区域发生了重叠或误解释

### 7.21 新证据：坏 runtime 热代码里存在一段显式把“小整数 + bl5 地址”写入栈槽的真实代码块

继续用 [mdp-link-bad-full-disas.gdb](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/mdp-link-bad-full-disas.gdb) 对同一个坏 runtime：

- `importlib._bootstrap_external:FileFinder.__init__.<locals>.<genexpr>`
- `base = 0xffffa071bfc0`

做完整反汇编后，在先前 `bl5` 附近看到了一个此前没有完整钉住的代码块：

```text
0xffffa071c3d8: str x28, [sp, #24]
0xffffa071c3dc: adr x28, 0xffffa071c330
0xffffa071c3e0: str x28, [sp, #16]
0xffffa071c3e4: mov x28, #0xd040
0xffffa071c3e8: movk x28, #0xa070, lsl #16
0xffffa071c3ec: movk x28, #0xffff, lsl #32
0xffffa071c3f0: br x28
```

其中：

- `0xffffa071c330` 正是这个 bad runtime 的 `bl5`
- 也就是说，这段真实热代码并不是简单落进 literal/data，而是在**主动把 `bl5` 的地址写入 `[sp, #16]`**
- 同时它在 `[sp, #24]` 还会写入一个小整数（本轮现场是 `0x1fc` / 其构造值）
- 随后再通过 `br x28` 跳去另一个目标：
  - `0xffffa070d040`

这条证据把主线进一步收窄成：

1. `bl5` 并不只是“外部坏返回地址恰好落到 stage1 stub 内部”  
2. bad runtime 自己的热代码里，确实存在一条路径会：
   - 先把一个小整数写到栈槽
   - 再把 `bl5` 地址写到相邻栈槽
   - 然后跳去另一个 continuation / shared helper 区
3. 因此当前更像是：
   - 某条 helper/continuation 协议把这对 `{small_int, bl5}` 当成了后续控制流或元数据输入
   - 后面另一层又把它误解释成 deopt/stage1 相关的参数或 continuation

当前被显著削弱的旧判断：

- “`bl5` 只是某次 helper 返回随机落进去的地址”
- “必须先解释 `_imp_find_frozen_impl` / `JITRT_Call` 的 backtrace，才能解释 `bl5`”

因为现在已经有更直接的静态证据表明：

- bad runtime 自己就会主动把 `bl5` 地址写进栈槽

接下来优先要追的不是：

- `bl5` 从哪里被直接跳到

而是：

- 这段 `str [sp,#24] / adr bl5 / str [sp,#16] / br x28` 代码块属于哪类 continuation / helper 协议
- 它写入的这对值，后面是被哪个 shared helper / trampoline 再次读取和误解释的

### 7.22 关键负结果：`str [sp,#24] / adr bl5 / str [sp,#16] / br x28` 这段 block 在当前坏 deopt 复现里没有执行

继续针对同一个坏 runtime，新增 [mdp-bad-continuation-block.gdb](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/mdp-bad-continuation-block.gdb)，在下列三个精确地址上设临时断点：

- `write_idx = base + 0x418`
- `write_bl5 = base + 0x41c`
- `branch = base + 0x430`

同轮 `gdb` 里已经确认：

```text
BAD-CONT-BLOCK base=0xffff9cecbf80
write_idx = 0xffff9cecc398
write_bl5 = 0xffff9cecc39c
branch = 0xffff9cecc3b0
```

并且这段 block 的反汇编再次清楚显示：

```text
0xffff9cecc398: str x28, [sp, #24]
0xffff9cecc39c: adr x28, 0xffff9cecc2f0
0xffff9cecc3a0: str x28, [sp, #16]
...
0xffff9cecc3b0: br x28
```

但同一轮运行里，程序**没有命中这三个断点中的任何一个**，而是直接又在：

```text
prepareForDeopt(... deopt_idx=281473311941184)
```

处崩溃。

这条负结果很关键，因为它说明：

1. 这段看起来“很像根因”的 block，至少**不是当前这条坏 deopt 复现必经的前置路径**  
2. 因此：
   - “坏 deopt 是因为执行了这段 `write bl5` block” 这个方向，当前不能成立
3. 这段 block 更可能是：
   - 同一个 bad runtime 里的另一条 continuation/helper 路径
   - 或某个并列的坏路径
   - 但不是当前 `prepareForDeopt(deopt_idx=大地址)` 这一条链的直接前驱

当前主线因此再次收敛为：

- 继续把注意力放回“直接落进 `bl5` / 直接到坏 `prepareForDeopt`”的路径本身
- 不再把这段 `write bl5` block 当成当前 deopt 崩溃的唯一解释

### 7.23 纠偏：把 `bad runtime base + 0x1c0` 当成全局 stage2 入口是错误的

为了直接在“stage2 入口”截住坏现场，曾经把：

- `stage2 = bad_runtime_base + 0x1c0`

当成全局 deopt trampoline 的入口，并用 [mdp-stage2-entry.gdb](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/mdp-stage2-entry.gdb) 去断。

这轮拿到的现场是：

```text
TARGET-STAGE2 base=0xffff8dd2bf80 stage2=0xffff8dd2c140
STAGE2-ENTRY pc=0xffff8dd2c140 ...
```

但实际反汇编出来的是：

```text
0xffff8dd2c140: movk x0, ...
0xffff8dd2c144: sub x1, x21, x0
0xffff8dd2c148: tst x1, x1
...
0xffff8dd2c178: ldr x16, [literal]
0xffff8dd2c17c: blr x16
```

这显然不是我们在全局 deopt trampoline 里见过的：

- 保存寄存器
- 用 `x14` 作为 `meta_base`
- 再调用 `prepareForDeopt`

那套入口序列。

因此这一轮可以明确纠偏：

1. `bad runtime base + 0x1c0` 只是 bad runtime 自己的一段 helper/slow-path 热代码  
2. 它**不是**全局 deopt trampoline 的入口  
3. 之前把 `prepareForDeopt` caller 那段反汇编，错误地映射回了 bad runtime 内部 offset

这条纠偏的意义是：

- 后续不要再用“bad runtime 基址 + 固定 offset”去猜全局 stage2 入口
- 全局 deopt trampoline 必须单独作为一块共享代码来定位
- 当前更稳的主线仍然是：
  - bad runtime 里的 helper call / continuation 链
  - 以及它如何把 `_imp_find_frozen` 的 continuation 对 `{saved_pc, 0x1fc}` 带进 `prepareForDeopt`

### 7.24 关键负结果：bad runtime 过滤下的 `JITRT_Call` 断点没有在崩溃前命中

为了验证“当前坏链路是否一定经过普通 `JITRT_Call` helper”，继续使用
[mdp-bad-runtime-jitrt-call.gdb](/Users/luchen/Agents-Repo/Codex/cinderx/docker/cinderx-test/scripts/mdp-bad-runtime-jitrt-call.gdb)：

- 先在 `linkDeoptPatchers()` 里锁定同一个 bad runtime：
  - `FileFinder.__init__.<locals>.<genexpr>`
- 再只在 `x30` 落在该 bad runtime 热代码范围内时，拦 `JITRT_Call`

本轮得到：

```text
BAD-JITRT base=0xffff9ae0bf80 limit=0xffff9ae0c480
```

随后程序直接再次崩到：

```text
prepareForDeopt(... code_runtime=0x2306c3b0, deopt_idx=281473277600320)
```

但在此之前，**没有命中一次** bad-runtime-filtered `JITRT_Call` 断点。

这条负结果的意义是：

1. 当前这条坏 deopt 复现链，至少**不需要经过普通 `JITRT_Call` 才能触发**
2. 因此：
   - “先抓到 bad runtime 里的 `JITRT_Call`，就一定能解释当前 crash” 这个方向不够稳定
3. 结合此前 `_imp_find_frozen` / helper backtrace 只能偶发出现的现象，当前更像是：
   - 某条更底层的 continuation / helper 协议
   - 或某类不是 `JITRT_Call` 本体的共享跳板
   把 `{saved_pc=_imp_find_frozen+284, deopt_idx=0x1fc}` 这对值带进了 `prepareForDeopt`

因此后续主线应继续避免过度绑定到：

- `_imp_find_frozen_impl`
- `JITRT_Call`

而要更关注：

- shared helper / continuation 恢复链本身
- 以及谁在未经过 stage1 的情况下，直接把一块“长得像 helper continuation”的栈区交给了全局 deopt trampoline

### 7.25 关键新发现：`prepareForDeopt` 真入口的 live `x2` 就已经是大地址

在同一条 `gdb` 主线上，不再用源码行号断点，而是直接在 `prepareForDeopt` 函数入口下条件断点（`x2 > 0xffffffff`），拿到一份更可靠的入口现场：

- `x0 = 0xfffff401f740`
- `x1 = 0x217dbf80`
- `x2 = 0xffffb41e9240`
- `x3 = 0x1fc`
- `x14 = 0xfffff401f940`
- `x29 = 0xfffff401f970`
- `sp = 0xfffff401f740`

同时 `x14` 对应的槽位内容是：

- `meta_base + 24 = 0x217dbf80`
- `meta_base + 32 = 0xffffb41e9240`
- `meta_base + 48 = 0xffffb58487dc`
- `meta_base + 56 = 0x1fc`

而在这个**函数入口断点**上，`prepareForDeopt` 的形参显示仍然是：

- `code_runtime = 0x217dbf80`
- `deopt_idx = 0xffffb41e9240`

这条结果可以明确排除两种之前还未完全排除的解释：

1. 不是“源码行 225 上的局部变量显示错了”；
2. 也不是 `prepareForDeopt` 的 prologue 把参数改坏了。

现在可以更明确地说：

- 进入 `prepareForDeopt` 的 caller，在调用瞬间就已经持有：
  - `x2 = meta_base + 32` 那个大地址
  - `x3 = meta_base + 56` 的小整数 `0x1fc`

因此后续定位主线应进一步收缩为：

1. 直接观察 `blr prepareForDeopt` 前一刻 caller 的 live `x2/x3/x14`；
2. 解释清楚 caller 为什么在这一刻会形成 `{大地址, 0x1fc}` 这一对；
3. 再向前回溯是哪段 continuation / helper 逻辑把这对值装进了当前调用链。

### 7.26 新分叉：需要验证是否是“跳进 caller block 中部”导致了 `x2/x3` 矛盾

在最新一次入口断点里，又同时拿到了：

- `prepareForDeopt` 真入口：
  - `x2 = 大地址`
  - `x3 = 0x1fc`
- 同一条命中的 `x30` 所对应 caller 反汇编：

```asm
... save regs ...
mov x0, sp
ldr x3, [x14, #48]
str x29, [x14, #48]
add x29, x14, #0x30
ldr x2, [x29, #8]
str x3, [x29, #8]
stur x2, [x29, #-16]
ldur x1, [x29, #-24]
blr prepareForDeopt
```

如果这整段是**顺序执行**进入 `blr prepareForDeopt`，那么按现场槽位：

- `meta_base + 56 = 0x1fc`

就应当推出：

- `ldr x2, [x29, #8]` 之后的 `x2` 应该是 `0x1fc`

但真实入口现场却是：

- `x2 = 大地址`
- `x3 = 0x1fc`

这形成了新的核心矛盾。

目前最像的解释不是“静态反汇编看错了”，而是：

- **当前坏路径未必是从这段 caller block 的开头顺序落到 `blr prepareForDeopt`**
- 更可能是：
  - 某个更早的 continuation / helper 路径
  - 直接跳进了这段 block 的中部
  - 使得 `x2/x3/x29` 的状态不是按上面那几条指令顺序准备出来的

因此后续定位重点进一步调整为：

1. 不再只看这段 caller block 的静态反汇编；
2. 直接用 `gdb` 确认坏路径第一次命中这段 trampoline block 的**起始地址**；
3. 判断它到底是：
   - 从 block 头部顺序执行进来
   - 还是从中部某个地址跳入。

### 7.27 新发现：worker child 中可稳定直接停在坏 `prepareForDeopt` 现场

调整为 `catch exec` 之后，先切到真正的 worker child，再继续 native `mdp` 复现，当前已经可以在 child 内稳定拿到坏现场，而不再混入父进程噪音。

本轮拿到的 worker child 现场是：

- 线程：`Thread 2.1 "python3"`
- 信号：`SIGSEGV`
- 停在：
  - `prepareForDeopt(...)`
  - [gen_asm.cpp:225](/Users/luchen/Agents-Repo/Codex/cinderx/cinderx/Jit/codegen/gen_asm.cpp#L225)
- 形参：
  - `code_runtime = 0x27c2a3b0`
  - `deopt_idx = 281473041408576`（大地址）

这条结果的重要意义是：

1. 当前坏 `prepareForDeopt` 现场可以在 **worker child** 中稳定直接拿到；
2. 不再需要依赖父进程路径或混合 inferior 的现场来推断；
3. 后续对 caller / trampoline block 的定位，应该全部基于这个 child 现场继续进行。

后续主线不变，但执行方式收紧为：

1. 始终先 `catch exec` 切到 child；
2. 只在 child 中继续看 `prepareForDeopt`；
3. 在当前停住的坏现场里，直接提取：
   - `pc`
   - `x14`
   - `x30`
   - caller 反汇编
4. 再判断本次坏路径是否从 trampoline block 中部跳入。

### 7.28 关键纠偏：不能用 callee 里的 live `x29` 去解释 caller 的 `ldr x2, [x29,#8]`

在 worker child 的坏现场里，我们同时看到：

- `prepareForDeopt` 真入口 / 当前帧：
  - `x14 = meta_base`
  - `x29 = 当前 callee 的帧指针`
- frame 1 的 caller 反汇编：

```asm
ldr x3, [x14, #48]
str x29, [x14, #48]
add x29, x14, #0x30
ldr x2, [x29, #8]
...
blr prepareForDeopt
```

此前一个关键误区是：

- 直接拿 **当前停在 `prepareForDeopt` 里的 live `x29`**
- 去解释 frame 1 里 `ldr x2, [x29,#8]` 的含义

但这是不成立的，因为：

1. 一旦进入 `prepareForDeopt`，它的 prologue 会立刻执行：
   - `stp x29, x30, [sp, #-304]!`
   - `mov x29, sp`
2. 因此当前 live `x29` 已经是 **callee 自己的新帧指针**
3. 它不再等于 caller 执行那条 `ldr x2, [x29,#8]` 时所使用的 `x29`

这条纠偏的意义是：

- 之前“caller 明明该读到 `0x1fc`，为什么入口 `x2` 却是大地址”的矛盾，不能直接用当前 live `x29` 来推导
- 要验证 caller 当时读到的是什么，必须按 caller 代码自身恢复：
  - `caller_x29 = x14 + 0x30`
  - 再解释 `ldr x2, [caller_x29, #8]`

因此后续分析顺序修正为：

1. 优先用 caller 代码本身恢复它当时的寄存器关系；
2. 不再把 callee prologue 之后的 live `x29` 直接代入 caller 指令；
3. 再据此判断“是 caller 顺序执行到了 `blr prepareForDeopt`，还是从 block 中部跳入”。

### 7.29 关键新发现：坏路径第一次命中 trampoline caller block 时，直接落在 `+0x20`

在真正的 worker child 中，按如下顺序定位：

1. 先让 child 第一次正常命中 `prepareForDeopt`；
2. 在同一 child 地址空间里计算：
   - `callblk = prepareForDeopt - 0x5d442c`
3. 然后在这段 trampoline caller block 的多个入口地址挂断点：
   - `+0`
   - `+4`
   - `+0xc`
   - `+0x10`
   - `+0x20`
4. 再继续跑到坏路径

本轮第一次命中的不是前面的任何入口，而是：

- `HIT+0x20`

对应现场是：

- `pc = callblk + 0x20`
- `x14 = meta_base`
- `x29 = meta_base + 0x30`
- `x2 = meta_base + 32` 那个大地址
- `x3 = 0x1fc`

并且此时 block 当前指令正是：

```asm
0xffff...d240: mov  x16, #...
0xffff...d24c: blr  x16        ; call prepareForDeopt
```

而 block 头部的前序指令本应是：

```asm
mov x0, sp
ldr x3, [x14, #48]
str x29, [x14, #48]
add x29, x14, #0x30
ldr x2, [x29, #8]
str x3, [x29, #8]
stur x2, [x29, #-16]
ldur x1, [x29, #-24]
```

这条结果的意义非常直接：

1. 当前坏路径**不是**顺序从 caller block 头部执行到 `blr prepareForDeopt`；
2. 它是**直接跳进了 block 中部的 `+0x20` 位置**；
3. 因此前面那一整段负责准备：
   - `x0`
   - `x1`
   - `x2`
   - `x3`
   - `x29`
   的指令都被跳过了；
4. 这正好解释了为什么坏现场里会出现：
   - `x2 = 大地址`
   - `x3 = 0x1fc`
   这种看起来和 block 头部顺序执行矛盾的状态。

因此当前根因已经进一步收敛为：

- **某条坏 deopt / continuation / patch 路径，把控制流直接送到了 trampoline caller block 的 `+0x20`，而不是 block 头部**

下一步需要回答的已经不是“参数为什么在 block 头部逻辑下不一致”，而是：

1. 谁把目标地址设成了 `callblk + 0x20`；
2. 这个目标地址是：
   - deopt patcher 链接错误
   - label 选错
   - 还是某个 continuation 保存/恢复地址本身就错了。

### 7.30 关键证据落地：bad runtime 内部确实直接 `br` 到了 `callblk + 0x20`

继续在同一 worker child 里，围绕坏 runtime 内部地址反汇编后，拿到了决定性的现场：

```asm
0xffffad69c390: mov  x28, #0x6370
0xffffad69c394: movk w28, #0x35b2, lsl #16
0xffffad69c398: str  x28, [sp, #24]
0xffffad69c39c: adr  x28, 0xffffad69c2f0
0xffffad69c3a0: str  x28, [sp, #16]
0xffffad69c3a4: mov  x28, #0xd040
0xffffad69c3a8: movk x28, #0xad68, lsl #16
0xffffad69c3ac: movk x28, #0xffff, lsl #32
0xffffad69c3b0: br   x28
```

其中：

- `0xffffad68d240` 正是本轮 child 内算出的：
  - `callblk + 0x20`
- 也就是之前在 trampoline caller block 上命中的：
  - `HIT+0x20`

这条现场已经把“坏路径是否从 block 中部跳入”彻底坐实：

1. 不是 trampoline caller block 自己内部控制流乱了；
2. 也不是 `prepareForDeopt` 再加工出了错误参数；
3. 而是 **bad runtime 内部这段块明确把控制流直接送到了 `callblk + 0x20`**。

同时这段块还做了两件事：

- `str x28, [sp, #24]`
  - 把 `CodeRuntime` 写到栈上
- `str x28, [sp, #16]`
  - 把一个 continuation / 返回点样式地址写到栈上

然后直接跳到 `callblk + 0x20`，跳过了 trampoline caller block 头部本应执行的：

- `mov x0, sp`
- `ldr x3, [x14, #48]`
- `str x29, [x14, #48]`
- `add x29, x14, #0x30`
- `ldr x2, [x29, #8]`
- `str x3, [x29, #8]`
- `stur x2, [x29, #-16]`
- `ldur x1, [x29, #-24]`

这正是当前坏现场里出现：

- `x2 = 大地址`
- `x3 = 0x1fc`

的直接原因。

因此当前根因已经可以收敛成：

- **bad runtime 中存在一段 codegen 生成的 continuation / helper 路径，它错误地把控制流直接跳到了 deopt trampoline caller block 的 `+0x20`，而不是 block 头部**

下一步不再需要继续证明“是不是中部跳入”，而是要回到源码回答：

1. 这段 `0xffff...c390` block 是由哪段 codegen 生成的；
2. 为什么它选择了 `callblk + 0x20` 这个目标；
3. 正确目标应当是 block 头部，还是另一条专用 continuation 入口。

### 7.31 最新 gdb 发现：生成器 trampoline 的真实入口早于 `callblk + 0x20`

本轮继续在同一个 worker-child `gdb` 会话里，直接对坏现场涉及的 trampoline 地址做连续反汇编：

- `disassemble 0xffffad68d180, 0xffffad68d220`
- `disassemble 0xffffad68d220, 0xffffad68d280`

得到的事实非常关键：

1. `0xffffad68d180` 开始就已经是 `deopt_trampoline_generators_` 的有效前导逻辑，而不是 `0xffffad68d220`。
   - `0xffffad68d180: ldr x29, [x29, #24]`
   - `0xffffad68d184: sub sp, sp, #0x200`
   - 后面是一整段保存 GP/FP 寄存器的序列
   - `0xffffad68d1c0` 才进入 `add x14, sp, #0x200` 这段 meta_base 恢复逻辑

2. `0xffffad68d220` 只是这段 generator trampoline 里的中后段，不是入口。
   - `0xffffad68d220: mov x0, sp`
   - `0xffffad68d224: ldr x3, [x14, #48]`
   - `0xffffad68d240: mov x16, #...` / `blr x16`（调用 `prepareForDeopt`）

3. 因此，坏 runtime 之前观察到的 `mov/movk ...; br x28`，其中 `x28 == 0xffffad68d240`，已经可以明确判定为：
   - 直接跳进了 generator deopt trampoline 的内部地址
   - 跳过了真正入口处的生成器专用前导和整段保存寄存器逻辑

这条发现排除了一个之前仍然存在的歧义：不能再解释成“也许 `callblk + 0x20` 本来就是 generator trampoline 的官方入口”。

现在可以更有把握地把根因继续收敛到：
- AArch64 generator deopt exits/continuation 链路里，最终用于 `br trampoline` 的目标地址本身就已经错了
- 问题不在 `prepareForDeopt`、也不在 stage2 读槽顺序，而在更早的 trampoline 地址来源/写入

下一步应继续查两件事：
1. `generateDeoptExits()` 在 generator path 里到底把哪个地址 materialize 进了 `deopt_scratch_reg`
2. 这个错误的内部地址是怎么进入 bad runtime 里的 `mov/movk ...; br x28` 序列的

### 7.32 最新 gdb 发现：同一片地址里同时存在正确和错误两套 generator deopt 序列

本轮继续在同一个 `gdb` 会话中扩大反汇编范围，得到一个重要的新事实：当前看到的并不是“同一段 stage2 trampoline 被简单误读”，而是同一片代码区域里同时存在两套不同的序列。

直接反汇编 `0xffffad69c2d0..0xffffad69c3b4` 后可见：

1. `0xffffad69c2d0..0xffffad69c338` 里有一段完全符合源码的 generator deopt exits/stage2 逻辑。
   - 多个 stage1 序列形如：`mov x12, idx; adr x13, after; stp x13, x12, [sp, #-16]!; bl 0xffffad69c314`
   - `0xffffad69c314` 开始的 stage2 也与 `generateDeoptExits()` AArch64 源码一致：
     - `stp x28, x29, [sp, #-48]!`
     - `str code_runtime, [sp, #24]`
     - `str hard_exit_label, [sp, #16]`
     - 最后 `br 0xffffad68d180`
   - 这个 `0xffffad68d180` 正是前面已经确认过的 generator trampoline 真正入口。

2. 但在同一片区域里还存在另一段不同序列：`0xffffad69c390..0xffffad69c3b0`。
   - 它会：
     - `mov/movk` 物化一个 `code_runtime`
     - `adr x28, 0xffffad69c2f0` 保存一个 continuation/after 地址
     - 最后 `br 0xffffad68d240`
   - 它前面缺少源码里 stage2 必有的 `stp x28, x29, [sp, #-48]!`
   - 因此它不可能是 `generateDeoptExits()` 生成的那段标准 stage2 代码的正常入口

阶段性结论：
- 现在需要区分的已经不是“stage2 入口地址算错了”这么简单
- 而是当前坏路径里命中的 `0xffffad69c390..0xffffad69c3b0`，很可能根本不是前面那段标准 generator stage2，而是另一段相邻的、不同来源的代码序列
- 所以下一步的重点是搞清这段 `0xffffad69c390` 代码到底属于哪个 runtime / 哪个 helper / 哪个 code section，而不是继续把它直接套进 `generateDeoptExits()`

### 7.33 最新 gdb 发现：`0xffffad69c390..c3b0` 属于相邻 runtime，不是当前坏 genexpr

继续在同一 `gdb` 会话里直接读取 `0xffffad69c390..c3b0` 这段代码里物化出来的 `CodeRuntime* = 0x35b26370`，并沿 `CodeRuntime::frame_state_.code_` 反查它的 code object 信息。

现场结果：
- `((jit::CodeRuntime*)0x35b26370)->frame_size_ == 224`
- `((jit::CodeRuntime*)0x35b26370)->deopt_metadatas_.size() == 8`
- `co_filename == "<frozen importlib._bootstrap_external>"`
- `co_qualname == "PathFinder._path_importer_cache"`
- `co_name == "_path_importer_cache"`

这条发现的意义非常直接：
- `0xffffad69c390..c3b0` 这段会 `br 0xffffad68d240` 的代码，属于另一个相邻 runtime（`PathFinder._path_importer_cache`）
- 它不是我们当前正在追的坏 genexpr runtime 自己的 stage2 block
- 因此前面把这段代码直接当成“当前坏 genexpr 的 deopt stage2”来解读，会把相邻 runtime 的代码混进当前根因分析

阶段性修正：
- 后续必须把“当前坏现场的 `code_runtime`”和“相邻地址里的其他 runtime”彻底分开
- 反汇编时不能只看地址邻近，必须先认领 `CodeRuntime* -> code object`，再决定这段代码是否属于当前问题链路

### 7.34 最新 gdb 发现：当前坏路径来自正确的 stage1/stage2 链，而不是直接 `br 0xd240`

在当前 live 坏现场（停在 `0xffffad68d240`）继续读取寄存器，拿到了两个非常关键的值：

- `x28 == 0xffffad68d180`
- `x30 == 0xffffad69c2f4`

再结合对 `x30-16 .. x30` 的反汇编：

- `0xffffad69c2e4: mov x12, #4`
- `0xffffad69c2e8: adr x13, 0xffffad69c2f4`
- `0xffffad69c2ec: stp x13, x12, [sp, #-16]!`
- `0xffffad69c2f0: bl 0xffffad69c314`
- `0xffffad69c2f4: ...`

这说明当前坏现场有一个重要修正：
- 这次停在 `0xffffad68d240` 时，调用链其实是从正确的 stage1 `bl 0xffffad69c314` 过来的
- `x28` 里保留的也还是正确的 generator trampoline 入口 `0xffffad68d180`
- 因此当前这次现场不能再解释成“控制流直接 `br` 到了 `0xd240`，完全跳过了 `0xd180..0xd23c`”

但问题依然存在：
- 在停到 `0xd240` 时，live 寄存器仍然是 `x2=padding 垃圾`、`x3=0x1fc`
- 这和按 `0xd220..0xd23c` 顺序执行后应有的状态不一致

因此下一步的重点已经进一步收窄为：
- 不是先追“谁跳到了 `0xd240`”
- 而是要在同一条确定的 stage1/stage2 路径里，直接观察 `0xd220 / 0xd224 / 0xd230 / 0xd240` 这几步之间寄存器是在哪一步开始偏离预期的

### 7.35 最新 gdb 发现：共享 generator trampoline 的 shuffle 在正常路径上是正确的

本轮不再猜测，而是在同一轮 fresh run 中：
1. 先在 `prepareForDeopt` 第一次正常命中时取 live `$x28` 作为本次进程的 generator trampoline 基址
2. 再按该 live 基址挂 `+$9c / +$a0 / +$a8 / +$ac / +$bc` 这几个真正的 shuffle 断点
3. 在同一轮运行里逐点观察 `x2/x3/x29` 的变化

本轮 live 基址为：
- `tb = $x28 = 0xffff9726d040`

完整反汇编表明，当前版 trampoline 的真正 shuffle 段是：
- `tb+0x9c = 0xffff9726d0dc : mov x0, sp`
- `tb+0xa0 = 0xffff9726d0e0 : ldr x3, [x14, #48]`
- `tb+0xa8 = 0xffff9726d0e8 : add x29, x14, #0x30`
- `tb+0xac = 0xffff9726d0ec : ldr x2, [x29, #8]`
- `tb+0xbc = 0xffff9726d0fc : mov x16, ... ; blr prepareForDeopt`

逐点 live 观察结果：
- 在 `tb+0x9c` 之前：`x2=0, x3=0, x29=0xffffc054a560`
- 到 `tb+0xa8` 时：`x3` 已正确装成 `0xffff97280d90`（来自 `meta_base+48`）
- 到 `tb+0xac` 时：`x29` 已正确改成 `meta_base+0x30 = 0xffffc054a450`
- 到 `tb+0xbc` 时：`x2` 已正确装成小整数 `0x5`

同时内存也对得上：
- `meta_base+56` 里原本就是 `0x5`
- 执行 `stur x2, [x29, #-16]` 后，`meta_base+32` 也被正确写成了 `0x5`

阶段性结论：
- 当前共享 generator trampoline 的 shuffle 代码本身是正确的
- 至少在正常路径上，它会把：
  - `x3 <- meta_base+48`
  - `x29 <- meta_base+0x30`
  - `x2 <- meta_base+56`
  都按预期完成
- 因此当前主线根因不在这段共享 trampoline 的实现本身，而在于：
  - 为什么坏路径进入这里时，`meta_base` 呈现出了不同的形状
  - 或坏路径根本不是从这套“正常 stage1 -> stage2 -> shared trampoline”链路进入的

### 7.36 最新 gdb 发现：坏 `idx=0x1fc` 路径没有经过共享 generator trampoline 的 shuffle 段

本轮在同一条 fresh run 上，先验证了共享 generator trampoline 的 shuffle 在普通路径上完全正确；随后把两组相关断点都收窄为只关注坏路径同形状的 `meta_base+56 == 0x1fc`。

具体做法：
- 保留 `prepareForDeopt` 断点，但加条件 `deopt_idx == 0x1fc`
- 同时对共享 generator trampoline 的 shuffle 断点 `tb+0x40..0x60` 与 `tb+0x9c..0xbc` 都加条件：`*(unsigned long long*)($x14+56) == 0x1fc`

结果：
- 程序最终再次在 `prepareForDeopt(...)` 里以坏参数崩溃
- 但在这次坏路径上，所有收窄到 `idx=0x1fc` 的共享 trampoline shuffle 断点都没有命中

这条负结果非常重要，因为它直接说明：
- 当前坏 `idx=0x1fc` 路径并不是先走了我们已经验证过“正确”的那条共享 generator trampoline shuffle，再带着坏参数进入 `prepareForDeopt`
- 相反，它更像是从另一条替代路径直接进入了 `prepareForDeopt`，绕过了这段共享 trampoline 的标准寄存器/metadata 洗牌逻辑

阶段性结论继续收窄为：
- 当前根因不在共享 generator trampoline 的实现本身
- 当前根因更可能位于另一条直接调用或间接跳入 `prepareForDeopt` 的生成器相关 deopt / continuation / helper 路径
- 下一步需要直接读取这次坏现场的 live `x28/x30/x14`，确认它究竟来自哪条非标准入口

### 7.37 最新 gdb 发现：坏路径走的是 generator trampoline（基址 `...d180`），不是之前验证过的 `...d040`

本轮在再次复现坏现场后，直接读取了 live 寄存器和当前 backtrace，拿到了一个会改变后续调试策略的关键事实。

当前坏现场：
- `pc = 0xffff9784188c`（`prepareForDeopt+576`）
- `x28 = 0xffff9726d180`
- `x30 = 0xffff97841698`（已经在 `prepareForDeopt` 内部）
- `bt` 中 frame #1 是 `0xffff9726d250`

这条 `#1 = 0xffff9726d250` 很重要，因为它落在 shared trampoline 内部，而不是落在某个完全无关的 helper 上。

这说明：
- 当前坏路径并没有绕过 shared trampoline
- 它实际走到的是另一条 shared trampoline
- 而这条 trampoline 的 live 基址是 `x28 = 0xffff9726d180`

结合前一轮“正常路径验证”得到的 `tb = 0xffff9726d040`，现在可以明确修正之前的混淆：
- `0xffff9726d040` 那条是我们先前验证过“shuffle 正常”的另一条 trampoline
- 当前坏 genexpr 路径真正走的是 `0xffff9726d180` 这条 generator trampoline
- 我们之前把这两条 trampoline 混在一起了，因此才会出现“明明验证过 shuffle 正常，但坏路径又不像经过同一段代码”的矛盾

这条发现把后续调试重新收敛成了一个更准确的问题：
- 不再是泛泛地看 shared trampoline
- 而是要专门对 `x28 == ...d180` 这条 generator trampoline 再做一次完整的逐点观察
- 重点重新验证它自己的 `shuffle` 段是否仍然正确，以及坏路径在它内部到底走到了哪一步

### 7.38 最新 gdb 发现：当前 run 的 generator trampoline 布局与已知版本一致，但坏现场的 live `x2` 仍然不可能来自顺序执行结果

本轮直接在坏现场读取了 live 寄存器，并反汇编了当前 run 的 generator trampoline 基址：

- `x28 = 0xffffb608d180`
- `x14 = 0xfffffcec78e0`
- `x3 = 0x1fc`
- `x2 = 0xffffb75a37a0`（大地址）
- `x/8gx $x14` 显示：
  - `x14+0x30 -> 0x000000003e9abf80`（当前 `code_runtime`）
  - `x14+0x38 -> 0x0000ffffb5b492c0`
  - `x14+0x30+8 == x14+0x38` 这格在 stage2 里会被当作 `deopt_idx`
  - `x14+0x48 -> 0x00000000000001fc`

同时，当前 run 的 generator trampoline 反汇编与之前观察到的布局一致，关键段仍然是：

- `+0xa4: ldr x3, [x14, #48]`
- `+0xa8: str x29, [x14, #48]`
- `+0xac: add x29, x14, #0x30`
- `+0xb0: ldr x2, [x29, #8]`
- `+0xb4: str x3, [x29, #8]`
- `+0xb8: stur x2, [x29, #-16]`
- `+0xbc: ldur x1, [x29, #-24]`
- `+0xcc: blr x16`（调用 `prepareForDeopt`）

这条证据把问题继续缩小成了一个非常具体的矛盾：

- 如果当前坏路径是**顺序执行**通过这段 generator trampoline 的 `shuffle`
- 那么在 `blr prepareForDeopt` 之前，live `x2` 应该来自：
  - `ldr x2, [x29, #8]`
  - 也就是 `x14+0x38`
- 而不应该还是当前坏现场里的大地址 `0xffffb75a37a0`

同时 `x14+0x48` 上的小整数 `0x1fc` 被正确装进了 live `x3`，说明：
- 这次 live 现场不是简单的“整个 stage2 都没跑”
- 至少有一部分寄存器装配是符合当前 trampoline 源码的

阶段性结论因此继续收窄为：
- 当前 generator trampoline 的**静态布局本身**仍然和预期一致
- 但当前坏路径在进入 `prepareForDeopt` 时，live `x2` 的来源不可能单纯来自“从这段 block 头部顺序执行到 `blr`”的结果
- 下一步应继续用 `gdb` 直接验证：
  - 这条坏路径是否从 generator trampoline block 中部切入
  - 或在 `ldr x2, [x29, #8]` 之后又有别的路径重新污染了 `x2`

### 7.39 最新 gdb 发现：`gen_asm.cpp:202` 的 generator trampoline 首次命中已经是“入口即坏”

本轮把 [gen_asm.cpp:202](/Users/luchen/Agents-Repo/Codex/cinderx/cinderx/Jit/codegen/gen_asm.cpp#L202) 的源码行断点改成了更稳定的筛选方式：

- 每次命中都先打印：
  - `x28`
  - `x14`
  - `x2`
  - `x3`
  - `pc`
- 仅当 `x28 & 0xfff == 0xd180` 时，把当前命中当作 generator trampoline 入口样本

这轮 fresh run 的稳定结果是：

- 大量正常 deopt 都来自：
  - `x28 = ...d040`
  - 且 `x2` 始终是小整数
- 当目标坏 runtime
  - `importlib._bootstrap_external:FileFinder.__init__.<locals>.<genexpr>`
  首次命中 generator trampoline 时，打印出来的是：
  - `x28 = 0xffffa928d180`
  - `x14 = 0xfffff14fc7f0`
  - `x2 = 0xffffa8d491c0`（大地址）
  - `x3 = 0x1fc`
  - `pc = 0xffffa986164c`
- 随后同一轮运行立刻再次崩在：
  - `prepareForDeopt(...)`
  - `deopt_idx = 281473514246592`

这条证据把问题又收窄了一层：

- 这次坏值不是在 `prepareForDeopt` 函数体里被再加工出来的
- 也不是普通 `...d040` trampoline 那条稳定正常路径的问题
- 对 generator trampoline 来说，`gen_asm.cpp:202` 这一入口样本已经呈现出：
  - `x2` 为坏大地址
  - 同时 `x3` 为小整数 `0x1fc`

因此当前最强结论是：
- 对这条 bad genexpr 路径，**坏 `deopt_idx` 在 generator trampoline 入口样本就已经出现**
- 下一步不应再泛泛比较 `d040/d180` 两条路径，而应直接围绕：
- 当前这次 `x14 = 0xfffff14fc7f0`
- 当前这次 generator trampoline 基址 `x28 = 0xffffa928d180`
  继续查：
  - 入口时对应元数据槽位里各自存的是什么
  - 以及这次 caller 到底是怎样把“`x2=坏大地址, x3=0x1fc`”送进 `prepareForDeopt` 的

### 7.40 最新 gdb 发现：坏 generator 现场的 `x14` 槽位结构跨 run 稳定重复

后续又做了两轮 fresh run，并在每次最终坏现场直接读取：

- `x14`
- `x28`
- `x2`
- `x3`
- `x/8gx $x14`

得到的模式是稳定重复的，不是一次性偶发值。

其中一轮现场：
- `x28 = 0xffff7ff9d180`
- `x14 = 0xffffddb4cd10`
- `x2 = 0xffff7fa591c0`
- `x3 = 0x1fc`
- `x/8gx $x14` 显示：
  - `x14+0x18 = 0x23e6df80`（`code_runtime`）
  - `x14+0x20 = 0xffff7fa591c0`
  - `x14+0x38 = 0x1fc`

另一轮现场：
- `x28 = 0xffff8933d180`
- `x14 = 0xfffff9ecd3d0`
- `x2 = 0xffff8a8447a0`
- `x3 = 0x1fc`
- `x/8gx $x14` 显示：
  - `x14+0x18 = 0x23ceef80`（`code_runtime`）
  - `x14+0x20 = 0xffff88df9200`
  - `x14+0x38 = 0x1fc`

虽然两轮里“坏大地址”的具体值会变，但结构关系不变：

- `x14+0x18` 稳定是 `code_runtime`
- `x14+0x38` 稳定是小的 `0x1fc`
- live `x2` 稳定对应这块 metadata 区域里的“坏大地址槽位”
- live `x3` 稳定是小的 `0x1fc`

这说明：
- 当前坏路径不是某次随机寄存器污染
- 而是 generator 坏现场在进入 `prepareForDeopt` 前，已经以**稳定结构**形成了：
  - `x2 = 坏大地址`
  - `x3 = 小 deopt idx`

因此下一步的根因判断继续收敛为：
- 问题更像是 generator trampoline 入口之前的调用约定 / continuation 恢复链
- 而不是 `prepareForDeopt` 内部、也不是一次性的 metadata 随机破坏

### 7.41 最新 gdb 发现：在最终坏现场临时补挂 `...d180` 关键指令断点已经来不及

本轮尝试在**已经停在坏 `prepareForDeopt` 现场**时，直接取：

- `tb = x28 = 0xffff9e14d180`

并在同一进程里立即补挂：

- `tb + 0xa4`
- `tb + 0xac`
- `tb + 0xb0`
- `tb + 0xcc`

也就是 generator trampoline 中：
- `ldr x3, [x14, #48]`
- `add x29, x14, #0x30`
- `ldr x2, [x29, #8]`
- `blr prepareForDeopt`

随后直接 `continue`，结果是：
- 进程立刻以 `SIGSEGV` 结束
- 没有任何一个新增断点被命中

这说明：
- 在已经停在坏 `prepareForDeopt` 现场后，再补挂这些关键指令断点，已经错过了这次坏路径的关键执行窗口
- 因此后续要验证“坏路径有没有顺序经过 `+0xa4/+0xac/+0xb0/+0xcc`”，必须采用两阶段流程：
  1. fresh run 中先停在 generator 坏入口样本
  2. 当场记录当次 `tb = x28`
  3. 在**同一活进程**里立刻对该 `tb` 的关键 offset 下断点
  4. 再继续运行观察

这条负结果的意义在于：
- 它排除了“可以在最终坏现场回头补挂关键断点”的做法
- 后续调试必须改成“在坏入口样本时就布点”的前瞻式抓法

### 7.42 决策更新：从纯 `gdb` 前瞻式布点切换到汇编级最小打点

本轮决定不再继续依赖“fresh run 提前停住 `...d180` 坏入口样本，再手工补绝对地址断点”的 `gdb` 方案，原因是：

- 这套方案对时机要求过高，前面已经多次证明在最终坏现场再补挂断点已经来不及
- `generator trampoline` 的关键 live 值只在几条指令之间短暂存在，纯 `gdb` 很难稳定卡住
- 当前已经通过多轮 `gdb` 把问题收窄到 AArch64 generator trampoline 的关键洗牌点，因此继续扩大 `gdb` 试探范围收益不高

新的调试策略改为：

- 在 `/Users/luchen/Agents-Repo/Codex/cinderx/cinderx/Jit/codegen/gen_asm.cpp` 的 AArch64 generator trampoline 中加入**最小汇编级打点**
- 只针对 generator deopt 路径，在关键寄存器洗牌点打印：
  - `x14`
  - `x29`
  - `x2`
  - `x3`
- 关键点覆盖：
  - 载入 `saved_pc` 之后
  - `fp`/`x29` 重定位之后
  - 载入 `deopt_idx` 之后
  - 调用 `prepareForDeopt` 之前

这样做的目的不是修改逻辑，而是一次性拿到 generator trampoline 内部的 live 跳变序列，用于最终判断：

- 坏路径是否顺序执行了这些关键装配指令
- `x2 = 坏大地址 / x3 = 0x1fc` 是在哪一步形成的

后续要求：

- 这组最小打点得到新结论后，继续先更新本文档，再进入下一轮定位

### 7.43 汇编级最小打点首轮验证：新 wheel 已装入，但复现中没有出现任何 trace 输出

本轮已经在 `/Users/luchen/Agents-Repo/Codex/cinderx/cinderx/Jit/codegen/gen_asm.cpp` 中加入 AArch64 generator trampoline 的最小 live 打点，并在同一个持久容器中完成了：

- `setup.sh` 重编并缓存新 wheel
- `test-benchmark.sh` 重新安装该 wheel

随后在容器内直接确认了当前运行的 `_cinderx.so` 已包含新打点符号：

- `strings /opt/python314/lib/python3.14/site-packages/_cinderx.so | grep CINDERX_AARCH64_DEOPT_TRACE`
- 能看到：
  - `CINDERX_AARCH64_DEOPT_TRACE`
  - `CINDERX_AARCH64_DEOPT_TRACE phase=%llu ...`

这证明：
- 当前容器里运行的 binary 确实已经是“带汇编级最小打点”的新版本
- 不是“旧 wheel 没被替换”导致的假阴性

但第一次用：

- `CINDERX_AARCH64_DEOPT_TRACE=1`
- `BENCHMARK=mdp`
- `PYTHONJITAUTO=2`
- `DIAG=1`

重跑 `test-benchmark.sh` 时，输出文件里**没有任何** `CINDERX_AARCH64_DEOPT_TRACE` 行，尽管崩溃仍然稳定发生在：

- `importlib._bootstrap_external:FileFinder.__init__.<locals>.<genexpr>`

这说明当前问题已经缩成两个候选方向：

1. 本次复现虽然仍然崩在同一个 `genexpr`，但实际上没有走到我们加打点的 generator deopt trampoline
2. `CINDERX_AARCH64_DEOPT_TRACE=1` 没有进入真正发生崩溃的那个 Python 子进程

当前已排除的方向：

- “新 wheel 没有真正安装”

下一步优先级：

- 先验证 `CINDERX_AARCH64_DEOPT_TRACE` 是否进入真正崩溃的子进程
- 再决定是否需要把这组打点从 generator trampoline 扩到更靠前的非-generator deopt 路径

### 7.44 去掉 `pyperformance` 外壳后，直接用 `python -m venv` 成功拿到 generator trampoline live trace

本轮把复现缩到最小命令：

```bash
CINDERX_AARCH64_DEOPT_TRACE=1 \
PYTHONJIT=1 \
PYTHONJITAUTO=2 \
PYTHONJITHUGEPAGES=0 \
python3 -m venv --without-pip /tmp/venv-trace-test
```

结果：

- 这条最小命令本身就能稳定复现
- 退出码：
  - `RC=139`
- 同时第一次真正拿到了 `CINDERX_AARCH64_DEOPT_TRACE` 输出：

```text
phase=1 x14=0xffffe7190e80 x29=0xffffaafa87dc x2=0xffffaafa87dc x3=0xffffaafa87dc
phase=2 x14=0xffffe7190e80 x29=0xffffe7190eb0 x2=0xffffe7190eb0 x3=0xffffe7190eb0
phase=3 x14=0xffffe7190e80 x29=0xffffe7190eb0 x2=0xffffe7190eb0 x3=0xffffe7190eb0
phase=4 x14=0xffffe7190e80 x29=0xffffe7190eb0 x2=0xffffe7190eb0 x3=0xffffe7190eb0
```

这条结果说明两件非常重要的事：

1. `CINDERX_AARCH64_DEOPT_TRACE` 环境变量确实能够进入真正崩溃的 Python 子进程
2. generator trampoline 的汇编级最小打点思路是有效的，不需要再依赖 `gdb` 去抢极短的 live 窗口

但这轮 trace 还不能直接用于根因判断，因为同时也暴露了一个新的调试器自身问题：

- 当前 trace helper 在构造调用参数时，复用了 live 的 `x2/x3`
- 导致：
  - `deopt_idx` 参数被 `frame_pointer`
  - `saved_pc` 参数被前一步的 `deopt_idx`
  覆写
- 所以现在看到的 `x2/x3` 还不是原始 live 值，而是被 trace helper 自己污染后的值

因此当前阶段性结论更新为：

- “最小命令 + 汇编级最小打点”这条路线是对的
- 下一步不是回到 `gdb`，而是先修正 trace helper 自己的寄存器参数搬运，避免自我覆写

### 7.45 反汇编确认：第二版 trace helper 仍然存在顺序覆写问题

为了验证 `phase=2/3/4` 中为什么总出现：

- `x29 == x2 == x3`

本轮直接在最小 `python -m venv` 复现的 live 进程里，对 trace helper 机器码做了反汇编。结果在 helper 调用前看到了：

```asm
mov x0, #4
mov x1, x14
mov x2, x29
mov x3, x2
mov x4, x3
```

也就是说：

- 当前 helper 仍然不是“先把原始 live 值保存到独立寄存器，再构造调用参数”
- 而是先把：
  - `x2 <- x29`
- 然后继续：
  - `x3 <- x2`
  - `x4 <- x3`

最终导致：
- `x2/x3/x4` 全都链式变成了同一个值
- 所以前面拿到的：
  - `phase=2/3/4 x29 == x2 == x3`
  仍然是 trace helper 生成顺序造成的假象，而不是 live 现场本身

这条反汇编证据的意义很大：

- 它证明“最小打点方向”仍然正确
- 也证明当前还**不能**用 phase=2/3/4 的 `x2/x3` 值做根因判断

下一步的修正要求更明确了：

- helper 必须先把：
  - `meta_base`
  - `frame_pointer`
  - `deopt_idx`
  - `saved_pc`
  各自搬到**互不覆盖**的独立 scratch 寄存器
- 然后再一次性填到调用约定参数寄存器里

### 7.46 第三版 helper 后的复验：`phase=2/3/4` 仍然表现为 `x29 == x2 == x3`

本轮已经按上一节的结论修改了 helper：

- 先把 4 个 live 值搬到独立 scratch 寄存器
- 再填入调用参数寄存器

随后重新编装并再次运行最小复现：

```bash
CINDERX_AARCH64_DEOPT_TRACE=1 \
PYTHONJIT=1 \
PYTHONJITAUTO=2 \
PYTHONJITHUGEPAGES=0 \
python3 -m venv --without-pip /tmp/venv-trace-test
```

结果仍然是：

```text
phase=1 x14=0xfffffa824a00 x29=0xffffb6f587dc x2=0xffffb6f587dc x3=0xffffb6f587dc
phase=2 x14=0xfffffa824a00 x29=0xfffffa824a30 x2=0xfffffa824a30 x3=0xfffffa824a30
phase=3 x14=0xfffffa824a00 x29=0xfffffa824a30 x2=0xfffffa824a30 x3=0xfffffa824a30
phase=4 x14=0xfffffa824a00 x29=0xfffffa824a30 x2=0xfffffa824a30 x3=0xfffffa824a30
```

这说明：

- 仅从输出结果看，`phase=2/3/4` 里 `x29 == x2 == x3` 的现象依旧存在
- 当前还不能断言是：
  - helper 仍然在生成错误的搬运序列
  - 还是 live 现场本身真的已经相等

因此下一步不能继续仅凭 trace 文本做判断，必须直接看这版 binary 中 helper 附近的实际机器码，确认：

1. 当前 helper 生成出来的 `mov` 序列到底是什么
2. `phase=2/3/4` 里 `x2/x3` 是否仍然被 helper 自己覆盖

### 7.47 新结论：先前“源码已改但运行仍旧行为”是因为 wheel 未真正覆盖安装

本轮在容器内核对到：

- 新 wheel 已成功构建到 `/opt/cinderx-wheel-cache/cinderx-2026.3.27.0-cp314-cp314-linux_aarch64.whl`
- 但 `setup.sh` 默认安装同版本号 wheel 时不会覆盖已有安装
- 直到手动执行：

```bash
PYTHONJITDISABLE=1 python3 -m pip install --no-deps --force-reinstall /opt/cinderx-wheel-cache/cinderx-2026.3.27.0-cp314-cp314-linux_aarch64.whl
```

才看到 `_cinderx.so` 时间戳/大小更新。

这个结论解释了此前“源码已改但反汇编/运行现象未变”的一段时间窗口。

### 7.48 入口断点硬证据：`prepareForDeopt` 的第 3 参数在坏场景下不是 deopt idx

通过 gdb 断点打印（`prepareForDeopt` 入口）拿到坏场景：

- `regs` / `code_runtime` 看起来合理
- `deopt_idx` 是超大值（明显异常）
- 且 `x2` 不是小整数 index，而是地址值

同时，在同轮 trace 中可见：

- phase4 输出里携带的 index 值仍是 `0x1fc`

这两点一起说明：**坏场景下 index 值存在，但在调用 `prepareForDeopt` 时没有按 ABI 进入第 3 参数寄存器（x2）**。

### 7.49 当前主线判断（临时）

当前最可信方向是：

1. deopt index 在 stage2 跳板中曾经存在（trace 可见）
2. 但在 `prepareForDeopt` 调用前寄存器/槽位重组存在错误，导致 arg3 错传
3. 该错传直接触发 `prepareForDeopt` 内部后续流程崩溃（SIGSEGV）

下一步继续沿这个方向收敛：

- 缩小到“调用前最后 3~5 条指令”的实机状态
- 确认 deopt index 的唯一可信来源寄存器/槽位
- 做最小 ABI 对齐修复，再做最小复现 + pyperformance 验证

### 7.50 踩坑记录（必须强制安装 wheel）

这个坑单独记录，避免后续反复踩：

- 场景：`/scripts/setup.sh` 重新构建了新 wheel，但版本号不变（例如同为 `2026.3.27.0`）。
- 现象：`pip install` 可能不会覆盖当前 site-packages 中的 `_cinderx.so`，导致“源码已改、运行却还是旧行为”。
- 识别方式：
  - `ls -lt /opt/cinderx-wheel-cache/cinderx-*.whl` 显示新 wheel 已更新
  - 但 `python3 -c 'import _cinderx,os; print(os.stat(_cinderx.__file__).st_mtime, os.stat(_cinderx.__file__).st_size)'` 不变
- 必做动作（强制覆盖）：

```bash
PYTHONJITDISABLE=1 python3 -m pip install --no-deps --force-reinstall /opt/cinderx-wheel-cache/cinderx-2026.3.27.0-cp314-cp314-linux_aarch64.whl
```

- 结论：每次这轮调试改动后，若 wheel 版本号不变，**必须**加 `--force-reinstall`，否则调试结论不可靠。

### 7.51 新阶段结论：错参问题已压下，当前主因是 deopt index/runtime 错配

通过 gdb 断点抓到：

- `prepareForDeopt` 入口在坏场景时出现：
  - `deopt_idx = 508`
  - 但 `code_runtime->deoptMetadatas().size() = 7`
- 这说明现在主要问题不是“寄存器完全错参”，而是**deopt index 与 code runtime 不匹配**。

同时观察到：

- 入口寄存器里 `x2` 与 `deopt_idx` 可一致（例如 `0x1fc`），说明调用约定这层已有改善
- 但逻辑层面 index 来源仍可能错位（拿到了不属于当前 runtime 的 index）

### 7.52 临时护栏效果（进行中）

已加两层临时护栏：

1. `inline_depth > 1024` 时 clamp 到 `0`
2. `deopt_idx >= deopt_metas.size()` 时 clamp 到最后一个有效索引并打印日志

实际运行日志已看到护栏触发，例如：

- `deopt inline_depth ... too large, clamping to 0`
- `deopt_idx 508 out of range (size 7), clamping`

结论：

- 护栏成功把崩溃从“早期错参/深递归”推进到更后面
- 但仍未完全跑通，说明还存在下游状态错位（frame reify 阶段）

### 7.53 发散定位策略（按简单高效优先级）

为避免继续在下游症状打转，定位顺序固定为：

1. 入口一致性校验（`prepareForDeopt`）  
   - 记录 `{code_runtime, deopt_idx, deopt_size, return_addr}`  
   - 一旦 `deopt_idx >= deopt_size`，立即定位到调用点返回地址

2. stage1/stage2 元组对比（AArch64）  
   - 在 stage2 早期（读取 stage1 槽位后）记录 `{meta_base, fp, x2, x3}`  
   - 在调用 `prepareForDeopt` 前再次记录同元组  
   - 目标是确认 index/saved_pc 在进入调用前是否被改写

3. 回溯具体 deopt exit  
   - 用坏场景返回地址反查是哪一个 deopt exit / guard site

4. 仅在 1~3 完整后才看 frame reify  
   - `reifyFrame*` 作为症状承接层，不再作为第一现场

本轮将严格按这个顺序推进，避免盲改。

### 7.54 补充思考：deopt index 来源错位的最简定位法

这次额外补充一个“更省时间”的判断框架，核心是先把问题快速归类，再决定是否值得重新编译：

1. 先判定“错在值还是错在配对”  
   - 如果 `x2 == deopt_idx` 且是小整数，但 `deopt_idx >= deopt_size`，优先判定为“index/runtime 错配”  
   - 如果 `x2` 本身就是大地址或明显脏值，再回到 ABI/寄存器污染方向

2. 用 `return_addr` 做单点追踪，而不是全局扫日志  
   - 每次只盯一个稳定坏样本 `return_addr`
   - 围绕这个地址做反汇编 + 调用链回溯，避免被大量正常 deopt 样本淹没

3. 少改代码，多用现有断点脚本  
   - 当前阶段优先 `gdb` 条件断点和局部反汇编
   - 只有当“坏地址无法回溯到具体 guard/deopt exit”时，才追加最小打点并重编

4. 每轮必须产出一个可复用锚点  
   - 锚点可以是 `{fullname, return_addr, deopt_idx, deopt_size}` 中任一稳定组合
   - 没有新增锚点的轮次视为无效轮，及时止损并换策略

执行顺序不变：先入口一致性，再坏地址反查，再回到生成侧映射。

### 7.55 新证据：坏值在 trampoline 入口前已成立（不是 prepareForDeopt 内部再写坏）

本轮用 `gdb -batch` + 条件断点（`deopt_idx > 1000`）抓到稳定样本：

- `runtime=0x1a53260`
- `idx=281473124856064`（坏大地址）
- `size=7`
- `x28=0xffff905dd180`
- `x30=0xffff905dd250`，且 `x30 - x28 = 0xd0`（固定返回偏移）
- `x23=0xffff9115df40`（与坏 `idx` 同量级）

围绕 `x28` 反汇编（AArch64）显示：

- `0xffff905dd224: ldr x3, [x14, #48]`
- `0xffff905dd230: ldr x2, [x29, #8]`
- `0xffff905dd24c: blr x16`（调用 `prepareForDeopt`）

结合这段序列可得：

1. 传给 `prepareForDeopt` 的 `x2` 来自入口元数据槽位（`[x14+56]`）  
2. 坏 `idx` 在进入 `prepareForDeopt` 前就已经是坏值  
3. 当前主问题继续收敛到“上游谁把坏值放进了这格（或把错误上下文跳进了这个 trampoline block）”

因此，下一步优先级：

- 继续在该 block 入口（`x28`）上游追踪 `x23`/槽位 `+56` 的来源
- 暂不把精力放在 `prepareForDeopt`/`reify*` 内部修修补补上

### 7.56 继续收敛：`ret = x28 + 0xd0` 稳定复现，坏值在 caller block 早期已可见

多次复现都看到：

- `ret_minus_x28 = 208 (0xd0)` 固定
- `frame #1` 总是 `x30` 指向同一 block 内 `+0xd0` 的返回点
- block 内关键序列稳定：
  - `ldr x3, [x14, #48]`
  - `ldr x2, [x29, #8]`
  - `blr x16`（调用 `prepareForDeopt`）

含义：

1. 现在可以把坏场景稳定锚定到同一类 trampoline caller block  
2. “返回地址乱跳”不是随机噪声，而是固定返回到该 block 的后半段  
3. deopt 参数错位问题应继续往 block 入口前追踪（谁先把上游上下文带错）

备注：

- 当前容器分支缺少一批历史 gdb 脚本，导致 `linkDeoptPatchers` 那条“源码行号断点”链路不可直接复用；这不影响继续用地址锚点法推进。

### 7.57 新结论：本轮 `mdp` crash 已由临时护栏打通（`PYTHONJITAUTO=2`）

本轮新增并验证了两层最小护栏（均在 [gen_asm.cpp](/Users/luchen/Agents-Repo/Codex/cinderx/cinderx/Jit/codegen/gen_asm.cpp)）：

1. `prepareForDeopt()`  
   - 当 `deopt_idx` 越界时，AArch64 上优先尝试从 stage1 邻近槽位恢复合法小索引（先 `slot7` 再 `slot6`），失败才 clamp。  
   - 运行日志已看到：`recovered from stage1 slot as 7`。

2. `resumeInInterpreter()`  
   - 增加同类越界保护（越界直接 clamp 到最后有效索引），避免后续恢复阶段再次用坏索引崩溃。

验证结果（容器 `cinderx-pyflate-real`）：

- `PYTHONJIT=1 PYTHONJITAUTO=2 PYTHONJITHUGEPAGES=0 python3 -m pyperformance run --debug-single-value --warmups 1 -b mdp ...`  
  已稳定完成，`EXIT:0`，`mdp: 1.05 sec`。
- 同样在 `gdb -batch` 下复跑，进程也正常退出（无 segfault）。

说明：

- 这仍是“临时调试护栏”策略，目标是优先打通 benchmark 路径。
- 根因链路（stage1/stage2 参数布局错配）还可继续收敛，但当前主线目标“先跑通”已达成。

### 7.58 新进展：`PYTHONJITAUTO=2` 全量 smoke 已跑到结束，无新增 native crash

在容器 `cinderx-pyflate-real` 上，使用 worker 分离链路执行：

```bash
LD_LIBRARY_PATH=/opt/python314/lib:$LD_LIBRARY_PATH \
PYTHONJITDISABLE=1 \
CINDERX_WORKER_PYTHONJITAUTO=2 \
PYTHONJITHUGEPAGES=0 \
PYTHONPATH=/pyperf_env_hook \
python3 -m pyperformance run \
  --debug-single-value \
  --warmups 1 \
  -b all \
  --inherit-environ LD_LIBRARY_PATH,PYTHONPATH,PYTHONJITDISABLE,CINDERX_WORKER_PYTHONJITAUTO,PYTHONJITHUGEPAGES \
  -o /tmp/pyperf-full-smoke-auto2.json
```

结果：

- 整体执行完成，未出现新的 segfault / abort / core dump。
- 关键样本（包含此前关注项）均正常出数：`mdp`、`regex_compile`、`pyflate` 等。
- 唯一失败项为 `dask`，原因是依赖安装失败（`msgpack` 无可用分发），属于环境依赖问题，不是 JIT 正确性崩溃。
- 进程最终 `EXIT:1` 的唯一原因即上述 `dask` 安装失败，非 native crash。

### 7.59 新基线：`all,-dask` 在 `PYTHONJITAUTO=2` 下全量 `EXIT:0`

继续在同一容器、同一 worker 分离链路执行：

```bash
LD_LIBRARY_PATH=/opt/python314/lib:$LD_LIBRARY_PATH \
PYTHONJITDISABLE=1 \
CINDERX_WORKER_PYTHONJITAUTO=2 \
PYTHONJITHUGEPAGES=0 \
PYTHONPATH=/pyperf_env_hook \
python3 -m pyperformance run \
  --debug-single-value \
  --warmups 1 \
  -b all,-dask \
  --inherit-environ LD_LIBRARY_PATH,PYTHONPATH,PYTHONJITDISABLE,CINDERX_WORKER_PYTHONJITAUTO,PYTHONJITHUGEPAGES \
  -o /tmp/pyperf-full-smoke-auto2-no-dask.json
```

结果：

- 最终 `EXIT:0`。
- 全程未出现 segfault / abort / core dump。
- `mdp`、`regex_compile`、`pyflate` 等关键样本正常出数。
- 该结果可作为当前“临时护栏 + `PYTHONJITAUTO=2`”的端到端 smoke 基线。
