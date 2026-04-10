# Enable LIGHTWEIGHT_FRAMES on Python 3.14 ARM (Stage A) Design

Date: 2026-02-25

## Objective
Enable `ENABLE_LIGHTWEIGHT_FRAMES` by default for Python 3.14 on ARM (`aarch64`/`arm64`) while preserving compatibility with `ENABLE_ADAPTIVE_STATIC_PYTHON`, `CINDERX_ENABLE_LTO=1`, and `CINDERX_ENABLE_PGO=1`.

## Scope
- In scope (Stage A):
  - Python 3.14 ARM default enablement.
  - New runtime API to expose build-time status.
  - Remote-only validation through `ssh root@124.70.162.35`.
- Out of scope (later stages):
  - Default enablement for x86.
  - Default enablement for Python 3.15.

## Constraints
- Keep environment override behavior: explicit env vars still win over defaults.
- Minimize diff and avoid changing unrelated JIT behavior.
- Use TDD and verification-before-completion.

## Design

### 1. Default enablement strategy (`setup.py`)
Add a helper function mirroring adaptive-static style:
- `should_enable_lightweight_frames(py_version, meta_python, machine=None) -> bool`
- Stage A default policy:
  - `True` for Meta 3.12 (preserve existing behavior)
  - `True` for OSS Python 3.14 on `aarch64`/`arm64`
  - `False` otherwise (including 3.15 by default in this stage)

Use this helper in `BuildExt._run_cmake()`:
- Replace `set_option("ENABLE_LIGHTWEIGHT_FRAMES", meta_312)` with helper call.

### 2. Runtime status API
Expose compile-time status from native module:
- `_cinderx.is_lightweight_frames_enabled() -> bool`
  - Returns `True` iff `ENABLE_LIGHTWEIGHT_FRAMES` was defined at build time.

Surface in Python package API:
- `cinderx.is_lightweight_frames_enabled()`
  - Imported from `_cinderx` when available.
  - Fallback returns `False` when `_cinderx` unavailable.

### 3. Tests (TDD first)
- Setup/default policy tests:
  - new `tests/test_setup_lightweight_frames.py`
  - assert Stage A policy and env flag behavior interaction assumptions.
- API contract tests:
  - new `tests/test_cinderx_lightweight_frames_api.py`
  - assert function exists and returns bool.
- OSS quick smoke:
  - extend `cinderx/PythonLib/test_cinderx/test_oss_quick.py`
  - assert API exists and expected value on runtime.

### 4. Verification strategy (remote only)
All commands run through:
- `ssh root@124.70.162.35 '<command>'`

Validation matrix:
1. Unit tests for setup helper (RED then GREEN).
2. Build/install with `CINDERX_ENABLE_LTO=1` and check runtime API.
3. Build/install with `CINDERX_ENABLE_PGO=1 CINDERX_ENABLE_LTO=1` and check runtime API.
4. Confirm adaptive static API remains `True` on 3.14 ARM.
5. Run `test_oss_quick.py` smoke.

## Risk and mitigations
- Risk: PGO cycle duration/instability on remote host.
  - Mitigation: run as background job with explicit exit file and log capture.
- Risk: introducing API import regressions in `_cinderx` fallback paths.
  - Mitigation: keep fallback function in `__init__.py` symmetrical to adaptive-static.
- Risk: behavior drift on 3.15 while staging.
  - Mitigation: explicit tests lock Stage A to 3.14 ARM only.

## Success criteria
- 3.14 ARM default lightweight-frames enablement is active.
- `cinderx.is_lightweight_frames_enabled()` returns `True` on verified remote build.
- LTO+PGO+adaptive-static coexistence verified with evidence captured.
- All key results recorded in `findings.md`.
