# d5fa88c3: Don't generate Decrefs for immortal types

## 元信息

- Commit: `d5fa88c3193d84c717b5435e8b1a306da3ea3940`
- Date: 2026-03-26
- Author: Alex Malyshev
- Reviewer: `czardoz`
- Layer: HIR refcount insertion
- Changed files:
  - `cinderx/Jit/hir/refcount_insertion.cpp`
  - `cinderx/RuntimeTests/hir_guard_test.cpp`
  - 多份 `hir_tests/*refcount*` 和 `all_passes*` expected output

## Commit Message 要点

HIR instructions 可以输出 `TBool` 和 `TNoneType`。这些 type 技术上可能 `couldBe(TMortalObject)`，但在 Python 3.12+ 中 bool 和 None 都是 immortal。与其修改 HIR type generator 禁止 `TMortalBool`，官方选择在 refcount insertion pass 中手动识别这些 immortal types，避免生成 `Decref`。

## 优化形状

旧形状：

```text
instr output type couldBe(TMortalObject)
  -> refcount insertion emits Decref
```

新形状：

```text
instr output is known immortal singleton/type
  -> skip Decref
```

这是 refcount traffic elimination。它不会改变 Python object lifetime，因为 immortal object 本来不需要真实 decref。

## 代码实现 Review

核心在 `refcount_insertion.cpp`。阅读时重点看 pass 如何判断一个 value 需要 refcount 操作。这里的 interesting point 是：type lattice 的 conservatism 和 CPython runtime facts 不完全一致。

官方没有强行改 type generator，因为那可能让 `TBool` 与其他 type 组合规则不一致。改 pass 是更局部、更安全的选择。

## 测试实现 Review

多份 expected output 更新说明这个 pass 影响范围较广。学习时看：

- `refcount_insertion_test.txt`
- `refcount_insertion_static_test.txt`
- `all_passes_test.txt`

目标是确认原先多余的 `Decref` 消失，同时其他 mortal object 的 refcount 逻辑不变。

## CPython 3.14 关系

CPython 3.14 继承了 3.12+ immortal objects 的语义。CinderX refcount insertion 如果不了解这个事实，就会为 bool/None 生成无意义 refcount work。

## ARM64 启发

在 free-threading 或 atomic refcount 更贵的环境中，减少 refcount instructions 本身就是性能优化。ARM64 上 atomic operations 和 memory ordering 成本明显，refcount traffic elimination 值得重点看。

这个 commit 和 `3c88c653` 是两种互补方向：

- `d5fa88c3`: 能不生成 refcount 就不生成；
- `3c88c653`: 必须 refcount 时 inline fast path。

## 后续追问

- 还有哪些 type 在 3.14 中事实上 immortal，但 HIR type 没表达？
- 是否可以给 immortal type 建更明确的 type flag？
- refcount insertion 是否能利用 object specialization 判断更多 immortal constants？
- ARM64 上去掉这些 decref 后 code size 变化有多少？
