# LIR / Codegen 优化线索

## 主线判断

3/4 月的 LIR/codegen 优化有一个清楚方向：把隐式 backend special case 变成显式 LIR rewrite，让 regalloc 看到 temporary、constant、stack/memory input 和 call target。这样既让代码生成更稳定，也能减少 ARM64 上常见的 scratch register pressure。

这类 commit 的价值不只在“少几条指令”，还在于让 compiler pipeline 可理解。以前 emitter 内部偷偷用 scratch register，测试很难覆盖；现在 rewrite 后的 LIR 可以被 `lir_postgen_test`、`lir_postalloc_test` 固化。

## 3 月: helper removal 和 branch fusion

`44e26d22` 是最直接的 helper removal。`StoreArrayItem` 原来 lower 成 `JITRT_Set*_InArray` helper call，实际上 helper 只做一次 array store。commit 删除 helper，直接 emit `kMove` 到 `OutInd`。

收益包括：

- 没有 call/ret；
- 少了 argument marshalling；
- 少了 caller-save spills；
- index known 时可以折叠成 constant offset store。

`e9968ea2` 做 compare + conditional branch fusion。旧形状是 `cmp + setcc + test + je`，新形状是直接 `cmp + jcc`。这个 commit 也展示了谨慎边界：`setcc` 可能变 dead，但没有 liveness 信息前不强删。

## 4 月: postgen rewrite 主线

`aca150d2`、`8b158d25`、`47e3a8de`、`791c7dcc`、`16c708f8` 都在处理 ARM64 operand constraints:

- illegal/large immediates 先 move 到 vreg；
- FP guard value 先变成 GP-usable value；
- LEA 需要 temporary 时改成 explicit `MAdd`；
- `kHasType` guard 先显式 load `ob_type`；
- `Call Imm/Stack` 改成 `Move -> vreg -> Call`。

共同点：让 regalloc 管理 temporary，而不是 codegen 抢 `arch::reg_scratch_*`。

## 4 月: postalloc rewrite 主线

`8aa963d4` 是 postalloc rewrite，因为问题出现在 register allocation 之后：某些 instruction 最终拿到了 ARM64 不支持的 memory input form。postalloc 可以看到最终 operand placement，于是把 memory input load 到 register。

这个 commit 很适合学习 ARM64 和 x86 的差异：x86 有 rich memory operand，ARM64 很多 ALU op 只接受 register。

## Constant pool 和 code size

`3a8600fb` 添加 `MovConstPool`。它识别重复 large 64-bit immediates，如果每次 materialize 需要超过两条 `movz/movk`，就改成从 constant pool PC-relative load。

这个优化属于 code size / I-cache 优化，不一定降低单次 latency，但能减少重复常量造成的 instruction bloat。对 JIT code cache 来说，code size 本身就是性能维度。

## Frame/trampoline LIR 化

`8635acf5` 和 `5029beec` 把 frame unlink/link 从 handwritten assembly 移到 LIR。这个方向很重要：frame setup 不再是 backend 私有协议，而是 LIR generator、regalloc、codegen 都能看见的 sequence。

后续 `4a563280`、`1f50e895`、`0d150eb5`、`68e3fe80` 继续把 resume entry、return box、deopt/deferred compile trampoline 移进 LIR。虽然这些不都在 deep review 清单里，但它们属于同一条路线。

## 测试阅读方法

LIR/codegen commit 应看三类测试：

- `RuntimeTests/lir_abi_test.cpp`: ABI、call、register convention。
- `RuntimeTests/lir_postgen_test.cpp`: postgen rewrite 后的 expected LIR。
- `RuntimeTests/lir_postalloc_test.cpp`: postalloc 后 memory/register operand shape。

如果一个 commit 修改 `autogen.cpp` 但没有 tests，要格外关注是否只是机械 rule change，还是 behavior change。

## 对 ARM64 的意义

ARM64 优化常常不是“选更快 instruction”这么简单，而是先把 operand shape 调合法。一个好的 ARM64 backend 优化通常长这样：

```text
identify illegal/expensive ARM64 operand shape
  -> rewrite into explicit LIR
  -> let regalloc assign temp
  -> codegen emits simple architecture-native instruction
  -> tests assert LIR/codegen shape
```

这条线是后面我们自己做 ARM64 优化时最应该模仿的。
