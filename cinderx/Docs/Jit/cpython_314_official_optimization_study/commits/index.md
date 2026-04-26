# Commit Index

## 2 月

| commit | 日期 | 作者 | 主题 | 层次 | 阅读重点 |
| --- | --- | --- | --- | --- | --- |
| `5bfab630` | 2026-02-03 | Jacob Bower | Enable lightweight frames | frame/runtime | 降低 frame 管理成本，为后续 trampoline/LIR 化铺路 |
| `3d414b95` | 2026-02-12 | Jacob Bower | Enable inline caching for plain instance attributes | bytecode / attr cache | instance attr inline cache 如何进入 CinderX fast path |
| `14b48134` | 2026-02-13 | Dino Viehland | Add postalloc rewrite for mov instructions | LIR/postalloc | 用 rewrite 修正 register allocation 后的冗余 move |
| `8b98266a` | 2026-02-13 | Dino Viehland | Use opcodes to load/store specific size | LIR/codegen | 把 load/store size 显式编码进 opcode |
| `659606ab` | 2026-02-17 | Dino Viehland | Move frame loading to dedicated opcode | frame/LIR | frame load 从隐式 helper 变成可优化 instruction |
| `d37552a7` | 2026-02-18 | Kevin Newton | aarch64 support | ARM64 backend | correctness bring-up，先让 backend 能跑 |
| `53f4fc0f` | 2026-02-25 | Alex Malyshev | Specialize float operations further | HIR simplify | float op unbox / typed BinaryOp 扩展 |
| `6e5e3716` | 2026-02-25 | Alex Malyshev | Add three more CinderX benchmarks | benchmark | `nbody`、`binary-trees`、`spectral-norm` |

## 3 月

| commit | 日期 | 作者 | 主题 | 层次 | 阅读重点 |
| --- | --- | --- | --- | --- | --- |
| `5fec65f4` | 2026-03-12 | Alex Malyshev | Enable specialized opcode support by default | bytecode intake | CinderX 开始默认消费 CPython specialized opcode |
| `8635acf5` | 2026-03-16 | Dino Viehland | Replace unlink frame generation with LIR generated version | frame/LIR | assembly stub 迁移到 LIR |
| `d70dcb5a` | 2026-03-17 | Alex Malyshev | Unbox float TrueDivide and mixed float/int ops to DoubleBinaryOp | HIR simplify | mixed numeric path 的典型样例 |
| `e9968ea2` | 2026-03-19 | Alex Malyshev | Fuse compare + CondBranch into cmp + jcc | LIR/codegen | compare+branch 融合 |
| `54cb7a83` | 2026-03-23 | Alex Malyshev | Specialize list StoreSubscr to skip PyObject_SetItem dispatch | container fast path | 跳过 generic C API dispatch |
| `44e26d22` | 2026-03-23 | Alex Malyshev | Inline StoreArrayItem LIR lowering to a direct memory store | LIR lowering | container fast path 下沉到 direct memory store |
| `d5fa88c3` | 2026-03-26 | Alex Malyshev | Don't generate Decrefs for immortal types | refcount/runtime | 利用 immortal object 语义减少无意义 Decref |

## 4 月

| commit | 日期 | 作者 | 主题 | 层次 | 阅读重点 |
| --- | --- | --- | --- | --- | --- |
| `aca150d2` | 2026-04-02 | Dino Viehland | Use re-writes to avoid scratch register usage w/ immediates | LIR/postgen | immediate rewrite，减少 scratch register |
| `8b158d25` | 2026-04-02 | Dino Viehland | Rewrite guard instructions on floating point instructions | LIR/postgen | 浮点 guard 形状后处理 |
| `47e3a8de` | 2026-04-03 | Dino Viehland | Rewrite lea that requires a temporary to an explicit madd instruction | ARM64/codegen | address calc 改成 ARM64 更合适的 `madd` |
| `791c7dcc` | 2026-04-03 | Dino Viehland | Rewrite kHasType guard to use postgen type load | guard/codegen | type guard lowering 的 postgen 优化 |
| `16c708f8` | 2026-04-03 | Dino Viehland | Add postgen rewrite for Call instruction inputs | LIR/postgen | call input shape 改写 |
| `3a8600fb` | 2026-04-07 | Dino Viehland | Add MovConstPool postgen pass for large duplicate constants | constant pool | 大常量去重，减少 code size |
| `5029beec` | 2026-04-09 | Dino Viehland | Move frame linking from assembly to LIR | frame/LIR | frame link 进入 LIR |
| `afc7de79` | 2026-04-09 | Dino Viehland | Make hot/cold splitting work on ARM | ARM64 layout | ARM64 hot/cold splitting |
| `b1945d88` | 2026-04-13 | Alex Malyshev | Simplify "Float BinaryOp Long" with compact long checks | HIR simplify | compact long + float mixed op |
| `59062ec2` | 2026-04-15 | Kevin Newton | Replace trie-based instruction dispatch with direct switch for aarch64 | ARM64 assembler | 降低 asmjit AArch64 instruction dispatch overhead |
| `8aa963d4` | 2026-04-15 | Dino Viehland | Re-write memory inputs to registers | LIR/postgen | memory input rewrite |
| `3c88c653` | 2026-04-16 | Jacob Bower | Inline Py_IncRef/Py_DecRef for free-threading | refcount/runtime | free-threading refcount helper inline |
| `4c280add` | 2026-04-22 | Alex Malyshev | Optimize LongCompare for compact longs | HIR simplify | compact long compare fast path |
| `229573e7` | 2026-04-22 | Alex Malyshev | Constant fold IntConvert for constant ints | HIR simplify | typed constant folding |
| `2c247cf7` | 2026-04-22 | Alex Malyshev | Add simplification cases for PrimitiveBox | HIR simplify | box/unbox 消除 |
| `0e2820b7` | 2026-04-22 | Alex Malyshev | Support IntBinaryOp on CBool arguments | HIR simplify | boolean primitive 进入 int binary op |
