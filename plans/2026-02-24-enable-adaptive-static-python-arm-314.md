# Enable Adaptive Static Python on CPython 3.14 ARM Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable `ENABLE_ADAPTIVE_STATIC_PYTHON` by default on CPython 3.14 ARM builds and provide deterministic checks to prove it is enabled and effective.

**Architecture:** Keep the change localized to build-time feature defaulting in `setup.py`, expose a runtime introspection function from `_cinderx`, and extend the existing getdeps quick-test entrypoint (`test_oss_quick.py`) so the remote path can assert both enablement and behavior signal.

**Tech Stack:** Python 3.14+, setuptools/cmake build pipeline, C++ CPython extension (`_cinderx`), unittest/getdeps.

---

### Task 1: Add Failing Tests for Flag Decision Logic (RED)

**Files:**
- Create: `tests/test_setup_adaptive_static_python.py`
- Test: `tests/test_setup_adaptive_static_python.py`

**Step 1: Write the failing test**

```python
import unittest
import setup


class AdaptiveStaticDefaultTests(unittest.TestCase):
    def test_enable_for_314_arm64(self):
        self.assertTrue(
            setup.should_enable_adaptive_static_python(
                py_version="3.14",
                meta_python=False,
                machine="aarch64",
            )
        )

    def test_disable_for_314_x64(self):
        self.assertFalse(
            setup.should_enable_adaptive_static_python(
                py_version="3.14",
                meta_python=False,
                machine="x86_64",
            )
        )

    def test_enable_for_meta_312(self):
        self.assertTrue(
            setup.should_enable_adaptive_static_python(
                py_version="3.12",
                meta_python=True,
                machine="x86_64",
            )
        )
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_setup_adaptive_static_python.py -v`
Expected: FAIL with missing attribute/function `should_enable_adaptive_static_python`.

**Step 3: Write minimal implementation**

Implement `should_enable_adaptive_static_python()` in `setup.py` and wire `ENABLE_ADAPTIVE_STATIC_PYTHON` to this helper.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_setup_adaptive_static_python.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add setup.py tests/test_setup_adaptive_static_python.py
git commit -m "build: enable adaptive static python by default on 3.14 arm"
```

### Task 2: Add Runtime Introspection for Enablement (RED)

**Files:**
- Modify: `cinderx/_cinderx-lib.cpp`
- Modify: `cinderx/PythonLib/cinderx/__init__.py`
- Modify: `cinderx/PythonLib/test_cinderx/test_oss_quick.py`

**Step 1: Write the failing test**

Add assertions to `test_oss_quick.py`:
- `_cinderx`/`cinderx` exports `is_adaptive_static_python_enabled`.
- Returned value matches expected default:
  - true on `(sys.version_info[:2] == (3, 14) and machine in {"aarch64","arm64"})`
  - true on Meta 3.12
  - otherwise false unless env override is applied.

**Step 2: Run test to verify it fails**

Run (remote canonical path):  
`python3 build/fbcode_builder/getdeps.py test --src-dir=. cinderx-3_14 --project-install-prefix cinderx-3_14:/usr/local`

Expected: FAIL because API is not yet exported.

**Step 3: Write minimal implementation**

- Add C API function in `_cinderx-lib.cpp`:
  - `is_adaptive_static_python_enabled()` returns compile-time macro state.
- Export in `_cinderx_methods`.
- Import in `cinderx/__init__.py` with safe fallback when native extension is unavailable.

**Step 4: Run test to verify it passes**

Run same remote canonical path command and expect PASS.

**Step 5: Commit**

```bash
git add cinderx/_cinderx-lib.cpp cinderx/PythonLib/cinderx/__init__.py cinderx/PythonLib/test_cinderx/test_oss_quick.py
git commit -m "runtime: expose adaptive static python enablement status"
```

### Task 3: Verify Effect Signal (Not Just Switch State)

**Files:**
- Modify: `cinderx/PythonLib/test_cinderx/test_oss_quick.py`
- Optional Create: `cinderx/TestScripts/measure_adaptive_static_effect.py`

**Step 1: Write failing behavior assertion**

In quick test, add one warmup-and-observe check that exercises static dispatch path and confirms adaptive behavior hook is active when enabled (e.g. no error path, adaptive delay API usable, and specialization-sensitive path executes after warmup).

**Step 2: Run to verify RED**

Run remote canonical path and confirm failure before implementation.

**Step 3: Implement minimal behavior check**

Use existing exposed adaptive controls (`delay_adaptive`, `set_adaptive_delay`, `get_adaptive_delay`) and a deterministic warmup loop to produce a stable pass/fail signal.

**Step 4: Run to verify GREEN**

Run remote canonical path and expect PASS.

**Step 5: Commit**

```bash
git add cinderx/PythonLib/test_cinderx/test_oss_quick.py cinderx/TestScripts/measure_adaptive_static_effect.py
git commit -m "test: validate adaptive static python behavior signal in oss quick path"
```

### Task 4: ARM Remote Verification and Evidence Capture

**Files:**
- Modify: `findings.md`
- Modify: `progress.md`

**Step 1: Run remote verification on target host**

Run on `124.70.162.35`:
- Build/install with defaults.
- Execute canonical getdeps test entry.
- Run A/B comparison with `ENABLE_ADAPTIVE_STATIC_PYTHON=0` and `=1` using the same workload command.

**Step 2: Capture key evidence**

Record command, exit code, and key output lines in `findings.md`:
- `is_adaptive_static_python_enabled()` value
- quick test pass/fail
- A/B timing summary.

**Step 3: Verify completion criteria**

Criteria:
- ARM 3.14 default build reports enabled.
- remote canonical test path passes.
- A/B run shows no correctness regressions; performance delta recorded.

**Step 4: Commit evidence docs**

```bash
git add findings.md progress.md
git commit -m "docs: capture arm 3.14 adaptive static python verification evidence"
```
