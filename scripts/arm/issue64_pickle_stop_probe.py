#!/usr/bin/env python3
import io
import pickle

import cinderx.jit as jit


DATA = [{"i": i, "s": f"v{i}", "b": b"x" * 16} for i in range(2000)]
PAYLOAD = pickle.dumps(DATA, protocol=5)


def run_once():
    return pickle._Unpickler(io.BytesIO(PAYLOAD)).load()


def main() -> None:
    jit.enable()
    jit.enable_specialized_opcodes()
    jit.compile_after_n_calls(1000000)

    assert jit.force_compile(pickle._Unpickler.load)
    assert jit.is_jit_compiled(pickle._Unpickler.load)

    jit.get_and_clear_runtime_stats()

    total = 0
    for _ in range(200):
        total += len(run_once())

    stats = jit.get_and_clear_runtime_stats()
    load_stop_deopts = 0
    load_deopts = 0
    for entry in stats.get("deopt", []):
        normal = entry["normal"]
        count = entry["int"]["count"]
        if normal.get("func_qualname") == "_Unpickler.load_stop":
            if normal.get("reason") == "Raise":
                load_stop_deopts += count
        elif normal.get("func_qualname") == "_Unpickler.load":
            if normal.get("reason") == "UnhandledException":
                load_deopts += count

    print(load_stop_deopts)
    print(load_deopts)
    print(total)


if __name__ == "__main__":
    main()
