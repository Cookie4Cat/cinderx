# ARM `autojit=11` `pyperformance nbody` crash investigation

## Scope

Investigate the ARM-only crash seen from commit `7d4d938a` when running
`pyperformance` with `CINDERX_WORKER_PYTHONJITAUTO=11`.

The original reproducer is:

```bash
PYTHONJITTYPEANNOTATIONGUARDS=1 \
PYTHONJITENABLEHIRINLINER=1 \
PYTHONPATH="$PWD/scripts/arm/pyperf_env_hook:$PYTHONPATH" \
CINDERX_WORKER_PYTHONJITAUTO=11 \
PYTHONJITSPECIALIZEDOPCODES=1 \
$MYPY -m pyperformance run --affinity=128 --warmup 3 \
  --inherit-environ http_proxy,https_proxy,LD_LIBRARY_PATH,PYTHONPATH,\
CINDERX_WORKER_PYTHONJITAUTO,PYTHONJITSPECIALIZEDOPCODES,\
PYTHONJITENABLEHIRINLINER,PYTHONJITTYPEANNOTATIONGUARDS \
  -b nbody
```

On the target ARM box, `CINDERX_WORKER_PYTHONJITAUTO<=10` works, while `11`
crashes.

## Reproduction notes

- The `pyperformance` virtualenv must be patched to use
  `--system-site-packages`.
- The ARM machine used during investigation only has 8 cores, so
  `--affinity=128` is invalid there and should be replaced with `--affinity=0`
  or omitted when isolating the crash.
- The crash is reproducible in the worker environment created by
  `pyperformance`, not only in the driver environment.

## Investigation steps

### 1. Confirm the threshold behavior

- Verified that `autojit=10` survives once the invalid CPU affinity is removed.
- Verified that `autojit=11` still crashes with the same benchmark and
  environment.
- Matched that split with the existing pyperformance startup guard threshold in
  JIT logic.

### 2. Remove benchmark-only explanations

- Confirmed the failure is not specific to `HIR inliner`,
  `TYPEANNOTATIONGUARDS`, or specialized opcodes.
- Confirmed the crash also reaches pyperf / stdlib / JSON serialization paths,
  not just benchmark math code.

### 3. Track AArch64 deopt corruption

- Added AArch64 deopt tracing in `gen_asm.cpp`.
- Confirmed generator deopts were recovering bogus `deopt_idx` values from the
  stage-1 layout.
- Fixed one real bug in stage-2 metadata recovery so the resume path no longer
  sees obviously invalid deopt indexes.

### 4. Fix startup import re-entrancy

- Found that `HIRBuilder::emitStoreSubscr()` indirectly imported stdlib
  `array` from the compiler through `getStdlibArrayType()`.
- That re-entered import machinery while compiling importlib startup code and
  caused an earlier ARM crash before the benchmark itself.
- Changed the builder to consult `sys.modules` instead of importing `array`
  during compilation.

### 5. Isolate the remaining generator crash

- After the startup fix, the remaining crash consistently moved into
  `json.encoder`, specifically
  `_make_iterencode.<locals>._iterencode_list`.
- Added deopt-reason and descriptor tracing.
- Confirmed the remaining crash is tied to `descr=InitialYield`.

### 6. Narrow the remaining `InitialYield` failure

- Treated non-exceptional generator yield-like deopts as yield paths instead of
  aborting as unhandled exceptions.
- Added `InitialYield`-specific resume tracing.
- Preserved the created generator frame on `InitialYield` deopt instead of
  reifying it as a normal suspended frame.
- Returned the generator object from `resumeInInterpreter()` for
  `InitialYield`.
- Routed generator deopt exits through the yield epilogue for additional
  validation.

## Problems confirmed during the investigation

### Fixed / improved

1. Startup import re-entrancy from the HIR builder.
2. AArch64 generator deopt `code_runtime` / metadata marshalling issues.
3. AArch64 resume paths receiving clearly bogus deopt indexes.
4. `InitialYield` being classified as an aborting unhandled-exception path.

### Still unresolved

1. `pyperformance -b nbody` with `CINDERX_WORKER_PYTHONJITAUTO=11` still fails
   on ARM.
2. The remaining failure is after `resumeInInterpreter()` has already handled
   the `InitialYield` case and returned the generator object.
3. The current evidence points to the final AArch64 native return path after
   `InitialYield` deopt, not to Python-level generator semantics anymore.

## Current status

The latest run reaches:

- `deopt reason idx=0 reason=1`
- `code=_make_iterencode.<locals>._iterencode_list`
- `descr=InitialYield`
- `initialyield resume return result=...`

and then still terminates with `Bus error`.

That means:

- `InitialYield` is now positively identified.
- The dedicated `InitialYield` resume branch executes.
- The remaining crash happens after that branch returns, in the AArch64
  deopt-to-native return sequence.

## Code touched in this investigation

- `cinderx/Jit/hir/builder.cpp`
- `cinderx/Jit/deopt.cpp`
- `cinderx/Jit/codegen/gen_asm.cpp`

## Recommended next step

Continue from the AArch64 trampoline after `resumeInInterpreter()` returns:

- add one more post-resume trace point immediately before the final branch to
  the real epilogue, or
- map the crash PC back to the generated trampoline instruction sequence.

The remaining bug no longer looks like a high-level generator semantic issue.
It looks like a final AArch64 return-path corruption after `InitialYield`
deopt handling has already completed.
