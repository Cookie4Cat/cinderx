# Copyright (c) Meta Platforms, Inc. and affiliates.
import dis
import unittest

import cinderx.opcode as opcode

# pyre-ignore[21]: can't find test.support
from test.support.import_helper import import_module

_opcode = import_module("_opcode")
# pyre-ignore[21]: can't find _opcode
from _opcode import stack_effect

SHADOW_OPS = getattr(opcode, "shadowop", ())


MISSING_STACK_EFFECT = {
    "LOAD_FIELD",
    "STORE_FIELD",
    "LOAD_METHOD_STATIC",
    "INVOKE_METHOD",
    "BUILD_CHECKED_LIST",
    "CAST",
    "LOAD_LOCAL",
    "STORE_LOCAL",
    "PRIMITIVE_BOX",
    "POP_JUMP_IF_ZERO",
    "POP_JUMP_IF_NONZERO",
    "PRIMITIVE_UNBOX",
    "PRIMITIVE_BINARY_OP",
    "PRIMITIVE_UNARY_OP",
    "PRIMITIVE_COMPARE_OP",
    "LOAD_ITERABLE_ARG",
    "LOAD_MAPPING_ARG",
    "INVOKE_FUNCTION",
    "INVOKE_NATIVE",
    "JUMP_IF_ZERO_OR_POP",
    "JUMP_IF_NONZERO_OR_POP",
    "FAST_LEN",
    "CONVERT_PRIMITIVE",
    "LOAD_TYPE",
    "LOAD_CLASS",
    "BUILD_CHECKED_MAP",
    "SEQUENCE_GET",
    "SEQUENCE_SET",
    "LIST_DEL",
    "REFINE_TYPE",
    "PRIMITIVE_LOAD_CONST",
    "RETURN_PRIMITIVE",
    "LOAD_METHOD_SUPER",
    "LOAD_ATTR_SUPER",
    "TP_ALLOC",
}


class CinderX_OpcodeTests(unittest.TestCase):
    def test_stack_effect(self) -> None:
        self.assertEqual(stack_effect(dis.opmap["POP_TOP"]), -1)
        if "DUP_TOP_TWO" in dis.opmap:
            self.assertEqual(stack_effect(dis.opmap["DUP_TOP_TWO"]), 2)
        else:
            self.assertEqual(stack_effect(dis.opmap["COPY"], 1), 1)
        self.assertEqual(
            stack_effect(dis.opmap["BUILD_SLICE"], 0),
            dis.stack_effect(dis.opmap["BUILD_SLICE"], 0),
        )
        self.assertEqual(
            stack_effect(dis.opmap["BUILD_SLICE"], 1),
            dis.stack_effect(dis.opmap["BUILD_SLICE"], 1),
        )
        self.assertEqual(
            stack_effect(dis.opmap["BUILD_SLICE"], 3),
            dis.stack_effect(dis.opmap["BUILD_SLICE"], 3),
        )
        self.assertRaises(ValueError, stack_effect, 30000)
        self.assertEqual(
            stack_effect(dis.opmap["BUILD_SLICE"]),
            dis.stack_effect(dis.opmap["BUILD_SLICE"]),
        )
        self.assertEqual(
            stack_effect(dis.opmap["POP_TOP"], 0),
            dis.stack_effect(dis.opmap["POP_TOP"], 0),
        )
        # All defined opcodes
        for name, code in dis.opmap.items():
            # TASK(T74641077) - Figure out how to deal with static python opcodes
            # pyre-fixme[16]: Module `opcode` has no attribute `shadowop`.
            if name in MISSING_STACK_EFFECT or code in SHADOW_OPS:
                continue

            with self.subTest(opname=name):
                if code < dis.HAVE_ARGUMENT:
                    self.assertEqual(stack_effect(code), dis.stack_effect(code))
                    self.assertEqual(
                        stack_effect(code, 0),
                        dis.stack_effect(code, 0),
                    )
                else:
                    self.assertEqual(stack_effect(code, 0), dis.stack_effect(code, 0))
                    self.assertEqual(stack_effect(code), dis.stack_effect(code))
        # All not defined opcodes
        for code in set(range(256)) - set(dis.opmap.values()):
            with self.subTest(opcode=code):
                self.assertRaises(ValueError, stack_effect, code)
                self.assertRaises(ValueError, stack_effect, code, 0)

    def test_stack_effect_jump(self) -> None:
        if "JUMP_IF_TRUE_OR_POP" in dis.opmap:
            jump_if_true = dis.opmap["JUMP_IF_TRUE_OR_POP"]
            self.assertEqual(stack_effect(jump_if_true, 0), 0)
            self.assertEqual(stack_effect(jump_if_true, 0, jump=True), 0)
            self.assertEqual(stack_effect(jump_if_true, 0, jump=False), -1)
        else:
            jump_if_true = dis.opmap["JUMP_IF_TRUE"]
            self.assertEqual(stack_effect(jump_if_true, 0), 0)
            self.assertEqual(stack_effect(jump_if_true, 0, jump=True), 0)
            self.assertEqual(stack_effect(jump_if_true, 0, jump=False), 0)
        FOR_ITER = dis.opmap["FOR_ITER"]
        self.assertEqual(stack_effect(FOR_ITER, 0), dis.stack_effect(FOR_ITER, 0))
        self.assertEqual(
            stack_effect(FOR_ITER, 0, jump=True),
            dis.stack_effect(FOR_ITER, 0, jump=True),
        )
        self.assertEqual(
            stack_effect(FOR_ITER, 0, jump=False),
            dis.stack_effect(FOR_ITER, 0, jump=False),
        )
        JUMP_FORWARD = dis.opmap["JUMP_FORWARD"]
        self.assertEqual(stack_effect(JUMP_FORWARD, 0), 0)
        self.assertEqual(stack_effect(JUMP_FORWARD, 0, jump=True), 0)
        self.assertEqual(stack_effect(JUMP_FORWARD, 0, jump=False), 0)
        # All defined opcodes
        has_jump = dis.hasjabs + dis.hasjrel
        for name, code in dis.opmap.items():
            # TASK(T74641077) - Figure out how to deal with static python opcodes
            # pyre-fixme[16]: Module `opcode` has no attribute `shadowop`.
            if name in MISSING_STACK_EFFECT or code in SHADOW_OPS:
                continue

            with self.subTest(opname=name):
                if code < dis.HAVE_ARGUMENT:
                    common = stack_effect(code)
                    jump = stack_effect(code, jump=True)
                    nojump = stack_effect(code, jump=False)
                    expected_common = dis.stack_effect(code)
                    expected_jump = dis.stack_effect(code, jump=True)
                    expected_nojump = dis.stack_effect(code, jump=False)
                else:
                    common = stack_effect(code, 0)
                    jump = stack_effect(code, 0, jump=True)
                    nojump = stack_effect(code, 0, jump=False)
                    expected_common = dis.stack_effect(code, 0)
                    expected_jump = dis.stack_effect(code, 0, jump=True)
                    expected_nojump = dis.stack_effect(code, 0, jump=False)
                self.assertEqual(common, expected_common)
                self.assertEqual(jump, expected_jump)
                self.assertEqual(nojump, expected_nojump)


if __name__ == "__main__":
    unittest.main()
