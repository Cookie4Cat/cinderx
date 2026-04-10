# Findings: issue-22 generators attr/decref optimization

## Remote Verification
- Host: `124.70.162.35`
- Entry: `scripts/arm/remote_update_build_test.sh`
- Mode: remote source sync, wheel build, install, ARM runtime validation
- Options: `PARALLEL=6`, `CINDERX_BUILD_JOBS=6`, `FORCE_CLEAN_BUILD=1`, `SKIP_PYPERF=1`

## Confirmed Results
- The standard remote entry flow completed successfully end-to-end.
- A targeted generators repro after install showed:
  - `LoadField = 20`
  - `LoadAttrCached = 0`
  - `BatchDecref = 0`
  - `Decref = 10`
  - output sequence: `[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]`
- After the second-phase generator-only decref lowering change, a targeted remote LIR repro showed:
  - `bb_count = 43`
  - `compiled_size = 2424`
  - output sequence still `[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]`

## Key Conclusion
- The dominant issue confirmed here was not generic `LoadAttrCached` CSE.
- The more important blocker was that low-local generator helpers were excluded from the existing `LOAD_ATTR_INSTANCE_VALUE` lowering path by the `co_nlocals` threshold.
- Allowing generators through that path eliminates the cached attribute C calls entirely for the tested iterator shape.

## Remaining Gap
- Refcount/decref expansion remains visible:
  - `Decref = 10`
  - `BatchDecref = 0`
- The generator-specific helper lowering reduced code size / block count pressure, but it does not remove HIR decref sites.
- A future follow-up could still pursue smarter HIR-level decref batching or motion if more performance is needed.
