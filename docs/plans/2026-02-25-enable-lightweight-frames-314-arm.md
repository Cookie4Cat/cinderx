# Enable LIGHTWEIGHT_FRAMES 3.14 ARM Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable `ENABLE_LIGHTWEIGHT_FRAMES` by default on Python 3.14 ARM and verify it works together with LTO, PGO, and adaptive static python.

**Architecture:** Add a setup-level default policy helper, expose native build-time status via a small API, and lock behavior with focused tests. Validate end-to-end only on remote ARM host with explicit evidence capture.

**Tech Stack:** Python setuptools (`setup.py`), C++ extension (`_cinderx`), unittest, remote Linux build/install via SSH.

---

### Task 1: Add failing setup-policy tests (RED)

**Files:**
- Create: `tests/test_setup_lightweight_frames.py`

**Step 1: Write the failing test**
- Add tests that expect:
  - `should_enable_lightweight_frames(py_version="3.14", meta_python=False, machine="aarch64")` is `True`
  - same for `arm64`
  - `3.14 + x86_64` is `False`
  - `3.15 + arm64` is `False` (Stage A)
  - `3.12 + meta_python=True` is `True`

**Step 2: Run test to verify it fails**
Run (remote):
- `ssh root@124.70.162.35 'cd /root/work/cinderx-main && source /root/venv-cinderx314/bin/activate && python -m unittest tests/test_setup_lightweight_frames.py -v'`
Expected: FAIL due to missing helper.

### Task 2: Implement minimal setup policy (GREEN)

**Files:**
- Modify: `setup.py`

**Step 1: Write minimal implementation**
- Add `should_enable_lightweight_frames(...)`.
- Use helper in `set_option("ENABLE_LIGHTWEIGHT_FRAMES", ...)`.

**Step 2: Run test to verify it passes**
Run (remote):
- same unittest command as Task 1.
Expected: PASS.

### Task 3: Add failing API tests (RED)

**Files:**
- Create: `tests/test_cinderx_lightweight_frames_api.py`
- Modify: `cinderx/PythonLib/test_cinderx/test_oss_quick.py`

**Step 1: Write the failing test**
- Assert `cinderx` exports `is_lightweight_frames_enabled` and return type is bool.
- Extend OSS quick test to assert expected value on runtime (3.14 ARM should be True).

**Step 2: Run tests to verify fail**
Run (remote, before implementation):
- `ssh root@124.70.162.35 'cd /root/work/cinderx-main && source /root/venv-cinderx314/bin/activate && PYTHONPATH=cinderx/PythonLib python -m unittest tests/test_cinderx_lightweight_frames_api.py -v'`
Expected: FAIL due to missing API.

### Task 4: Implement native/API exposure (GREEN)

**Files:**
- Modify: `cinderx/_cinderx-lib.cpp`
- Modify: `cinderx/PythonLib/cinderx/__init__.py`

**Step 1: Write minimal implementation**
- Add `_cinderx.is_lightweight_frames_enabled()` doc + function + method table entry.
- Import in Python module and provide fallback function returning `False`.

**Step 2: Run tests to verify pass**
Run (remote):
- `ssh root@124.70.162.35 'cd /root/work/cinderx-main && source /root/venv-cinderx314/bin/activate && PYTHONPATH=cinderx/PythonLib python -m unittest tests/test_cinderx_lightweight_frames_api.py -v'`
Expected: PASS.

### Task 5: Remote integration verification (LTO + PGO + adaptive static)

**Files:**
- Modify: `findings.md`
- Modify: `progress.md`
- Modify: `task_plan.md`

**Step 1: Sync code to remote test path**
- Sync changed files to `/root/work/cinderx-main`.

**Step 2: Verify LTO + adaptive static + lightweight frames**
Run (remote):
- build/install with `CINDERX_ENABLE_PGO=0 CINDERX_ENABLE_LTO=1`
- probe APIs:
  - `cinderx.is_lightweight_frames_enabled()`
  - `cinderx.is_adaptive_static_python_enabled()`
- verify build flags include `-flto` and `ENABLE_LIGHTWEIGHT_FRAMES` define.

**Step 3: Verify PGO + LTO + adaptive static + lightweight frames**
Run (remote):
- build/install with `CINDERX_ENABLE_PGO=1 CINDERX_ENABLE_LTO=1`
- collect log, exit code, runtime API probes.

**Step 4: Smoke tests**
Run (remote):
- `python cinderx/PythonLib/test_cinderx/test_oss_quick.py`

**Step 5: Record evidence**
- Append commands and key outputs to `findings.md`.

### Task 6: Verification-before-completion gate

**Files:**
- Modify: `findings.md`
- Modify: `progress.md`
- Modify: `task_plan.md`

**Step 1: Re-run decisive verification commands fresh**
- remote unit tests, LTO build probe, PGO+LTO build probe, smoke test.

**Step 2: Confirm claims are evidence-backed**
- Only claim completion if latest command outputs confirm success.

**Step 3: Finalize phase statuses**
- mark plan phases complete and capture remaining risks.
