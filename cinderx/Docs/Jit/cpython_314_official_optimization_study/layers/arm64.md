# ARM64

这一层关注 AArch64 backend 从 correctness bring-up 到 code quality 的路径。

## 重点 commits

- `d37552a7` aarch64 support
- `47e3a8de` Rewrite lea that requires a temporary to an explicit madd instruction
- `afc7de79` Make hot/cold splitting work on ARM
- `59062ec2` Replace trie-based instruction dispatch with direct switch for aarch64
- `aca150d2` Use re-writes to avoid scratch register usage w/ immediates
- `16c708f8` Add postgen rewrite for Call instruction inputs

## 阅读重点

ARM64 的优化经常不是“新增一个 Python fast path”，而是降低已有 fast path 的 backend 成本：

- 减少 scratch register。
- 减少大 immediate materialization。
- 改善 branch / call lowering。
- 改善 block layout。
- 避免不必要的 temporary。

## 验证建议

pyperformance 不一定能看出 backend cleanup 的收益。需要额外看：

- asm dump
- instruction count
- code size
- hot/cold block layout
- register spill/reload
