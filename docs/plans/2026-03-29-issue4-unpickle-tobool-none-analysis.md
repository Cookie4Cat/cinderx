# Issue #4: `TO_BOOL_NONE` 通用修复*
## 问题定义

`pickle._Unframer.read` 的 `if self.current_frame:` 在 Python 3.14 下会被 quicken 成 `TO_BOOL_NONE`。

之前 JIT 对 `TO_BOOL_NONE` 的 lowering 是：

- `GuardType(TNoneType)`
- `LoadConst(Py_False)`

这会把解释器里的“自适应专门化命中形状”编译成“JIT 中必须永远是 `None`”的稳定承诺。

结果是：

- 热起来时如果该站点先看到 `None`，就会编译出 `GuardType(TNoneType)`。
- 之后一旦站点合法地看到非 `None` 值，就会在 JIT 中持续 deopt。

`unpickle_pure_python` 暴露了这个问题，但它不是 `_Unframer` 的私有问题，而是 `TO_BOOL_NONE` lowering 的通用问题。

## 根因

CPython 3.14 对 `TO_BOOL_NONE` 的解释器语义并不是“该值必须始终是 `None`”，而是：

- 若值仍然是 `None`，走快速路径并返回 `False`
- 若值不是 `None`，则 miss 回退到通用 `TO_BOOL`

也就是说，`TO_BOOL_NONE` 在解释器里只是一个 quickening hint，而不是稳定类型承诺。

本地仓库里的 3.14 生成解释器代码已经能直接看到这一点：

- `cinderx/Interpreter/3.14/Includes/generated_cases.c.h`

其中 `TO_BOOL_NONE` 的关键逻辑是：

- `if (!PyStackRef_IsNone(value)) { ... JUMP_TO_PREDICTED(TO_BOOL); }`

因此，JIT 之前把它翻译成 `GuardType(TNoneType)` 是过度特化。

## 设计目标

1. 从根上修复 `TO_BOOL_NONE` 的 JIT 语义。
2. 不再依赖 `_Unframer` 这样的 workload 特判。
3. 保住 `go` 的最佳性能附近。
4. 让 `unpickle_pure_python` 去掉 deopt 后不要出现严重劣化。

## 最终方案

JIT 不再对 `TO_BOOL_NONE` 做专门 lowering。

具体做法：

- 保留 `TO_BOOL_BOOL / INT / LIST / STR` 的专门 lowering。
- 删除 `TO_BOOL_NONE -> GuardType(TNoneType) + False` 这一分支。
- 让 `TO_BOOL_NONE` 自然落回通用 `TO_BOOL` 路径，也就是：
  - `IsTruthy`
  - `PrimitiveBoxBool`

对应代码位置：

- `cinderx/Jit/hir/builder.cpp`