# CPython 3.14 Type-Info Coverage Audit

## 目标

`CPython 3.14` 的 adaptive interpreter 会把运行时观察到的类型信息写进 inline cache，并把普通 opcode 改写成 specialized opcode。`CinderX` 在 3.14 上的 JIT 类型信息不再主要来自旧 Cinder 的 shadow code，而是依赖这些 inline cache / specialized bytecode。

这个 audit 的目标是工程化回答：

- CPython 3.14 已经采到了哪些 type-info？
- CinderX bytecode intake 保留了哪些 specialized opcode？
- HIR builder 实际消费了哪些信息？
- 哪些 hot specialization 在进入 HIR 前被 `unspecialize()` 抹平？
- 哪些 specialization 只被用来加 `GuardType`，但没有消费 cache payload？

## 工具

脚本位置：

```bash
cinderx/TestScripts/jit_type_info_coverage_audit.py
```

推荐在 ARM64 服务器上用 CPython 3.14 运行：

```bash
/opt/python-3.14/bin/python3.14 \
  cinderx/TestScripts/jit_type_info_coverage_audit.py \
  --repo-root /path/to/cinderx \
  --output-dir /root/work/cinderx-type-info-audit-20260426/results
```

只跑静态 coverage：

```bash
python cinderx/TestScripts/jit_type_info_coverage_audit.py \
  --skip-dynamic \
  --output-dir build/type-info-audit-static
```

脚本自测：

```bash
python cinderx/TestScripts/jit_type_info_coverage_audit.py --self-test
```

## 输出文件

`cpython314-specializations.json`

- 从运行时 `opcode` 模块读取。
- 记录 `opcode._specializations`、`opcode._specialized_opmap`、`opcode._inline_cache_entries`、`opcode._cache_format`。
- 每个 specialized opcode 都包含 base opcode、cache fields 和信息分类。

`cinderx-static-coverage.json`

- 解析 `BytecodeInstruction::specializedOpcode()` 的 intake 白名单。
- 解析 HIR builder 中所有 `bc_instr.specializedOpcode()` 分支。
- 标记 `intake_status`、`hir_consume_status`、`cache_payload_used` 和 `lost_stage`。

`dynamic-hot-specializations.json`

- 通过 `sys.setprofile` 收集 warm-up 期间执行过的 code object。
- warm-up 后用 `dis.get_instructions(adaptive=True, show_caches=True)` 统计实际出现的 specialized opcode。
- 覆盖 micro workloads、轻量 repo benchmarks、以及 `pathlib/json_loads/regex_compile` 风格 workload。

`type-info-coverage.csv`

- join 后的主表，适合排序和筛选。
- 关键列：
  - `priority`
  - `opcode`
  - `base_opcode`
  - `dynamic_count`
  - `dynamic_weighted_count`
  - `cache_fields`
  - `intake_status`
  - `hir_consume_status`
  - `cache_payload_used`
  - `lost_stage`

`prioritized-gaps.md`

- 面向优化阅读的 top gaps。
- 每个 gap 固定包含 cache 信息、CinderX 当前状态、hot workloads、收益假设、fallback 边界和建议实现入口。
- `dynamic_count` 表示 specialized opcode 的动态位点覆盖，`dynamic_weighted_count` 表示按 `sys.setprofile` 采到的 code object call count 加权后的热度；前者更适合回答 coverage，后者更适合排优化优先级。

## 优先级规则

P0：

- 在动态 workload 中 hot。
- specialized opcode 在 intake 阶段丢失。
- cache payload 含高价值信息，例如 `version`、`keys_version`、`descr`、`func_version`、dict version 或 layout/index 信息。

P1：

- hot，但只做了弱消费。
- 典型情况是只加 `GuardType`，没有使用 inline cache payload。

P2：

- 不 hot 但 cache payload 高价值。
- 或 hot 但当前 coverage 已经有部分利用。

P3：

- 当前 workload 未观察到，或收益/正确性风险暂时不清楚。

## 首轮远端结果

首轮结果目录：

```bash
/root/work/cinderx-type-info-audit-20260426/results
```

运行环境：

- CPython: `/opt/python-3.14/bin/python3.14`
- 源码基线: clean `meta/main`
- dynamic warm-up: `--profiled-runs 1 --warmup-runs 20`

结果概览：

| priority | count |
| --- | ---: |
| P0 | 40 |
| P1 | 21 |
| P2 | 17 |
| P3 | 6 |

Top P0 gaps 包括：

- `LOAD_GLOBAL_MODULE`
- `LOAD_GLOBAL_BUILTIN`
- `CALL_PY_EXACT_ARGS`
- `TO_BOOL_BOOL`
- `TO_BOOL_INT`
- `LOAD_ATTR_INSTANCE_VALUE`
- `STORE_ATTR_INSTANCE_VALUE`
- `LOAD_ATTR_METHOD_WITH_VALUES`
- `LOAD_ATTR_METHOD_NO_DICT`
- `BINARY_OP_SUBSCR_GETITEM`

注意：`LOAD_ATTR_INSTANCE_VALUE` 和 `LOAD_ATTR_METHOD_WITH_VALUES` 已经在单独探索分支中验证过有效，但 clean `meta/main` 上仍会被 audit 正确标成 hot lost-at-intake gap。这说明 audit 能找到这类 3.14 type-info 接入机会。

`TO_BOOL_*` 也已经在单独探索分支中验证过有效：

- commit: `60e7f342d970ad8b48fa96cc0c92e35b766573b5`
- title: `jit: add 3.14 TO_BOOL specialization and branch fastpath`
- 形状：intake 保留 `TO_BOOL_BOOL` / `TO_BOOL_INT` / `TO_BOOL_LIST` / `TO_BOOL_NONE` / `TO_BOOL_STR`，HIR `emitToBool()` 读取 specialized opcode；`TO_BOOL_NONE` 和 `TO_BOOL_BOOL` 可以直接产生常量或复用 bool operand，`TO_BOOL_INT` / `TO_BOOL_LIST` / `TO_BOOL_STR` 先加 exact-type guard 再走已有 truthiness；branch lowering 额外把 `PrimitiveBoxBool` 直接接到 `CondBranch`。
- 启发：这是很好的 “specialized opcode -> HIR semantic shortcut -> branch fastpath” 样板；audit 仍会在 clean `meta/main` 标出它，但后续优化 queue 应把它归类为 already explored。

## 加权远端结果

加权结果目录：

```bash
/root/work/cinderx-type-info-audit-20260426/results-weighted
```

运行参数：

```bash
--profiled-runs 5 --warmup-runs 100
```

加权后 top P0 gaps：

| opcode | sites | weighted |
| --- | ---: | ---: |
| `LOAD_ATTR_INSTANCE_VALUE` | 140 | 6699401 |
| `CALL_PY_EXACT_ARGS` | 74 | 3584020 |
| `TO_BOOL_BOOL` | 46 | 3144679 |
| `LOAD_ATTR_METHOD_WITH_VALUES` | 55 | 3095259 |
| `STORE_ATTR_INSTANCE_VALUE` | 108 | 2807660 |
| `LOAD_GLOBAL_MODULE` | 307 | 2126080 |
| `BINARY_OP_EXTEND` | 34 | 830162 |
| `LOAD_GLOBAL_BUILTIN` | 105 | 249203 |

这个排序和首轮 site-count 排序不完全相同：`LOAD_GLOBAL_MODULE` 的位点最多，但 `CALL_PY_EXACT_ARGS` / `TO_BOOL_BOOL` 的 profile-weight 更靠前。后续选优化点时建议同时看两列：site-count 说明覆盖面，weighted-count 说明当前 workload 下的热度。

## Wiki 已探索记录映射

参考 `Cookie4Cat/cinderx` wiki：

- [CinderX Optimization Notes](https://github.com/Cookie4Cat/cinderx/wiki)
- [JIT-LOAD_ATTR_INSTANCE_VALUE](https://github.com/Cookie4Cat/cinderx/wiki/JIT-LOAD_ATTR_INSTANCE_VALUE)
- [JIT-LOAD_ATTR_METHOD_WITH_VALUES](https://github.com/Cookie4Cat/cinderx/wiki/JIT-LOAD_ATTR_METHOD_WITH_VALUES)
- [JIT-Rebound-Global-Guards](https://github.com/Cookie4Cat/cinderx/wiki/JIT-Rebound-Global-Guards)
- [JIT-BINARY_OP_SUBTRACT_INT](https://github.com/Cookie4Cat/cinderx/wiki/JIT-BINARY_OP_SUBTRACT_INT)
- [JIT-METEOR_CONTEST](https://github.com/Cookie4Cat/cinderx/wiki/JIT-METEOR_CONTEST)

和 P0 gap 的对应关系：

| audit gap / family | wiki 状态 | 说明 |
| --- | --- | --- |
| `LOAD_ATTR_INSTANCE_VALUE` | already optimized | `JIT-LOAD_ATTR_INSTANCE_VALUE` 已接入 CPython 3.14 instance-value attr specialization。 |
| `STORE_ATTR_INSTANCE_VALUE` | already optimized | 同一 wiki 页覆盖 store side，使用 inline-values layout fast path + fallback。 |
| `LOAD_ATTR_METHOD_WITH_VALUES` | already optimized | `JIT-LOAD_ATTR_METHOD_WITH_VALUES` 已接入稳定 method-load specialization。 |
| `TO_BOOL_BOOL` / `TO_BOOL_INT` / `TO_BOOL_LIST` / `TO_BOOL_NONE` / `TO_BOOL_STR` | already optimized | 用户提供的 `60e7f342` 已覆盖 TO_BOOL specialization 和 branch fastpath；当前 wiki 首页还没有单独页面。 |
| `LOAD_GLOBAL_MODULE` / `LOAD_GLOBAL_BUILTIN` | related but not covered | `JIT-Rebound-Global-Guards` 优化的是 existing `LOAD_GLOBAL` guard policy，把会重绑定但 type 稳定的全局从 `GuardIs` 收窄到 `GuardType(exact)`；它不是 CPython 3.14 `LOAD_GLOBAL_MODULE/BUILTIN` specialized opcode intake，也没有消费 module/builtin dict version + index cache payload。 |
| `BINARY_OP_SUBTRACT_INT` | already optimized, not same P0 shape | wiki 记录的是 mixed numeric subtract guard/deopt 策略，对 `raytrace` 有效；它不是当前 P0 的 lost-at-intake gap。 |
| `BINARY_OP_SUBSCR_LIST_SLICE` | already optimized for meteor_contest | `JIT-METEOR_CONTEST` 已接住 list full slice fast path。 |
| `BINARY_SUBSCR_LIST_INT` / `STORE_SUBSCR_LIST_INT` | already optimized for meteor_contest | wiki 记录 exact list/int subscript 与 store-subscript helper；注意 audit 里 CPython 名字可能表现为 `BINARY_OP_SUBSCR_LIST_INT`。 |
| `BINARY_OP_SUBSCR_STR_INT` / `BINARY_OP_SUBSCR_GETITEM` | not covered | meteor_contest 页面没有覆盖 str-int subscript 或 generic `__getitem__` specialization。 |
| `CALL_PY_EXACT_ARGS` and other `CALL_*` | not covered | 当前 wiki 没有 call-family specialization intake 记录。 |

## 下一步建议

用 audit 结果选优化目标时，优先看：

1. `dynamic_count` 和 `dynamic_weighted_count` 都高，或其中一列特别突出。
2. `lost_stage=intake` 或 `cache_payload_used=none/partial`。
3. `cache_fields` 含 `version/keys_version/descr/func_version/index`。
4. 对应 workload 能写 microbenchmark 验证。

排除 wiki / commit 已经验证过的主题后，下一组值得优先看的 gap 是：

- `CALL_PY_EXACT_ARGS`
- `LOAD_GLOBAL_MODULE` / `LOAD_GLOBAL_BUILTIN`
- `CALL_BUILTIN_O` / `CALL_LEN` / `CALL_ISINSTANCE`
- `BINARY_OP_EXTEND`
- `BINARY_OP_SUBSCR_STR_INT` / `BINARY_OP_SUBSCR_GETITEM`

这些都在动态采样中很热，并且 clean `meta/main` 当前会在 intake 阶段丢失 CPython 3.14 已经采到的 cache 信息。`LOAD_ATTR_INSTANCE_VALUE`、`STORE_ATTR_INSTANCE_VALUE`、`LOAD_ATTR_METHOD_WITH_VALUES`、`TO_BOOL_*`、`BINARY_OP_SUBSCR_LIST_SLICE`、`BINARY_SUBSCR_LIST_INT`、`STORE_SUBSCR_LIST_INT` 虽然在 audit 中仍然可能排得很高，但已经有独立验证结果，后续不作为第一批新目标。
