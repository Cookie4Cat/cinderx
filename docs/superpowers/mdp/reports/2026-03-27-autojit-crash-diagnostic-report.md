# 2026-03-27 AutoJIT 崩溃诊断报告（mdp / pyperformance）

## 1. 诊断范围

- 触发方式：`PYTHONJIT=1` + `PYTHONJITAUTO`（主要复现值为 `2`）
- 复现场景：`pyperformance run -b mdp`（warmup=1/3 均可触发）
- 平台：AArch64（openEuler 24.03 LTS SP1，GCC 14 系工具链，Docker/真实机对齐）

## 2. 崩溃点汇总

### 崩溃点 A：`stack.h:19` 断言失败（`!stack.empty()`）

- 现象：
  - core dump，栈在 `jit::Stack<jit::hir::Register*>::pop`
  - 上层常见于 `HIRBuilder::emitAnyCall`
- 触发函数样本：
  - `enum:Flag.__or__`
- 根因判断：
  - `CALL` 翻译阶段栈输入计数与实际栈状态不一致，出现 underflow。
  - 相关上下文里 `LOAD_ATTR_SLOT` / method receiver 语义参与了参数形态变化，放大了计数错配风险。
- 修复/临时屏蔽：
  - 增加最小诊断打点后修正了调用链上的栈处理（当前分支已消除该崩溃主路径）。

### 崩溃点 B：`HIRBuilder::getBlockAtOff` 段错误

- 现象：
  - 崩在 `tryInlineTupleGenexprCall` -> `getBlockAtOff`
  - 函数样本：`dataclasses:_fields_in_init_order`
- 根因判断：
  - 某些字节码形态下 `resume_off` 没有对应 block，release 下解引用 end 迭代器导致崩溃。
- 修复/临时屏蔽：
  - 在 `tryInlineTupleGenexprCall` 增加“找不到 block 则放弃该内联”的护栏，回退通用路径。

### 崩溃点 C：deopt 路径 `deopt_idx` 错位导致崩溃（AArch64 关键问题）

- 现象：
  - `prepareForDeopt()` 入参 `deopt_idx` 为大地址，明显越界。
  - 同时 `code_runtime->deoptMetadatas().size()` 很小（常见 7/8）。
  - 后续在 `reifyLightweightFrames` 或 `resumeInInterpreter` 再次崩溃。
- 根因判断：
  - AArch64 deopt trampoline（stage1/stage2）在特定 generator 相关路径上出现参数槽位错配：
    - 本应传递的小索引，进入 `prepareForDeopt` 时变成“返回地址样式的大值”。
  - 已通过 gdb + 寄存器/反汇编确认：坏值在 `prepareForDeopt` 之前就已成立。
- 修复/临时屏蔽（本轮重点）：
  1. `prepareForDeopt()` 增加 AArch64 越界恢复护栏：
     - 若 `deopt_idx` 越界，优先尝试从 stage1 邻近槽位恢复合法小索引（先 slot7，再 slot6）。
     - 仅恢复失败时再 clamp 到最后有效索引。
  2. `resumeInInterpreter()` 增加同类越界保护：
     - 防止恢复阶段继续用坏索引二次崩溃。
  3. 保留日志用于后续根因收敛：
     - `CINDERX_DEOPT_TRACE_ENTRY`
     - `CINDERX_AARCH64_DEOPT_TRACE`

## 3. 与运行环境相关的关键坑位

### 坑位 1：`PYTHONJITHUGEPAGES` 未显式置 0

- 现象：某些环境上 JIT benchmark 不稳定或异常。
- 结论：运行 JIT benchmark 时应显式设置 `PYTHONJITHUGEPAGES=0`（已有既往修复记录）。

### 坑位 2：同版本 wheel 未覆盖

- 现象：源码已改，但行为仍旧（实际加载旧 `_cinderx.so`）。
- 结论：版本号不变时必须强制重装：

```bash
PYTHONJITDISABLE=1 python3 -m pip install --no-deps --force-reinstall /path/to/cinderx-2026.3.27.0-*.whl
```

### 坑位 3：driver/worker 环境变量作用域

- 结论：
  - `PYTHONJITAUTO` 影响当前 Python 进程。
  - 在 `pyperformance` 场景中，worker 是否继承需通过 `--inherit-environ` 或 worker 前缀变量链路明确传递。
  - 若仅 driver 设置，worker 可能未按预期开启 AutoJIT。

## 4. 当前状态（2026-03-27）

- 在容器内，应用上述临时护栏后，以下命令已可稳定跑通：

```bash
PYTHONJIT=1 PYTHONJITAUTO=2 PYTHONJITHUGEPAGES=0 \
python3 -m pyperformance run --debug-single-value --warmups 1 -b mdp \
  --inherit-environ LD_LIBRARY_PATH,PYTHONJIT,PYTHONJITAUTO,PYTHONJITHUGEPAGES
```

- 结果：`EXIT:0`，`mdp` 正常出数（本轮样本约 `1.05 sec`）。

- 同一套护栏下继续执行全量 smoke（`-b all`，`PYTHONJITAUTO=2`）：
  - 无新增 native crash（未出现 segfault / abort / core dump）。
  - `mdp`、`regex_compile`、`pyflate` 等均正常出数。
  - 唯一失败项是 `dask` 依赖安装失败（`msgpack` 无可用分发），属于环境依赖问题。

## 5. 后续建议

1. 把当前护栏作为“临时稳定性补丁”保留，先保障 benchmark 主线可跑。
2. 继续收敛 AArch64 deopt stage1/stage2 的根因，目标是移除恢复性护栏，改为结构性修复。
3. 回归策略固定为两阶段：
   - 功能阶段：开启 deopt/HIR 诊断变量确认路径正确。
   - 性能阶段：关闭重日志变量后再测性能数据。
