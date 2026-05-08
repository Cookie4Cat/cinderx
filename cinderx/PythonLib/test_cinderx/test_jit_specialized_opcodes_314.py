# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

import dis
import sys
import unittest
from collections.abc import Callable
from typing import TypeVar

import cinderx.jit
from cinderx.test_support import passIf


TCallableRet = TypeVar("TCallableRet")


_all_opnames: list[str] = dis.opname
if hasattr(dis, "_specialized_instructions"):
    _specialized_indices: list[int] = [
        index for index, name in enumerate(_all_opnames) if name.startswith("<")
    ]

    # pyre-ignore[16]: CPython private attribute used by existing tests.
    for index, name in zip(_specialized_indices, dis._specialized_instructions):
        _all_opnames[index] = name


def opnames(func: Callable[..., TCallableRet]) -> list[str]:
    # pyre-fixme[28]: Unexpected keyword argument `adaptive`.
    bytecode = dis.Bytecode(func, adaptive=True)
    return [_all_opnames[insn.opcode] for insn in bytecode]


def specialize_and_compile(
    func: Callable[..., TCallableRet],
    warmup_call: Callable[[], TCallableRet],
    expected_opcode: str,
) -> None:
    cinderx.jit.force_uncompile(func)
    cinderx.jit.jit_suppress(func)

    for _ in range(5):
        warmup_call()

    specialized_opnames = opnames(func)
    if expected_opcode not in specialized_opnames:
        raise AssertionError(
            f"expected {expected_opcode} in adaptive bytecode, "
            f"found {specialized_opnames}"
        )

    cinderx.jit.jit_unsuppress(func)
    cinderx.jit.force_compile(func)


@unittest.skipIf(
    sys.version_info < (3, 14),
    "BINARY_OP_SUBSCR_* specialized opcodes are CPython 3.14+ only",
)
@passIf(not cinderx.jit.is_enabled(), "Tests functionality on the JIT")
class SpecializedOpcodes314Tests(unittest.TestCase):
    def setUp(self) -> None:
        cinderx.jit.enable_specialized_opcodes()

    def tearDown(self) -> None:
        cinderx.jit.disable_specialized_opcodes()

    def test_binary_op_subscr_dict(self) -> None:
        def f(a: dict[str, str], b: str) -> str:
            return a[b]

        specialize_and_compile(
            f, lambda: f({"a": "b"}, "a"), "BINARY_OP_SUBSCR_DICT"
        )

        self.assertEqual(f({"c": "d"}, "c"), "d")
        with self.assertRaises(KeyError):
            f({"c": "d"}, "missing")

        class DictSubclass(dict[str, str]):
            pass

        self.assertEqual(f(DictSubclass({"e": "f"}), "e"), "f")

    def test_binary_op_subscr_list_int(self) -> None:
        def f(a: list[str], b: int) -> str:
            return a[b]

        specialize_and_compile(
            f, lambda: f(["a", "b"], 0), "BINARY_OP_SUBSCR_LIST_INT"
        )

        self.assertEqual(f(["c", "d"], 0), "c")
        self.assertEqual(f(["c", "d"], True), "d")
        with self.assertRaises(IndexError):
            f(["c", "d"], 2)

        class ListSubclass(list[str]):
            pass

        self.assertEqual(f(ListSubclass(["e", "f"]), 1), "f")

    def test_binary_op_subscr_tuple_int(self) -> None:
        def f(a: tuple[str, ...], b: int) -> str:
            return a[b]

        specialize_and_compile(
            f, lambda: f(("a", "b"), 0), "BINARY_OP_SUBSCR_TUPLE_INT"
        )

        self.assertEqual(f(("c", "d"), 0), "c")
        self.assertEqual(f(("c", "d"), True), "d")
        with self.assertRaises(IndexError):
            f(("c", "d"), 2)

        class TupleSubclass(tuple[str, ...]):
            pass

        self.assertEqual(f(TupleSubclass(("e", "f")), 1), "f")


if __name__ == "__main__":
    unittest.main()
