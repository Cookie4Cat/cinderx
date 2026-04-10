# deepcopy / issue #47 mistake ledger

## Active guardrails

- Do not spend remote time before a failing local regression or targeted reproducer exists.
- Do not move past `HIR` until the current and target HIR shapes are written down.
- Do not repeat a failed remote attempt without either:
  - a new implementation hypothesis, or
  - a new validation step that answers a different question.
- Release every remote lease immediately after logs or benchmark artifacts are copied back.
- Keep key evidence in `findings.md` and `plans/deepcopy-issue.md`, not only in chat.

## Round 1

- Baseline capture miss:
  - the default remote `test_arm_runtime.py` suite is not currently green on this branch, so a plain unified-entrypoint run does not isolate issue #47 by itself.
  - prevention:
    - when the baseline suite is already red, use the same unified entrypoint with `ARM_RUNTIME_SKIP_TESTS` plus a focused `EXTRA_TEST_CMD` to isolate the target reproducer before drawing conclusions.
- New guardrail added:
  - keep a dedicated regression for stdlib `copy._keep_alive` and `copy._deepcopy_tuple` so future work does not silently regress the deterministic KeyError path.
- New miss:
  - the first `_deepcopy_tuple` continuation rewrite can produce malformed HIR/CFG and crash in `removeUnreachableBlocks()`.
  - prevention:
    - before another remote compile, require either:
      - a local CFG sanity argument that every newly allocated block gets an explicit terminator, or
      - a narrower rewrite that only touches `_keep_alive`.
- New miss:
  - the first `_keep_alive` matcher assumed `LOAD_ATTR` was followed immediately by `CALL`, but the real bytecode has an intervening `LOAD_FAST_BORROW x`.
  - prevention:
    - always capture and compare the exact remote `dis` shape before locking a bytecode-pattern matcher for 3.14 stdlib helpers.
- New miss:
  - the first helper miss sentinel used a static `Ref<>`, which crashed on interpreter shutdown when its destructor decref'd after runtime teardown.
  - prevention:
    - for process-lifetime private sentinels in JIT runtime helpers, prefer a raw intentionally leaked `PyObject*` over a static `Ref<>`.
- New miss:
  - branching from a rewrite-created miss block into an existing future bytecode block is unsafe if `translate()` will not subsequently queue and populate that block from the new edge.
  - prevention:
    - any future `_deepcopy_tuple` rewrite must either inline the continuation logic or explicitly respect how `translate()` queues successor blocks after changing `tc.block`.
- New guardrail validated:
  - helper-return miss paths are much safer than synthetic branches into untranslated future bytecode blocks for stdlib exception continuations.
- New process note:
  - the unified entrypoint's built-in single `BENCH` gate is good for one benchmark or a smoke list, but it was awkward for preserving stable multi-benchmark comparison artifacts.
  - prevention:
    - for future broad sweeps, prepare the workdir through the unified entrypoint first, then run a dedicated subset script inside that prepared environment and save stable result JSONs under `artifacts/`.
