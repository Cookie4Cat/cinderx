# LIR / Codegen

这一层关注 HIR 已经表达出的优化，是否能在 LIR 和 machine code 中保留下来。

## 重点 commits

- `14b48134` Add postalloc rewrite for mov instructions
- `8b98266a` Use opcodes to load/store specific size
- `e9968ea2` Fuse compare + CondBranch into cmp + jcc
- `aca150d2` Use re-writes to avoid scratch register usage w/ immediates
- `8b158d25` Rewrite guard instructions on floating point instructions
- `16c708f8` Add postgen rewrite for Call instruction inputs
- `3a8600fb` Add MovConstPool postgen pass for large duplicate constants
- `8aa963d4` Re-write memory inputs to registers

## 典型问题

- HIR 很干净，但 LIR operand shape 后端不喜欢。
- immediate 太大，导致 movz/movk materialization。
- memory input 出现在不支持 memory operand 的 instruction 上。
- call target 太早被 materialize 到 temporary register。
- compare 结果被物化，而不是直接进入 branch。

## 可复用方法

postalloc / postgen rewrite 是低风险但很实用的工具。它不改变 Python 语义，也不大改 HIR，只修正即将进入 backend 的 instruction shape。
