# afc7de79: Make hot/cold splitting work on ARM

## 元信息

- Commit: `afc7de79e57b56b494477f6e12cef636d6ec6577`
- Date: 2026-04-09
- Author: Dino Viehland
- Reviewer: Kevin Newton
- Layer: code allocator / hot-cold layout / ARM branch displacement
- Changed files:
  - `cinderx/Jit/code_allocator.cpp`
  - `cinderx/Jit/code_allocator.h`
  - `cinderx/Jit/pyjit.cpp`

## Commit Message 要点

hot/cold splitting 在 ARM 上会产生大量 `InvalidDisplacement`。如果用 `PYTHONJITDEBUG=1 PYTHONJITALL=1`，会看到很多 methods 因 displacement 问题没有 JIT 成功。`test_max_code_size_slow` 也会暴露，因为 JIT 无法达到预期 maximum code size。

这个 commit 更新 allocator，确保 hot 和 cold pages 都在 branch 可达范围内。

## 优化形状

hot/cold splitting 的目标通常是：

```text
hot path contiguous and cache-friendly
cold/deopt/slow path separated
```

但 ARM64 branch range 有限制。如果 cold code page 离 hot code 太远，branch/call displacement 无法 encode，最终不是慢一点，而是直接无法生成合法代码。

新形状：

```text
allocate hot and cold pages within ARM reachable range
preserve hot/cold split
avoid InvalidDisplacement
keep methods JIT-able
```

## 代码实现 Review

`code_allocator.cpp/h` 是核心。阅读时要看 allocator 如何选择 page，如何判断 range，以及 hot/cold sections 是否共享某种 allocation group。`pyjit.cpp` 的改动通常是接入 allocator behavior 或 debug/config 相关。

这个 commit 的关键不是某条 branch instruction，而是 code layout policy。

## 测试与 correctness

message 给了两个验证入口：

- `PYTHONJITDEBUG=1 PYTHONJITALL=1` 观察 InvalidDisplacement；
- `test_max_code_size_slow`。

学习时要把“函数是否 JIT 成功”也当作性能指标。无法 JIT 的函数会退回解释器，benchmark 上表现为大幅 regression 或不稳定。

## ARM64 启发

ARM64 code layout 优化必须考虑 reachability。x86_64 上一些 layout 策略可能因为更灵活的 branch encoding 不出问题；AArch64 上 hot/cold split、literal pool、deopt exits、trampolines 都可能碰到 range 限制。

## 后续追问

- allocator 是否记录 hot-cold distance 统计？
- literal pool 和 hot/cold splitting 是否可能互相影响？
- branch relaxation 是否能兜底所有 out-of-range case？
- code cache fragmentation 是否会让这个问题重新出现？
