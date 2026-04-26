# 59062ec2: Direct switch dispatch for aarch64

## 元信息

- Commit: `59062ec27da3dc43953c8d27ad0bfb98c69dc300`
- Date: 2026-04-15
- Author: Kevin Newton
- Reviewer: Alex Malyshev
- Layer: AArch64 codegen dispatch / compile-time overhead
- Changed file:
  - `cinderx/Jit/codegen/autogen.cpp`

## Commit Message 要点

这个 commit 把 aarch64 的 trie-based instruction dispatch 替换成 direct switch。相邻还有 x86-64 的同类 commit，但这一篇只换 aarch64 侧。

## 优化形状

旧形状：

```text
generated instruction dispatch through trie-like matcher
```

新形状：

```text
direct switch over instruction/opcode/pattern
```

这不是 generated machine code runtime 优化，而是 JIT compile-time/codegen path 优化。它减少 codegen dispatch 的结构复杂度，也让 debugging 更直接。

## 代码实现 Review

changed file 只有 `autogen.cpp`，说明这是 generated/auto-translation dispatch layer 的结构调整。阅读时应关注：

- direct switch 是否保留原有 pattern priority；
- unsupported pattern fallback 是否一致；
- aarch64 与 x86-64 dispatch 是否仍保持语义对齐；
- backend tests 是否覆盖常见 instruction families。

## 测试与 correctness

这类改动的风险不是某个 Python program 结果错，而是某些 rare LIR instruction pattern 匹配到错误 translator 或 fallback。需要靠 backend/LIR tests 覆盖。

## ARM64 启发

JIT 性能包括 compilation speed。ARM64 backend bring-up 后，如果 codegen dispatch 复杂，会拖累 JIT compile time，也增加后续维护成本。direct switch 让新增 ARM64 translation rule 更容易定位。

## 后续追问

- direct switch 后 JIT compilation speed benchmark 是否改善？
- trie-based dispatch 原来是否有 code size 或 branch mispredict 问题？
- autogen rule priority 是否有 snapshot tests？
- ARM64 新增 instruction 时 direct switch 是否更容易 review？
