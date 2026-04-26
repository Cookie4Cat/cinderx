# Bytecode Intake

这一层关注 CPython 3.14 adaptive interpreter 已经采到的 type info，CinderX 有没有在 intake / HIR builder 里保留下来。

## 重点 commits

- `5fec65f4` Enable specialized opcode support by default
- `3d414b95` Enable inline caching for plain instance attributes
- `54cb7a83` Specialize list StoreSubscr to skip PyObject_SetItem dispatch

## Audit checklist

1. `dis.get_instructions(adaptive=True, show_caches=True)` 里是否出现 specialized opcode。
2. `BytecodeInstruction::specializedOpcode()` 是否保留这个 opcode。
3. HIR builder 是否按 specialized opcode 分支。
4. HIR 是否只加 guard，还是真正 lowering 到 dedicated helper / instruction。
5. simplify / LIR 是否继续消费这个 type info。

## 可复用结论

CPython 3.14 的 inline cache 可以替代 Cinder 旧时代 shadow code 的一部分采样职责。优化机会通常出现在：

- CPython 已经 specialized，但 CinderX intake 抹平了。
- CinderX 保留了 specialized opcode，但 HIR 只做 weak guard。
- HIR 做了 typed path，但 LIR/codegen 又落回 generic helper。
