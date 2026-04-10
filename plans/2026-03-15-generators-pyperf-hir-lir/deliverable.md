# Deliverable: pyperformance generators HIR/LIR optimization

The remaining profitable `pyperformance generators` work on this branch was no
longer in high-level generator HIR shape; the earlier field-lowering and
generator-decref fixes had already removed the bigger HIR issues. The next hot
cost was `IsTruthy` lowering in `Tree.__iter__`, where `self.left` /
`self.right` still paid the generic `PyObject_IsTrue` helper on the hot path.

The implemented fix extends `Opcode::kIsTruthy` lowering in
`cinderx/Jit/lir/generator.cpp` with a broader compare-based fast path:
- `obj is Py_None` returns false immediately
- exact `bool` keeps the existing `Py_True` compare
- objects with no `nb_bool`, `mp_length`, or `sq_length` slots return true
- everything else still falls back to `PyObject_IsTrue`

Regression coverage was added in
`cinderx/PythonLib/test_cinderx/test_arm_runtime.py` via
`test_istruthy_plain_object_uses_default_truthy_fast_path`, and the existing
generator compactness guard was rebased to the new stable shape
(`bb_count <= 72`, `compiled_size <= 3000`).

Remote verification through the unified ARM entry succeeded:
- TDD run (`SKIP_PYPERF=1`): `Ran 49 tests ... OK`
- Final run (`SKIP_PYPERF=0`, `BENCH=generators`): `Ran 49 tests ... OK`
- pyperformance artifacts:
  - jitlist: `0.06811246101278812 s`
  - autojit50: `0.0719388599973172 s`

For a cleaner same-host comparison, a direct hot-run A/B on `bm_generators`
showed:
- old median wall: `0.39330390794202685 s`
- new median wall: `0.3489009899785742 s`
- improvement: about `11.29%`
