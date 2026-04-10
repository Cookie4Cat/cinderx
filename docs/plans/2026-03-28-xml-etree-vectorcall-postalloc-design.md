# xml_etree VectorCall Postalloc 根因修复设计说明书


## 2. 背景

在如下配置下运行 `pyperformance` 的 `xml_etree` 基准时，worker 会崩溃：

```bash
PYTHONJITTYPEANNOTATIONGUARDS=1 \
PYTHONJITENABLEJITLISTWILDCARDS=1 \
PYTHONJITAUTO=2 \
PYTHONJITSPECIALIZEDOPCODES=1 \
PYTHONJITENABLEHIRINLINER=1 \
PYTHONJITLISTFILE="/home/jit_list.txt" \
/home/pybin/bin/python3.14 -m pyperformance run \
  --affinity=1 \
  --warmup 3 \
  -b xml_etree \
  --inherit-environ PYTHONPATH,LD_LIBRARY_PATH,PYTHONJITAUTO,\
PYTHONJITENABLEHIRINLINER,PYTHONJITSPECIALIZEDOPCODES,PYTHONJITLISTFILE,\
PYTHONJITENABLEJITLISTWILDCARDS,PYTHONJITTYPEANNOTATIONGUARDS
```
本次目标是定位真实根因并修复，同时不引入用户列出的 benchmark 性能回退。

## 3. 设计目标

1. 修复 `xml_etree` 崩溃根因，而不是继续依赖定向禁编译。
2. 保持 `bm_xml_etree/run_benchmark.py:bench_parse` 可以继续进入 JIT。
3. 不引入用户列出的 benchmark 的统计显著性能负回退。
4. 修改范围尽量小，限定在已确认的错误优化点。

## 4. 非目标

1. 不重写整套 AArch64 postalloc move 优化。
2. 不在 runtime helper 中增加新的 ABI 补丁或 benchmark 特判。
3. 不改变用户的 benchmark 命令、环境变量或 jit-list 文件。

## 5. 根因分析

### 5.1 复现特征

可以用一个更小的 specialized-opcode 复现触发同类崩溃：

```python
def tostring(x):
    return b"x"

def f(mod, x):
    for _ in range(30):
        y = x
    return mod.tostring(y)
```

该函数在 AArch64 上编译后，最终会进入 module attribute 的 `VectorCall` 路径。

### 5.2 现象

HIR 中的 `VectorCall` 形态正常，helper 参数也正确；问题出现在 postalloc 之后的 LIR：

1. 原本应存在一条把 callable 放回 `X0` 的 `Move X0 <- tmp`。
2. 这条 move 被 `optimizeMoveSequence()` 和后续 move 优化错误折叠掉。
3. 结果 `JITRT_Vectorcall` 调用时，`X0` 没有携带 callable，最终走到空指针调用并崩溃。

### 5.3 错误原因

`optimizeMoveSequence()` 会回扫一段非常窄的 copy 链，把：

1. `Move tmp <- retreg`
2. `Move argreg <- tmp`

折叠成：

1. `Move argreg <- retreg`

问题在于它原先只把“有显式 output 的指令”视为 clobber。AArch64 上存在一种零值化指令：

1. `Xor X0, X0`

这条指令会实际覆盖寄存器，但在当前 LIR 表示里没有显式 `output()`。因此回扫逻辑会错误跨过它，继续把后面的 copy 链视为可折叠，等价于跨过真实 clobber 做寄存器传播。

## 6. 方案概述

在 `cinderx/Jit/lir/postalloc.cpp` 中，对 `optimizeMoveSequence()` 的回扫停止条件做最小增强：

1. 识别“无显式 output 的自异或清零”指令。
2. 如果该指令清零的是当前 copy 链涉及的临时寄存器，停止回扫。
3. 如果该指令清零的是返回寄存器，也停止回扫。

这样可以阻止错误地跨越隐藏 clobber 做 copy 链折叠，同时不扩大到其它无 output 指令。

## 7. 详细设计

### 7.1 新增识别函数

新增 `isZeroingXorOnRegister(const Instruction* instr, PhyLocation reg)`：

1. 指令必须是 `Xor`。
2. `output()` 必须为 `None`。
3. 必须恰好有两个输入。
4. 两个输入都必须是同一个物理寄存器 `reg`。

只有同时满足这些条件时，才把该指令视为“隐藏 clobber”。

### 7.2 接入点

修改 `optimizeMoveSequence()` 中的回扫逻辑：

1. 保留原有“遇到显式写入 `tmp` 或 `retreg` 时停止”的规则。
2. 额外检查当前扫描指令是否是对 `tmp` 或 `retreg` 的 zeroing xor。
3. 若命中则立即停止回扫，不再尝试折叠 copy 链。

### 7.3 为什么不用更宽的 clobber 识别

曾测试过把一批“可能隐式写寄存器”的 output-less 指令统一视为 clobber，这虽然也能修复崩溃，但会让 `chaos` 出现约 3% 且统计显著的性能回退。

因此本次最终方案只覆盖已经确认会误伤该 copy 链折叠的 zeroing xor，不做泛化。

## 8. 方案落点

### 8.1 `cinderx/Jit/lir/postalloc.cpp`

这是根因所在：

1. 问题发生在 postalloc copy 链折叠阶段。
2. HIR、call lowering 和 runtime helper 都不是最终错误写点。
3. 在这里修复可以保留原本的 `VectorCall` 生成逻辑，不需要引入额外 ABI 假设。

### 8.2 `cinderx/Jit/pyjit.cpp`

删除此前的 `xml_etree` benchmark 定向禁编译逻辑，恢复正常编译资格判断。

### 8.3 `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`

新增 ARM 回归测试，直接覆盖：

1. specialized module attribute `VectorCall`
2. 经过热身后的 JIT 编译
3. 编译后返回值正确且没有丢失 callable

## 9. 风险评估

### 9.1 主要风险

1. 把零值化 `Xor reg, reg` 识别过宽，可能抑制本来合法的 copy 链折叠。
2. 修复范围过窄，可能遗漏其它“无显式 output 但会 clobber 寄存器”的指令。

### 9.2 风险控制

1. 仅针对 `Xor` 且两个输入同寄存器、且 `output()` 为空的形态。
2. 只在当前 copy 链涉及的两个寄存器上触发停止。
3. 用 `xml_etree` 原始命令验证功能恢复。
4. 用用户指定的 benchmark 集合做 baseline/fix A/B 比较，验证无显著性能负回退。

## 10. 回归测试设计

新增 `test_module_attr_vectorcall_survives_zeroed_return_register()`：

1. 在临时模块中定义 `tostring()` 和 `f(mod, x)`。
2. 通过 `jit.enable_specialized_opcodes()` 和热身触发 module attribute specialized path。
3. 强制编译 `f`。
4. 检查 `VectorCall` HIR opcode 计数至少为 1。
5. 调用结果必须为十六进制字符串 `78`，即 `b"x"`。


## 11. 后续建议

1. 如果后续在 AArch64 LIR 中再引入其它“无显式 output 的寄存器 clobber”指令，应同步审视 `optimizeMoveSequence()` 的停止条件。
2. 若未来要继续泛化这一类修复，应先补充更系统的 postalloc clobber 语义建模，再做更宽的优化。
