# ARM vs X86 Richards Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a unified ARM/X86 richards measurement loop, then execute optimization in strict order (1 -> 2 -> 3) with evidence-driven tests.

**Architecture:** Add a shared benchmark analysis utility and host runners that produce consistent JSON artifacts. Use those artifacts to tune JIT policy first, then perform targeted ARM codegen edits with regression guards.

**Tech Stack:** PowerShell orchestration, remote shell over SSH, Python 3.14 + pyperformance, CinderX JIT runtime tests.

---

### Task 1: Add benchmark analysis utility (TDD)

**Files:**
- Create: `scripts/bench/richards_metrics.py`
- Create: `scripts/bench/test_richards_metrics.py`

**Step 1: Write failing tests**
- Add tests for:
  - bootstrap CI bounds ordering,
  - ARM-vs-X86 speedup sign convention,
  - robust summary generation from sample vectors.

**Step 2: Run tests to verify RED**
- Run: `python -m unittest scripts/bench/test_richards_metrics.py`
- Expected: failure due missing module/functions.

**Step 3: Implement minimal utility**
- Implement:
  - summary stats,
  - bootstrap CI for mean delta,
  - ARM-vs-X86 percent speedup where positive means ARM faster.

**Step 4: Run tests to verify GREEN**
- Run: `python -m unittest scripts/bench/test_richards_metrics.py`
- Expected: all pass.

**Step 5: Commit**
- `git add scripts/bench/richards_metrics.py scripts/bench/test_richards_metrics.py`
- `git commit -m "bench: add richards metrics utility with tests"`

### Task 2: Add unified remote richards runner (ARM/X86)

**Files:**
- Create: `scripts/bench/run_richards_remote.sh`
- Create: `scripts/bench/collect_arm_x86_richards.ps1`

**Step 1: Write failing test for output contract**
- Add/extend `scripts/bench/test_richards_metrics.py` with fixture parser test
  expecting fields from runner JSON.

**Step 2: Verify RED**
- Run unittest target, confirm missing fields/parse path fail.

**Step 3: Implement runners**
- `run_richards_remote.sh`:
  - run `nojit`, `jitlist`, `autojit50` richards samples (configurable count),
  - emit JSON artifact with raw samples.
- `collect_arm_x86_richards.ps1`:
  - invoke remote runner via SSH on both hosts,
  - pull artifacts,
  - call `richards_metrics.py` to compute comparative summary.

**Step 4: Verify GREEN**
- Run parser tests and dry-run collection command.

**Step 5: Commit**
- commit the new runner scripts/tests.

### Task 3: Step 1 validation on both hosts

**Files:**
- Modify: `findings.md`
- Modify: `progress.md`
- Modify: `task_plan.md`

**Step 1: Run unified measurement entrypoint**
- Run `scripts/bench/collect_arm_x86_richards.ps1` with:
  - ARM host: `124.70.162.35`
  - X86 host: `106.14.164.133`
  - venv path: `/root/venv-cinderx314`

**Step 2: Verify output and CI**
- Ensure summary JSON exists and includes:
  - mode-wise stats,
  - ARM-vs-X86 speedup and CI.

**Step 3: Record baseline**
- Append from->to baseline block to `findings.md`.

### Task 4: Step 2 JIT policy tuning (no codegen)

**Files:**
- Modify: `scripts/bench/run_richards_remote.sh` (threshold knobs only if needed)
- Modify: `findings.md`

**Step 1: Add failing regression check**
- Add test case in `cinderx/PythonLib/test_cinderx/test_arm_runtime.py` for
  policy knob invariants if behavior/API touched.

**Step 2: RED verification**
- Run targeted test and confirm fails before policy update.

**Step 3: Implement policy iteration**
- Evaluate candidates (e.g., `25`, `50`, `100`) and optional jitlist hotspot
  expansion without codegen edits.

**Step 4: Verification**
- Re-run unified ARM/X86 collector; compare to baseline.

**Step 5: Commit**
- Commit only policy-related changes with metrics reference.

### Task 5: Step 3 ARM codegen micro-optimization

**Files:**
- Modify: `cinderx/Jit/codegen/gen_asm.cpp`
- Modify: `cinderx/Jit/codegen/gen_asm_utils.cpp`
- Modify: `cinderx/Jit/codegen/environ.h` (if needed)
- Modify: `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
- Modify: `findings.md`

**Step 1: Add failing regression/perf-shape test**
- Add one minimal ARM runtime/code-size or behavior guard for the target path.

**Step 2: RED verification**
- Run targeted ARM runtime test to capture expected failure.

**Step 3: Implement minimal codegen change**
- Apply one low-risk hot-path change only.

**Step 4: GREEN verification**
- Run ARM runtime suite and unified ARM/X86 performance collector.

**Step 5: Commit**
- Commit codegen change and test update.

### Task 6: Final verification-before-completion

**Files:**
- Modify: `findings.md`
- Modify: `progress.md`
- Modify: `task_plan.md`

**Step 1: Run full required verification**
- ARM remote entrypoint smoke/build:
  - `scripts/push_to_arm.ps1 -SkipPyperformance`
- Unified comparative performance entrypoint:
  - `scripts/bench/collect_arm_x86_richards.ps1`
- ARM runtime tests:
  - `python cinderx/PythonLib/test_cinderx/test_arm_runtime.py` (on ARM host)

**Step 2: Evidence review**
- Confirm latest outputs, exit codes, and thresholds before any success claim.

**Step 3: Record final results**
- Write final from->to and target status (ARM >= X86 + 3%) in `findings.md`.
