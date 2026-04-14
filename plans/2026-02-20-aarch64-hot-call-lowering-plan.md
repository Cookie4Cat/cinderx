# AArch64 Hot Call Lowering Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Optimize AArch64 hot immediate call lowering so singleton hot targets avoid helper stubs while repeated targets keep dedup behavior.

**Architecture:** Add a small LIR pre-pass in `NativeGenerator` to count immediate `kCall` target multiplicity, then use that count inside AArch64 `emitCall` to select direct literal call vs helper stub path for `instr != nullptr`.

**Tech Stack:** C++ (JIT codegen), Python unittest (`test_arm_runtime.py`), existing ARM remote pipeline scripts.

---

### Task 1: Add a failing ARM regression test (TDD Red)

**Files:**
- Modify: `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`

**Step 1: Write failing test**

- Add `test_aarch64_singleton_immediate_call_target_prefers_direct_literal`.
- Build two compiled functions:
  - `f1`: one `math.sqrt(x)` callsite
  - `f2`: two `math.sqrt(x)` callsites
- Assert:
  - both compile and execute correctly
  - `size_delta = size(f2) - size(f1)` is `>= 364`

**Step 2: Verify fail**

Run on ARM:

```bash
python cinderx/PythonLib/test_cinderx/test_arm_runtime.py -k singleton_immediate_call_target
```

Expected: FAIL on current baseline (`delta` observed around `360`).

### Task 2: Add target-usage pre-pass plumbing

**Files:**
- Modify: `cinderx/Jit/codegen/environ.h`
- Modify: `cinderx/Jit/codegen/gen_asm.h`
- Modify: `cinderx/Jit/codegen/gen_asm.cpp`

**Step 1: Extend environment state**

- Add AArch64 map in `Environ`:
  - `UnorderedMap<uint64_t, uint32_t> hot_call_target_uses;`

**Step 2: Add pre-pass declaration/implementation**

- Add private method in `NativeGenerator`:
  - `void collectAarch64HotImmediateCallTargetUses();`
- Implement method in `gen_asm.cpp`:
  - iterate `lir_func_->basicblocks()`
  - for each `instr->isCall()`, inspect input0
  - if immediate, increment target usage count

**Step 3: Hook pre-pass before lowering**

- Invoke `collectAarch64HotImmediateCallTargetUses()` in `generateCode()`
  before `generateAssemblyBody(...)`.

### Task 3: Update AArch64 call lowering decision

**Files:**
- Modify: `cinderx/Jit/codegen/gen_asm_utils.cpp`

**Step 1: Select path by multiplicity**

- In `emitCall(env, uint64_t func, instr)` for `CINDER_AARCH64`:
  - keep `instr == nullptr` direct-literal behavior unchanged
  - for `instr != nullptr`:
    - if `instr->isCall()` and `hot_call_target_uses[func] <= 1`, emit direct
      literal call
    - otherwise keep helper-stub path

**Step 2: Preserve existing semantics**

- Keep debug entry recording unchanged.
- Keep helper-stub and literal-pool emission logic unchanged for repeated
  targets.

### Task 4: Verify Green locally/remotely

**Files:**
- No additional code changes expected.

**Step 1: Local compile/test sanity**

Run:

```bash
python -m compileall cinderx/PythonLib/test_cinderx/test_arm_runtime.py
```

**Step 2: ARM remote full gate**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/push_to_arm.ps1 `
  -RepoPath d:\code\cinderx-upstream-20260213 `
  -WorkBranch bench-cur-7c361dce `
  -ArmHost 124.70.162.35 `
  -SkipPyperformance
```

Expected: `Ran 5 tests ... OK` (or updated count).

**Step 3: Check targeted performance/size probes**

- Re-run singleton/repeated size probe:
  - expect new delta threshold test passes
- Re-run compactness guard:
  - expect existing threshold stays passing (`<= 71600` or better)

### Task 5: Record results and summarize

**Files:**
- Modify: `findings.md`
- Modify: `progress.md`
- Modify: `task_plan.md`

**Step 1: Record from->to numbers**

- Singleton/repeated size delta before/after
- Existing compactness guard value before/after
- Any richards spot-check numbers collected

**Step 2: Final status**

- Mark plan progress and residual risks.
- Note any follow-up hot-path targets for next iteration.
