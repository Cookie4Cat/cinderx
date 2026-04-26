# 3d414b95: Enable inline caching for plain instance attributes

## 元信息

- Commit: `3d414b9505763931ec2e290312c0e3c7a213191c`
- Date: 2026-02-12
- Author: Jacob Bower
- Reviewer: Alper Yoney
- Layer: inline cache / attribute access
- Changed file:
  - `cinderx/Jit/inline_cache.cpp`

## Commit Message 要点

commit message 说之前有一个 early exit 被错误保留下来，导致 plain instance attributes 的 inline caching 没有真正启用。这个 commit 移除那条阻断路径，让后面的 inline-cache setup 逻辑可以执行。

这类 commit 容易被低估，因为 diff 可能很小。但 attribute access 是 Python 性能中心路径，plain instance attribute 又是最常见的对象访问模式之一。

## 优化形状

目标不是改变 attribute 语义，而是在 guard 成立时跳过 generic lookup：

```text
LOAD_ATTR plain instance attr
  -> guard receiver type / dict layout / cache validity
  -> cached offset or cached descriptor path
  -> direct load
  -> deopt or fallback if invalidated
```

在 Python 里，attribute lookup 可能涉及 descriptor protocol、`__getattribute__`、instance dict、type dict、version tags 等。plain instance attribute inline cache 的价值在于：命中时避开这套 generic protocol。

## 代码实现 Review

唯一 changed file 是 `inline_cache.cpp`，说明这是 inline cache control-flow bug/fix，而不是新增 backend lowering。阅读时应关注：

- early exit 原先阻断了哪类 plain instance attr；
- cache fill 时记录哪些 facts；
- invalidation 或 guard failure 时如何 fallback；
- free-threading 或 multi-threaded compilation 下 cache metadata 是否安全。

## 测试与 correctness

这里正确性风险集中在 invalidation：

- class attribute mutation 后 cache 是否失效；
- instance dict shape 变化后是否 fallback；
- descriptor 和 non-descriptor 是否区分；
- subclass/overridden `__getattribute__` 是否被排除；
- free-threading 下缓存状态是否可见。

如果后续要补测试，应该找 plain instance attr、mutating class dict、mutating instance dict、subclass override 这几类。

## CPython 3.14 关系

CPython 3.14 自身也有 attr specialization。CinderX 的 inline cache 如果能 honor CPython specialization facts，就可以减少重复 profiling。这个 commit 属于“把已有 CinderX fast path 真正打开”。

## ARM64 启发

这不是 ARM64-specific，但对 ARM64 很重要：减少 attribute lookup helper call 和 dictionary probing，比优化一两条 ARM64 ALU instruction 更有收益。ARM64 后续可以看 inline cache hit path 的 generated code 是否有多余 load/guard/branch。

## 后续追问

- plain instance attr inline cache 在 fastmark/richards 中命中率如何？
- cache miss/deopt path 是否污染 hot code layout？
- ARM64 上 cached attr load 的 address mode 是否最佳？
- CPython 3.14 `LOAD_ATTR` specialization 与 CinderX inline cache 是否有重复 guard？
