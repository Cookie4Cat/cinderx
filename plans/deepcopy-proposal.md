## Proposal

- Case: `deepcopy`
- Issue: `#47`
- Symptom: JIT-compiled helpers with `try/except KeyError` only generate try-body machine code, so the expected miss path deopts with `UnhandledException` instead of running the `except` body in compiled code.
- Primary hypothesis: the HIR builder is not preserving exception-handler control flow for normal `try/except` regions, at least for the `BINARY_SUBSCR` KeyError pattern used by `copy._keep_alive` and `copy._deepcopy_tuple`.
- Planned order: `HIR -> LIR -> codegen`
- Validation:
  - add a minimal regression test for a hot `dict` miss inside `try/except KeyError`
  - capture current ARM HIR + deopt evidence through the unified remote entrypoint
  - implement the smallest HIR fix first
  - re-run ARM verify/benchmark and the requested regression subset
- Risks:
  - a generic exception-edge fix may be correctness-sensitive
  - a narrow pattern rewrite may solve `deepcopy` but leave the general issue partially open
- Exit criteria:
  - no deterministic `UnhandledException` deopt on the expected `KeyError` path for the reproducer
  - `deepcopy` shows clear ARM improvement
  - requested regression subset does not materially regress
