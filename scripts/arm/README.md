# ARM Benchmark Utilities (CinderX)

Utilities for quick ARM-side analysis of CinderX on selected `pyperformance` benchmark modules.

Current conventions:
- No benchmark-specific script names (for example no `nbody`-only perf script).
- No specialization toggle in these scripts: `cinderx` mode enables specialized opcodes by default when API exists.

## 1) Single-benchmark trend runner: `bench_single_mode.py`

File: `scripts/arm/bench_single_mode.py`

Purpose:
- Run one benchmark module in `cpython` or `cinderx` mode.
- Do simple warmup + timed rounds.
- Emit JSON summary.

Example:

```bash
/opt/python-3.14/bin/python3.14 /root/work/incoming/bench_single_mode.py \
  --bench nbody \
  --mode cinderx \
  --autojit 1 \
  --warmup-rounds 6 \
  --rounds 10
```

Phase-control options (used by perf script):
- `--wait-after-warmup`: after warmup, print marker and block before measured rounds.
- `--ready-marker`: marker text to print before blocking (default: `READY_FOR_PERF`).
- `--gate-file`: if set, wait until this file appears before measured rounds.
- `--gate-timeout-sec`: timeout for gate-file waiting (`0` means no timeout).

## 2) Warmed IR/ASM dump: `dump_benchmark_warm_ir.py`

File: `scripts/arm/dump_benchmark_warm_ir.py`

Purpose:
- Warm up first, then dump HIR/LIR/ASM from a warmed JIT state.
- Probe targets using `is_jit_compiled`; no force-compile path.

Example:

```bash
/opt/python-3.14/bin/python3.14 /root/work/incoming/dump_benchmark_warm_ir.py \
  --benchmark nbody \
  --autojit 1 \
  --warmup-rounds 6 \
  --outdir /root/work/jit_dump_nbody
```

Key outputs:
- `hir.log`, `lir.log`, `asm.from_elf.txt`
- target slices: `*.hir.txt`, `*.lir.txt`, `*.asm.txt`
- `summary.json` (includes target JIT status)

## 3) Generic perf profiling: `profile_benchmark_perf.sh`

File: `scripts/arm/profile_benchmark_perf.sh`

Purpose:
- Compare `cpython` vs `cinderx` with Linux `perf`.
- Profile only measured rounds, not warmup.

How it works:
1. Start runner process and finish warmup.
2. Runner blocks at phase gate.
3. Attach `perf record -p <pid>`.
4. Release gate and run measured rounds.
5. Stop perf and emit reports.

Example:

```bash
BENCH=nbody \
OUTDIR=/root/work/perf_nbody_smoke \
WARMUP=6 \
ROUNDS=10 \
AUTOJIT=1 \
bash /root/work/incoming/profile_benchmark_perf.sh
```

Useful env vars:
- `BENCH`, `OUTDIR`, `WARMUP`, `ROUNDS`, `AUTOJIT`
- `RUN_ARGS_JSON`, `RUN_REPEAT`
- `EVENT`, `FREQ`, `SORT_KEY`, `ANNOTATE_SYMBOL`
- `READY_TIMEOUT_SEC` (default `120`)
- `PERF_START_DELAY_SEC` (default `1`)

Outputs per mode:
- `run.<mode>.txt`
- `perf.<mode>.data`
- `perf.<mode>.record.log`
- `perf.<mode>.report.txt`
- optional `perf.<mode>.annotate.txt`
