Posted the generators follow-up analysis as a dedicated issue.

Issue summary:
- after the earlier generator field-lowering and decref-compaction work, the
  remaining profitable hotspot was `Tree.__iter__` truthiness lowering
- `self.left` / `self.right` still paid `PyObject_IsTrue` on the hot path even
  though the benchmark is dominated by `Tree` and `None`
- the fix extends `IsTruthy` lowering with:
  - `Py_None` false fast path
  - exact-bool fast path
  - default-truthy fast path for objects with no `nb_bool`, `mp_length`, or
    `sq_length`
  - helper fallback preserved for types that still need dynamic truthiness

Verification recorded on the issue:
- unified ARM entry passed (`scripts/arm/remote_update_build_test.sh`)
- `BENCH=generators` gate passed
- final pyperformance artifacts:
  - jitlist: `0.06811246101278812 s`
  - autojit50: `0.0719388599973172 s`
- same-host direct hot A/B:
  - `0.39330390794202685 s -> 0.3489009899785742 s`
  - about `11.29%` better on median wall time

The code change and regression coverage in this MR line up with that issue.
