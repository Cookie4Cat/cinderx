# ARM vs X86 Richards Optimization Design

Date: 2026-02-20
Scope: CinderX JIT optimization loop with strict sequence:
1) measurement stabilization, 2) JIT policy tuning, 3) ARM hot-path codegen.

## Objective

Establish a reproducible benchmarking pipeline on ARM (`124.70.162.35`) and
X86 (`106.14.164.133`) and drive iterative optimization until ARM richards
performance is at least 3% better than X86 under a unified methodology.

## Constraints

- Primary benchmark: `pyperformance richards`.
- Same driver environment family on both hosts (`venv-cinderx314`).
- Performance claims require repeated/interleaved measurements and confidence
  intervals, not one-shot snapshots.
- Existing ARM runtime/JIT correctness checks must stay green.

## Approach

### Step 1: Measurement stabilization

- Build a single remote benchmark entrypoint that:
  - executes benchmark modes (`nojit`, `jitlist`, `autojit50`),
  - emits structured JSON artifacts,
  - computes summary metrics and ARM-vs-X86 delta.
- Normalize benchmark method:
  - fixed warmup/samples,
  - interleaved execution order,
  - explicit environment capture (host, python, commit, mode).

### Step 2: JIT policy tuning

- Tune without touching codegen:
  - `compile_after_n_calls` threshold candidates,
  - optional lightweight compile budget gating,
  - richer jitlist hotspot coverage for richards call graph.
- Keep one-variable-at-a-time changes to isolate effect.

### Step 3: ARM hot-path codegen optimization

- Target richards-heavy paths:
  - call/method lowering branch cost,
  - guard/deopt branch density,
  - refcount-heavy micro paths.
- Keep code-size regression bounded and track native compiled-size probes.

## Validation

- Functional:
  - `cinderx/PythonLib/test_cinderx/test_arm_runtime.py` (ARM).
- Performance:
  - repeated ARM/X86 richards artifacts via unified entrypoint.
  - ARM improvement target: >= 3% vs X86, with CI-backed interpretation.
- Reporting:
  - append all from->to and decision rationale to `findings.md`.
