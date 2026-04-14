# MDP JIT Gap Analysis Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `pyperformance` 的 `mdp` benchmark 建立一条可重复的系统性归因与优化执行路径，先定位 `CinderX JIT` 相对 `stock CPython 3.14.0 + JIT` 的主要劣化类型，再据此推进第一轮高收益优化，并在报告中给出 HIR 前后对比。

**Architecture:** 先扩展本地诊断与 HIR 提取能力，让 `macOS` 快速迭代链路能直接覆盖 `bm_mdp`；再用这条链路产出按劣化类型分组的报告，并把结果映射到候选 JIT 文件簇；最后仅对排名最高的 1 到 2 类根因进入实现与 ARM Docker 复核，避免在证据不足时大范围试改 JIT。

**Tech Stack:** Python 3.14, pyperformance, CinderX JIT, CPython 3.14 JIT, unittest/pytest, shell scripts, ARM Docker, macOS 本地编译

---

## 文件结构

本计划涉及的文件和职责如下：

- Modify: `scripts/arm/run_local_pyperf_matrix.py`
  责任：把 `mdp` 纳入本地直接跑 benchmark 的矩阵入口。
- Modify: `cinderx/PythonLib/test_cinderx/test_local_pyperf_driver.py`
  责任：覆盖 `mdp` benchmark spec 解析与命令构造。
- Modify: `scripts/arm/bench_pyperf_direct.py`
  责任：补齐 `mdp` 归因所需的导出能力，例如热点函数筛选、HIR dump/HIR 统计元数据输出、可选的函数白名单编译。
- Modify: `scripts/arm/probe_jit_apis.py`
  责任：验证当前本地构建是否支持所需 JIT API，例如 HIR dump、runtime stats、函数级 HIR 统计。
- Create: `docs/superpowers/mdp/reports/2026-03-18-mdp-jit-gap-analysis-report.md`
  责任：沉淀中文归因报告，按劣化类型分组，包含与 `stock CPython JIT` 的对照和 HIR 前后对比。
- Modify: `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
  责任：为最终锁定的首轮优化点补 JIT 回归测试，优先用 HIR opcode 统计或 final HIR 关键片段做断言。
- Candidate Modify: `cinderx/Jit/hir/builder.cpp`
  责任：若根因集中在高层 HIR 形状、特化识别、对象访问或调用链模式识别，这里是首选修改点。
- Candidate Modify: `cinderx/Jit/hir/simplify.cpp`
  责任：若根因集中在 SSA/HIR pass 后仍残留冗余 guard、冗余对象操作、低效控制流，这里是首选修改点。
- Candidate Modify: `cinderx/Jit/lir/generator.cpp`
  责任：若 HIR 已经足够轻但 lowering 后仍过重，需要在此排查。
- Candidate Modify: `cinderx/Jit/codegen/gen_asm.cpp`
  责任：若问题落在最终代码生成层，则在此调整。
- Candidate Modify: `cinderx/Jit/pyjit.cpp`
  责任：若需要补充调试开关、JIT 配置或 dump 行为，则在此修改。

## Chunk 1: 扩展本地 `mdp` 归因入口

### Task 1: 在本地 pyperformance 矩阵入口中加入 `mdp`

**Files:**
- Modify: `scripts/arm/run_local_pyperf_matrix.py`
- Test: `cinderx/PythonLib/test_cinderx/test_local_pyperf_driver.py`

- [ ] **Step 1: 为 `mdp` 写失败测试**

在 `cinderx/PythonLib/test_cinderx/test_local_pyperf_driver.py` 新增一个解析 `mdp` benchmark spec 的测试，断言：

```python
spec = driver.resolve_benchmark_spec(
    pathlib.Path.home() / "Repo" / "pyperformance",
    "mdp",
)
assert spec["bench_func"] == "bench_mdp"
assert str(spec["module_path"]).endswith("bm_mdp/run_benchmark.py")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest cinderx/PythonLib/test_cinderx/test_local_pyperf_driver.py -k mdp -v`
Expected: FAIL with `unsupported benchmark` or missing `mdp` entry

- [ ] **Step 3: 在本地矩阵脚本中加入 `mdp`**

在 `scripts/arm/run_local_pyperf_matrix.py` 的 `BENCHMARK_SPECS` 中加入：

```python
"mdp": {
    "module_relpath": "pyperformance/data-files/benchmarks/bm_mdp/run_benchmark.py",
    "bench_func": "bench_mdp",
    "bench_args_json": "[1]",
},
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m pytest cinderx/PythonLib/test_cinderx/test_local_pyperf_driver.py -k mdp -v`
Expected: PASS

- [ ] **Step 5: 提交这一小步**

```bash
git add scripts/arm/run_local_pyperf_matrix.py cinderx/PythonLib/test_cinderx/test_local_pyperf_driver.py
git commit -m "diag: add mdp benchmark to local pyperf matrix"
```

### Task 2: 为 `mdp` 归因补足直接跑 benchmark 的导出能力

**Files:**
- Modify: `scripts/arm/bench_pyperf_direct.py`
- Test: `cinderx/PythonLib/test_cinderx/test_local_pyperf_driver.py`

- [ ] **Step 1: 为新导出字段写失败测试**

在测试中新增一个最小模块夹具，断言直接跑脚本的输出 JSON 中至少包含：

- `compiled_qualnames`
- `top_deopts`
- `candidate_count`
- `selected_compile_count`

如果计划加入 HIR 统计摘要，也在这里为 `hir_opcode_counts` 或等价字段写失败测试。

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest cinderx/PythonLib/test_cinderx/test_local_pyperf_driver.py -k direct_runner -v`
Expected: FAIL with missing JSON field or missing CLI flag

- [ ] **Step 3: 在 `bench_pyperf_direct.py` 补齐所需导出能力**

最小实现要求：

- 保持现有 `compile_strategy=all/backedge/names`
- 为 `mdp` 归因输出稳定 JSON
- 若当前脚本尚不能导出需要的 HIR 摘要，新增可选参数，例如：

```python
parser.add_argument("--dump-hir-summary", action="store_true")
parser.add_argument("--compile-names", default="")
```

并在有 JIT API 支持时收集：

```python
ops = jit.get_function_hir_opcode_counts(fn)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m pytest cinderx/PythonLib/test_cinderx/test_local_pyperf_driver.py -k 'direct_runner or mdp' -v`
Expected: PASS

- [ ] **Step 5: 提交这一小步**

```bash
git add scripts/arm/bench_pyperf_direct.py cinderx/PythonLib/test_cinderx/test_local_pyperf_driver.py
git commit -m "diag: enrich direct pyperf runner for mdp analysis"
```

### Task 3: 验证本地构建具备所需 JIT 诊断 API

**Files:**
- Modify: `scripts/arm/probe_jit_apis.py`

- [ ] **Step 1: 为 `probe_jit_apis.py` 明确输出格式**

把脚本输出整理成适合人工检查的清单，至少覆盖：

- `get_function_hir_opcode_counts`
- `get_and_clear_runtime_stats`
- `print_hir` 或等价 HIR 导出路径

- [ ] **Step 2: 运行脚本确认当前构建状态**

Run: `python3 scripts/arm/probe_jit_apis.py`
Expected: 打印出本地构建支持的 JIT API 列表

- [ ] **Step 3: 如输出不清晰，再做最小补强**

必要时将输出统一成：

```python
print(json.dumps(results, indent=2, ensure_ascii=False))
```

- [ ] **Step 4: 重新运行脚本确认可读**

Run: `python3 scripts/arm/probe_jit_apis.py`
Expected: JSON 或结构化文本可直接引用到归因笔记中

- [ ] **Step 5: 提交这一小步**

```bash
git add scripts/arm/probe_jit_apis.py
git commit -m "diag: clarify available local JIT probe APIs"
```

## Chunk 2: 完成 `mdp` 系统性归因并写报告

### Task 4: 在 macOS 本地采集 `mdp` 归因基线

**Files:**
- Read: `$HOME/Repo/pyperformance/pyperformance/data-files/benchmarks/bm_mdp/run_benchmark.py`
- Read: `scripts/arm/run_local_pyperf_matrix.py`
- Read: `scripts/arm/bench_pyperf_direct.py`
- Create: `docs/superpowers/mdp/reports/2026-03-18-mdp-jit-gap-analysis-report.md`

- [ ] **Step 1: 跑一轮 `mdp` 本地近似基线**

Run:

```bash
python3 scripts/arm/run_local_pyperf_matrix.py \
  --pyperformance-root "$HOME/Repo/pyperformance" \
  --benchmark mdp \
  --mode baseline \
  --samples 5 \
  --prewarm-runs 1
```

Expected: 输出 `mdp` 的本地近似时间、已编译函数与 deopt 聚合

- [ ] **Step 2: 根据输出整理第一版热点函数清单**

在报告中先记录：

- 关键热点函数
- 哪些函数实际进入 JIT
- 哪些函数拥有明显 deopt 或 HIR 负担

- [ ] **Step 3: 用函数白名单策略缩小关键热点**

Run:

```bash
python3 scripts/arm/bench_pyperf_direct.py \
  --module-path "$HOME/Repo/pyperformance/pyperformance/data-files/benchmarks/bm_mdp/run_benchmark.py" \
  --bench-func bench_mdp \
  --bench-args-json "[1]" \
  --compile-strategy names \
  --compile-names "Battle.evaluate,Battle.getSuccessors,Battle._getSuccessorsB,getCritDist,topoSort" \
  --samples 5 \
  --prewarm-runs 1 \
  --specialized-opcodes
```

Expected: 缩小归因范围，确认首批代表热点

- [ ] **Step 4: 在报告中形成按劣化类型分组的初稿**

至少建立以下章节：

- 对象/容器访问链
- `Fraction` / `defaultdict` 分布路径
- 高阶调用链
- 状态对象流转

- [ ] **Step 5: 提交这一小步**

```bash
git add docs/superpowers/mdp/reports/2026-03-18-mdp-jit-gap-analysis-report.md
git commit -m "docs: add initial mdp local attribution report"
```

### Task 5: 固定 `stock CPython JIT` 与当前 `CinderX JIT` 的正式对照

**Files:**
- Modify: `docs/superpowers/mdp/reports/2026-03-18-mdp-jit-gap-analysis-report.md`

- [ ] **Step 1: 在 ARM Docker 中跑 `stock CPython 3.14.0 + JIT`**

Run: 使用固定容器环境跑 `mdp`，记录正式时间与环境说明
Expected: 得到 `stock CPython JIT` 的可引用结果

- [ ] **Step 2: 在 ARM Docker 中跑当前 `CinderX JIT`**

Run: 使用相同输入与容器口径跑 `mdp`
Expected: 得到当前 `CinderX JIT` 的正式结果

- [ ] **Step 3: 在报告中补齐正式对照表**

报告中加入表格：

```markdown
| Runtime | Time (s) | Relative to stock CPython JIT |
|---------|----------|-------------------------------|
| stock CPython 3.14.0 + JIT | ... | 1.00x |
| current CinderX JIT | ... | ... |
```

- [ ] **Step 4: 用正式结果校验本地热点方向是否一致**

Expected: 确认本地归因没有明显跑偏；若不一致，在报告中单列“本地与 ARM 偏差”

- [ ] **Step 5: 提交这一小步**

```bash
git add docs/superpowers/mdp/reports/2026-03-18-mdp-jit-gap-analysis-report.md
git commit -m "docs: add arm baseline comparison for mdp"
```

### Task 6: 为每类问题补齐 HIR 主证据

**Files:**
- Modify: `docs/superpowers/mdp/reports/2026-03-18-mdp-jit-gap-analysis-report.md`

- [ ] **Step 1: 为每类问题挑 1 到 3 个代表函数**

优先从以下函数中选择：

- `Battle.evaluate`
- `Battle.getSuccessors`
- `Battle._getSuccessorsB`
- `Battle._getSuccessorsC`
- `getCritDist`
- `topoSort`

- [ ] **Step 2: 导出优化前 HIR**

Run: 使用 `PYTHONJITDUMPHIR` / `PYTHONJITDUMPFINALHIR` 或 `print_hir` 路径导出代表函数 HIR
Expected: 获得可粘贴到报告的精简 HIR 片段

- [ ] **Step 3: 在报告中为每类问题建立“HIT 形状”说明**

每一类问题写明：

- 当前 HIR 里重在哪里
- 预期优化后 HIR 应当消失或变轻的指令/路径是什么

- [ ] **Step 4: 对每类问题给出收益优先级**

按：

- 收益潜力
- 证据清晰度
- 实现可控性

三个维度排序

- [ ] **Step 5: 提交这一小步**

```bash
git add docs/superpowers/mdp/reports/2026-03-18-mdp-jit-gap-analysis-report.md
git commit -m "docs: add hir evidence and priority ranking for mdp"
```

## Chunk 3: 实施第一轮高收益优化

### Task 7: 锁定第一轮优化目标与文件簇

**Files:**
- Read: `docs/superpowers/mdp/reports/2026-03-18-mdp-jit-gap-analysis-report.md`
- Candidate Modify: `cinderx/Jit/hir/builder.cpp`
- Candidate Modify: `cinderx/Jit/hir/simplify.cpp`
- Candidate Modify: `cinderx/Jit/lir/generator.cpp`
- Candidate Modify: `cinderx/Jit/codegen/gen_asm.cpp`
- Candidate Modify: `cinderx/Jit/pyjit.cpp`

- [ ] **Step 1: 从报告中选出排名第 1 的劣化类型**

Expected: 选出单一最强根因，不要一上来并行做多个机制

- [ ] **Step 2: 根据根因映射到代码簇**

映射规则：

- 若是 HIR 识别与高层形状问题，优先看 `cinderx/Jit/hir/builder.cpp`
- 若是冗余 HIR/SSA 优化问题，优先看 `cinderx/Jit/hir/simplify.cpp`
- 若是 lowering 过重，优先看 `cinderx/Jit/lir/generator.cpp`
- 若是最终代码生成过重，优先看 `cinderx/Jit/codegen/gen_asm.cpp`
- 若需要调试开关或 dump 行为，补看 `cinderx/Jit/pyjit.cpp`

- [ ] **Step 3: 为该根因写最小回归测试**

优先在 `cinderx/PythonLib/test_cinderx/test_arm_runtime.py` 中新增针对性测试，使用：

```python
counts = cinderjit.get_function_hir_opcode_counts(target_fn)
assert counts.get("LoadAttr", 0) < old_value
```

或通过 `PYTHONJITDUMPFINALHIR=1` 比较关键文本形状。

- [ ] **Step 4: 运行测试确认失败**

Run: `python3 -m pytest cinderx/PythonLib/test_cinderx/test_arm_runtime.py -k mdp -v`
Expected: FAIL，证明回归测试真正卡住当前问题

- [ ] **Step 5: 提交测试骨架**

```bash
git add cinderx/PythonLib/test_cinderx/test_arm_runtime.py
git commit -m "test: add mdp jit regression guard"
```

### Task 8: 实现第一轮优化并验证 HIR 改善

**Files:**
- Modify: `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
- Candidate Modify: `cinderx/Jit/hir/builder.cpp`
- Candidate Modify: `cinderx/Jit/hir/simplify.cpp`
- Candidate Modify: `cinderx/Jit/lir/generator.cpp`
- Candidate Modify: `cinderx/Jit/codegen/gen_asm.cpp`
- Candidate Modify: `cinderx/Jit/pyjit.cpp`

- [ ] **Step 1: 做最小实现**

只改排名最高的单一根因所涉及文件，不顺手夹带其他优化。

- [ ] **Step 2: 运行针对性测试**

Run: `python3 -m pytest cinderx/PythonLib/test_cinderx/test_arm_runtime.py -k mdp -v`
Expected: PASS

- [ ] **Step 3: 重导代表函数 HIR**

Run: 使用与归因阶段相同的 dump 路径导出优化后 HIR
Expected: 报告中定义的“目标 HIR 变化”已经发生

- [ ] **Step 4: 跑 macOS 本地近似验证**

Run:

```bash
python3 scripts/arm/run_local_pyperf_matrix.py \
  --pyperformance-root "$HOME/Repo/pyperformance" \
  --benchmark mdp \
  --mode baseline \
  --samples 5 \
  --prewarm-runs 1
```

Expected: `mdp` 本地近似结果同向改善，且无明显反向退化

- [ ] **Step 5: 提交实现**

```bash
git add cinderx/PythonLib/test_cinderx/test_arm_runtime.py cinderx/Jit/hir/builder.cpp cinderx/Jit/hir/simplify.cpp cinderx/Jit/lir/generator.cpp cinderx/Jit/codegen/gen_asm.cpp cinderx/Jit/pyjit.cpp
git commit -m "jit: optimize primary mdp regression path"
```

### Task 9: ARM Docker 正式复核与报告收尾

**Files:**
- Modify: `docs/superpowers/mdp/reports/2026-03-18-mdp-jit-gap-analysis-report.md`

- [ ] **Step 1: 在 ARM Docker 中复跑优化后的 `CinderX JIT`**

Expected: 获得正式 `mdp` 结果

- [ ] **Step 2: 将优化前后正式结果写入报告**

补齐表格：

```markdown
| Runtime | Time (s) | Note |
|---------|----------|------|
| stock CPython 3.14.0 + JIT | ... | baseline |
| CinderX JIT (before) | ... | pre-opt |
| CinderX JIT (after) | ... | post-opt |
```

- [ ] **Step 3: 在报告中加入优化前后 HIR 对比**

每个已实施的根因至少放：

- 优化前 HIR 片段
- 优化后 HIR 片段
- 变化说明
- 与性能结果的对应关系

- [ ] **Step 4: 给出是否达到目标的结论**

明确回答：

- 是否持平 `1.04s`
- 若未持平，还差哪一类问题最值得继续做

- [ ] **Step 5: 提交报告**

```bash
git add docs/superpowers/mdp/reports/2026-03-18-mdp-jit-gap-analysis-report.md
git commit -m "docs: finalize mdp jit gap analysis report"
```
