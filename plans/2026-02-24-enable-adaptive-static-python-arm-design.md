# Enable Adaptive Static Python on 3.14 ARM Design

## Scope
- Target platform: official CPython 3.14 on ARM server.
- Goal: make `ENABLE_ADAPTIVE_STATIC_PYTHON` default-enabled for this target while keeping risk minimal on other targets.

## Approved Approach
- Default enablement rule:
  - Keep existing Meta 3.12 behavior.
  - Add ARM-specific default enablement for CPython 3.14 (`aarch64`/`arm64`).
  - Keep environment variable override behavior unchanged.
- Add explicit runtime introspection API from `_cinderx`:
  - `is_adaptive_static_python_enabled() -> bool`
  - Purpose: prove enablement deterministically in validation.
- Extend OSS quick validation path (`test_oss_quick.py`) so remote getdeps test can assert:
  - cinderx import/init succeeds
  - adaptive-static enabled state matches platform expectation
  - adaptive control API path remains callable.

## Why This Approach
- Lowest regression surface versus enabling globally for all 3.14+ targets.
- Produces a first-class, machine-checkable signal for "enabled" rather than inferring from logs.
- Reuses existing remote validation entrypoint with minimal workflow changes.

## Risks and Mitigations
- Risk: ARM behavior drift across distributions.
  - Mitigation: machine-based predicate (`aarch64`/`arm64`) and remote host verification.
- Risk: false confidence from import-only smoke tests.
  - Mitigation: quick test extension to include feature-state assertions.
- Risk: inability to remotely execute from this session due SSH auth.
  - Mitigation: provide exact remote commands and collect outputs into `findings.md`.

## Verification Strategy
- Build/install on ARM target.
- Run canonical getdeps test entry.
- Assert `cinderx.is_adaptive_static_python_enabled()` is true on 3.14 ARM default build.
- Run A/B (`ENABLE_ADAPTIVE_STATIC_PYTHON=0/1`) for behavior/perf evidence and log key outputs.
