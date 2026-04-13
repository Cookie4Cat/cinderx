# Findings & Decisions

## Requirements
- Enable `ENABLE_ADAPTIVE_STATIC_PYTHON` to work on official Python 3.14 ARM server path.
- Enable and follow skills/process: `using-superpowers` + `planning-with-files`.
- Execute the standard loop: `brainstorming -> writing-plans -> test-driven-development -> verification-before-completion`.
- Use `<remote test entry>` for all test/verification runs.
- Write key test/verification outcomes into this file.

## Research Findings
- `ENABLE_ADAPTIVE_STATIC_PYTHON` appears in `setup.py` (active editor context from user).
- Planning files were not present initially and were created in project root.
- `planning-with-files` catchup script ran without unsynced-session output.
- `setup.py` currently sets `ENABLE_ADAPTIVE_STATIC_PYTHON` via `set_option("ENABLE_ADAPTIVE_STATIC_PYTHON", meta_312)`, which suggests 3.12-gated behavior.
- `CMakeLists.txt` exposes `set_flag(ENABLE_ADAPTIVE_STATIC_PYTHON)`.
- Source tree already contains `ENABLE_ADAPTIVE_STATIC_PYTHON` usage in:
  - `cinderx/Interpreter/3.14/*`
  - `cinderx/Interpreter/3.15/*`
  - `cinderx/Interpreter/3.12/*`
- No concrete repository path/command for `<remote test entry>` found yet.
- `setup.py` computes:
  - `meta_312 = meta_python and py_version == "3.12"`
  - `is_314plus = py_version == "3.14" or py_version == "3.15"`
  - But `ENABLE_ADAPTIVE_STATIC_PYTHON` still defaults to `meta_312`.
- `.github/workflows/ci.yml` and `.github/workflows/publish.yml` pin Python `3.14.3`.
- `.github/workflows/getdeps-3_14-linux.yml` uses getdeps as a full build/test pipeline, with test command:
  - `python3 build/fbcode_builder/getdeps.py test --src-dir=. cinderx-3_14 --project-install-prefix cinderx-3_14:/usr/local`
- `build/fbcode_builder/manifests/cinderx-3_14` defines:
  - `[setup-py.test] python_script = cinderx/PythonLib/test_cinderx/test_oss_quick.py`
  - `[setup-py.env] CINDERX_ENABLE_PGO=1, CINDERX_ENABLE_LTO=1`
- CI quick path exists separately:
  - `uv run pytest cinderx/PythonLib/test_cinderx/test*.py`
- Current likely candidates for `<remote test entry>` are:
  - getdeps test command (closer to release/manifest workflow)
  - CI pytest command (faster feedback)
- `build/fbcode_builder/manifests/cinderx-3_14` quick test currently only checks import (`test_oss_quick.py`), not adaptive-static functionality.
- `git blame setup.py` shows:
  - `ENABLE_ADAPTIVE_STATIC_PYTHON` default (`meta_312`) introduced in commit window around 2025-10 OSS 3.14 compatibility work.
  - Later 2026-01 changes added `is_314plus` only for `ENABLE_INTERPRETER_LOOP` and `ENABLE_PEP523_HOOK`, leaving adaptive-static unchanged.
- `README.md` currently lists Linux `x86_64` as requirement; ARM is not declared as supported in OSS docs.
- `pyproject.toml` cibuildwheel targets only `cp314-manylinux_x86_64` and `cp314-musllinux_x86_64` (no ARM wheel target).
- Repository does contain multiple recent AArch64-related fixes, indicating partial ARM compatibility efforts despite packaging targets being x86_64.
- No dedicated test file currently verifies `setup.py` defaulting logic for `ENABLE_ADAPTIVE_STATIC_PYTHON`.
- Commit `d0297b3e` ("Enable interpreter loop on 3.14 OSS builds") notes that some codepaths (including adaptive-static control knobs) could not compile without interpreter loop, and enabled interpreter loop/PEP523 for 3.14.
- Even after that commit, `ENABLE_ADAPTIVE_STATIC_PYTHON` stayed defaulted to `meta_312`, indicating prior conservative rollout rather than missing implementation.
- In `cinderx/Interpreter/3.14/interpreter.c`, `Ci_InitOpcodes()` patches CPython opcode cache/deopt tables only when `ENABLE_ADAPTIVE_STATIC_PYTHON` is defined.
- In `cinderx/Interpreter/3.14/cinder-bytecodes.c`, many runtime specializations are gated by `#if ENABLE_SPECIALIZATION && defined(ENABLE_ADAPTIVE_STATIC_PYTHON)`, including:
  - `STORE_LOCAL_CACHED`
  - `BUILD_CHECKED_LIST_CACHED`
  - `BUILD_CHECKED_MAP_CACHED`
  - `LOAD_METHOD_STATIC_CACHED`
  - `INVOKE_FUNCTION_CACHED` / indirect cached path
  - `TP_ALLOC_CACHED`
  - `CAST_CACHED`
  - `LOAD_OBJ_FIELD` / `LOAD_PRIMITIVE_FIELD`
  - `STORE_OBJ_FIELD` / `STORE_PRIMITIVE_FIELD`
- Therefore enabling this flag is expected to affect adaptive specialization behavior and performance characteristics for Static Python-heavy paths.
- Attempted remote execution on ARM host `124.70.162.35` via SSH failed due authentication:
  - `Permission denied (publickey,gssapi-keyex,gssapi-with-mic,password)`
- `getdeps` current test entry for `cinderx-3_14` is import-only (`test_oss_quick.py`), insufficient to prove adaptive-static specialization is active.
- Existing static runtime tests contain comments about exercising cached paths (e.g. `INVOKE_FUNCTION_CACHED`) but do not explicitly assert adaptive/cached opcode presence.
- Existing bytecode assertion helpers in `test_compiler/common.py` use regular disassembly (`Bytecode(...)`) and do not inspect adaptive-specialized instruction stream by default.
- Implemented changes in this session:
  - `setup.py`: added `should_enable_adaptive_static_python()` and switched default option source to it.
  - `setup.py`: added `is_env_flag_enabled()` and switched `CINDERX_ENABLE_PGO/CINDERX_ENABLE_LTO` to real boolean parsing (`0/false/off/no` disables).
  - `_cinderx`: added runtime API `is_adaptive_static_python_enabled()`.
  - `cinderx.__init__`: exports `is_adaptive_static_python_enabled()` with fallback.
  - `test_oss_quick.py`: now asserts adaptive-static enablement state by platform/version.
  - Added local unit tests for setup default logic, env-flag parsing, and API presence.

## Verification Results
- Local RED (expected):
  - `python -m unittest tests/test_setup_adaptive_static_python.py -v`
  - Failure reason: missing `setup.should_enable_adaptive_static_python`.
- Local GREEN:
  - `$env:PYTHONPATH='cinderx/PythonLib'; python -m unittest tests/test_setup_adaptive_static_python.py tests/test_cinderx_adaptive_static_api.py -v`
  - Result: 10 tests passed.
- Syntax check:
  - `python -m py_compile setup.py cinderx/PythonLib/cinderx/__init__.py cinderx/PythonLib/test_cinderx/test_oss_quick.py tests/test_setup_adaptive_static_python.py tests/test_cinderx_adaptive_static_api.py`
  - Result: pass.
- Remote ARM verification (`124.70.162.35`, `aarch64`, Python `3.14.3`):
  - `getdeps build` failure (captured):
    - `getdeps.py build --src-dir=. cinderx-3_14 ...`
    - Failure: `/usr/bin/ld: ... LLVMgold.so: cannot open shared object file`
  - Root-cause evidence:
    - `setup.py` previously enabled LTO when `CINDERX_ENABLE_LTO` env var merely existed.
    - `getdeps` manifest exports `CINDERX_ENABLE_LTO=1 CINDERX_ENABLE_PGO=1`.
  - Remote install pass after fixes:
    - `env CINDERX_ENABLE_PGO=0 CINDERX_ENABLE_LTO=0 python setup.py install`
    - Build/install reached `[100%] Built target _cinderx` and installed to `/root/venv-cinderx314/lib/python3.14/site-packages`.
  - Remote functional checks (same host/venv):
    - `python cinderx/PythonLib/test_cinderx/test_oss_quick.py` -> `Ran 2 tests ... OK`
    - Runtime probe:
      - `hasattr(cinderx, "is_adaptive_static_python_enabled") == True`
      - `cinderx.is_adaptive_static_python_enabled() == True`
  - Remote enablement evidence (build artifacts):
    - `scratch/temp.linux-aarch64-cpython-314/CMakeCache.txt` contains `ENABLE_ADAPTIVE_STATIC_PYTHON:UNINITIALIZED=1`
    - `_cinderx` flags contain `-DENABLE_ADAPTIVE_STATIC_PYTHON` in:
      - `scratch/temp.linux-aarch64-cpython-314/CMakeFiles/_cinderx.dir/flags.make`

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Defer implementation until brainstorming design is approved | Required by brainstorming skill hard gate |
| Keep verification evidence tied to `<remote test entry>` only | Explicit user requirement |
| Enable by default on Python 3.14 ARM only | Matches target while minimizing regression surface compared with global 3.14+ enablement |
| Treat `CINDERX_ENABLE_PGO/LTO` as boolean values, not presence-only toggles | Required for reliable ARM builds where LTO toolchain plugin may be unavailable |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| Default path for `session-catchup.py` did not exist in this environment | Switched to the installed skill path under `C:/Users/Administrator/.codex/planning-with-files/...` |
| `rg` against non-existent `tools/` and `scripts/` paths failed | Scoped next searches to existing paths (`.github/`, repository root) |
| RED test initially failed due missing local dependency `setuptools` | Installed `setuptools` and re-ran to capture expected feature-missing failure |
| API unit test imported non-repo `cinderx` package | Ran tests with `PYTHONPATH=cinderx/PythonLib` to target repository code |
| `getdeps build` failed linking `_cinderx.so` with missing `LLVMgold.so` | Added boolean env parsing in `setup.py`; validated with `CINDERX_ENABLE_LTO=0` |
| ARM host initially missed system build prerequisite `m4` for getdeps autoconf path | Installed with `dnf install -y m4` |

## Resources
- `setup.py`
- `task_plan.md`
- `progress.md`
- Skill docs:
  - `C:/Users/Administrator/.codex/superpowers/skills/using-superpowers/SKILL.md`
  - `C:/Users/Administrator/.codex/planning-with-files/.codex/skills/planning-with-files/SKILL.md`
  - `C:/Users/Administrator/.codex/superpowers/skills/brainstorming/SKILL.md`
  - `C:/Users/Administrator/.codex/superpowers/skills/writing-plans/SKILL.md`
  - `C:/Users/Administrator/.codex/superpowers/skills/test-driven-development/SKILL.md`
  - `C:/Users/Administrator/.codex/superpowers/skills/verification-before-completion/SKILL.md`

## Visual/Browser Findings
- No browser or image operations used yet.

---
*Remote verification evidence updated on 2026-02-24 against `124.70.162.35`.*

## 2026-02-25 ARM verification (124.70.162.35)

- Scope: verify `ENABLE_ADAPTIVE_STATIC_PYTHON` works both without LTO and with LTO enabled.
- Build environment: `/root/venv-cinderx314` + Python 3.14 on aarch64.

### Code/Build adjustments used in this run

- `CMakeLists.txt` LTO logic keeps `ld.lld` preference for Clang LTO.
- `CMakeLists.txt` FetchContent sources switched from `GIT_REPOSITORY` to fixed `codeload.github.com` tarball URLs for:
  - `asmjit`
  - `fmt`
  - `parallel-hashmap`
  - `usdt`

### Validation results

1. No-LTO build/install

- Command:
  - `env CINDERX_ENABLE_PGO=0 CINDERX_ENABLE_LTO=0 python setup.py install`
- Log: `/tmp/cinderx_no_lto.log`
- Result:
  - Build reached `[100%] Built target _cinderx` and install phase (`install_lib`, `install_egg_info`, `install_scripts`).
  - Runtime probe: `ADAPTIVE_STATIC True`

2. LTO build/install

- Command:
  - `env CINDERX_ENABLE_PGO=0 CINDERX_ENABLE_LTO=1 python setup.py install`
- Log: `/tmp/cinderx_with_lto.log`
- Result:
  - Log contains `LTO: Enabled (full LTO)` and reaches install phase (`install_lib`, `install_egg_info`, `install_scripts`).
  - Runtime probe: `ADAPTIVE_STATIC True`
  - LTO evidence on generated build files:
    - `scratch/temp.linux-aarch64-cpython-314/CMakeCache.txt`: `ENABLE_LTO:BOOL=ON`
    - `scratch/temp.linux-aarch64-cpython-314/CMakeFiles/*/flags.make`: contains `-flto`
    - `scratch/temp.linux-aarch64-cpython-314/CMakeFiles/_cinderx.dir/link.txt`: contains `-flto -fuse-ld=lld`

3. End-to-end smoke

- Command:
  - `python cinderx/PythonLib/test_cinderx/test_oss_quick.py`
- Result:
  - `Ran 2 tests ... OK`
