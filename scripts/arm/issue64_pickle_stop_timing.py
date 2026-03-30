#!/usr/bin/env python3
import io
import pickle
import time

import cinderx.jit as jit


DATA = [dict(i=i, s=("v%d" % i), b=(b"x" * 16)) for i in range(2000)]
PAYLOAD = pickle.dumps(DATA, protocol=5)


def run_once():
    return pickle._Unpickler(io.BytesIO(PAYLOAD)).load()


def main() -> None:
    jit.enable()
    jit.enable_specialized_opcodes()
    jit.compile_after_n_calls(1000000)

    assert jit.force_compile(pickle._Unpickler.load)
    assert jit.is_jit_compiled(pickle._Unpickler.load)

    for _ in range(20):
        run_once()

    jit.get_and_clear_runtime_stats()
    vals = []
    total = 0
    for _ in range(5):
        t0 = time.perf_counter()
        total = 0
        for _ in range(200):
            total += len(run_once())
        vals.append(time.perf_counter() - t0)

    stats = jit.get_and_clear_runtime_stats()
    print("SAMPLES", vals)
    print("MEDIAN", sorted(vals)[len(vals) // 2])
    print("TOTAL", total)
    print("DEOPT", stats.get("deopt", []))


if __name__ == "__main__":
    main()
