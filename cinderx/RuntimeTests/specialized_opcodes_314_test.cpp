// Copyright (c) Meta Platforms, Inc. and affiliates.

#include <gtest/gtest.h>

#include "cinderx/Common/ref.h"
#include "cinderx/Interpreter/cinder_opcode.h"
#include "cinderx/Jit/bytecode.h"
#include "cinderx/Jit/hir/hir.h"
#include "cinderx/Jit/hir/phi_elimination.h"
#include "cinderx/Jit/hir/printer.h"
#include "cinderx/Jit/hir/simplify.h"
#include "cinderx/Jit/hir/ssa.h"
#include "cinderx/RuntimeTests/fixtures.h"

#include <string>

#if PY_VERSION_HEX >= 0x030E0000

namespace {

using namespace jit::hir;

bool contains(const std::string& haystack, const std::string& needle) {
  return haystack.find(needle) != std::string::npos;
}

Ref<> makeUnicode(const char* value) {
  return Ref<>::steal(PyUnicode_FromString(value));
}

Ref<> makeLong(long value) {
  return Ref<>::steal(PyLong_FromLong(value));
}

Ref<> makeDictArg() {
  auto dict = Ref<>::steal(PyDict_New());
  if (dict == nullptr) {
    return nullptr;
  }
  auto key = makeUnicode("a");
  auto value = makeUnicode("b");
  if (key == nullptr || value == nullptr) {
    return nullptr;
  }
  if (PyDict_SetItem(dict, key, value) != 0) {
    return nullptr;
  }
  return dict;
}

Ref<> makeListArg() {
  auto list = Ref<>::steal(PyList_New(2));
  if (list == nullptr) {
    return nullptr;
  }
  auto first = makeUnicode("a");
  auto second = makeUnicode("b");
  if (first == nullptr || second == nullptr) {
    return nullptr;
  }
  if (PyList_SetItem(list, 0, first.release()) != 0) {
    return nullptr;
  }
  if (PyList_SetItem(list, 1, second.release()) != 0) {
    return nullptr;
  }
  return list;
}

Ref<> makeTupleArg() {
  auto tuple = Ref<>::steal(PyTuple_New(2));
  if (tuple == nullptr) {
    return nullptr;
  }
  auto first = makeUnicode("a");
  auto second = makeUnicode("b");
  if (first == nullptr || second == nullptr) {
    return nullptr;
  }
  if (PyTuple_SetItem(tuple, 0, first.release()) != 0) {
    return nullptr;
  }
  if (PyTuple_SetItem(tuple, 1, second.release()) != 0) {
    return nullptr;
  }
  return tuple;
}

} // namespace

class SpecializedOpcodes314Test : public RuntimeTest {
 protected:
  Ref<PyFunctionObject> compileSubscriptFunction() {
    const char* src = R"(
def test(container, key):
    return container[key]
)";
    Ref<PyFunctionObject> func(compileAndGet(src, "test"));
    return func;
  }

  void warmup(BorrowedRef<PyFunctionObject> func, BorrowedRef<> arg0, BorrowedRef<> arg1) {
    for (int i = 0; i < 5; ++i) {
      auto result = Ref<>::steal(
          PyObject_CallFunctionObjArgs(func.getObj(), arg0.get(), arg1.get(), nullptr));
      ASSERT_NE(result, nullptr);
    }
  }

  bool hasSpecializedOpcode(BorrowedRef<PyFunctionObject> func, int opcode) {
    auto code = reinterpret_cast<PyCodeObject*>(func->func_code);
    jit::BytecodeInstructionBlock block{code};
    for (auto it = block.begin(); it != block.end(); ++it) {
      if (it->specializedOpcode() == opcode) {
        return true;
      }
    }
    return false;
  }

  std::string buildHIRText(BorrowedRef<PyFunctionObject> func) {
    auto irfunc = buildHIR(func);
    return HIRPrinter{}.ToString(*irfunc);
  }

  std::string buildSimplifiedHIRText(BorrowedRef<PyFunctionObject> func) {
    auto irfunc = buildHIR(func);
    SSAify{}.Run(*irfunc);
    Simplify{}.Run(*irfunc);
    PhiElimination{}.Run(*irfunc);
    return HIRPrinter{}.ToString(*irfunc);
  }
};

TEST_F(SpecializedOpcodes314Test, BinaryOpSubscrDictFeedsHIRGuards) {
  auto func = compileSubscriptFunction();
  ASSERT_NE(func, nullptr);
  auto dict = makeDictArg();
  auto key = makeUnicode("a");
  ASSERT_NE(dict, nullptr);
  ASSERT_NE(key, nullptr);

  warmup(func, dict, key);

  ASSERT_TRUE(hasSpecializedOpcode(func, BINARY_OP_SUBSCR_DICT));
  auto hir = buildHIRText(func);
  EXPECT_TRUE(contains(hir, "GuardType<DictExact>")) << hir;
  EXPECT_TRUE(contains(hir, "BinaryOp<Subscript>")) << hir;
}

TEST_F(SpecializedOpcodes314Test, BinaryOpSubscrListIntFeedsHIRGuards) {
  auto func = compileSubscriptFunction();
  ASSERT_NE(func, nullptr);
  auto list = makeListArg();
  auto index = makeLong(0);
  ASSERT_NE(list, nullptr);
  ASSERT_NE(index, nullptr);

  warmup(func, list, index);

  ASSERT_TRUE(hasSpecializedOpcode(func, BINARY_OP_SUBSCR_LIST_INT));
  auto hir = buildHIRText(func);
  EXPECT_TRUE(contains(hir, "GuardType<ListExact>")) << hir;
  EXPECT_TRUE(contains(hir, "GuardType<LongExact>")) << hir;
  EXPECT_TRUE(contains(hir, "BinaryOp<Subscript>")) << hir;

  auto simplified_hir = buildSimplifiedHIRText(func);
  EXPECT_TRUE(contains(simplified_hir, "LoadArrayItem")) << simplified_hir;
}

TEST_F(SpecializedOpcodes314Test, BinaryOpSubscrTupleIntFeedsHIRGuards) {
  auto func = compileSubscriptFunction();
  ASSERT_NE(func, nullptr);
  auto tuple = makeTupleArg();
  auto index = makeLong(0);
  ASSERT_NE(tuple, nullptr);
  ASSERT_NE(index, nullptr);

  warmup(func, tuple, index);

  ASSERT_TRUE(hasSpecializedOpcode(func, BINARY_OP_SUBSCR_TUPLE_INT));
  auto hir = buildHIRText(func);
  EXPECT_TRUE(contains(hir, "GuardType<TupleExact>")) << hir;
  EXPECT_TRUE(contains(hir, "GuardType<LongExact>")) << hir;
  EXPECT_TRUE(contains(hir, "BinaryOp<Subscript>")) << hir;

  auto simplified_hir = buildSimplifiedHIRText(func);
  EXPECT_TRUE(contains(simplified_hir, "LoadArrayItem")) << simplified_hir;
}

#endif
