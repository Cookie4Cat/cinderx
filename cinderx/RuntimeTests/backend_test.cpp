// Copyright (c) Meta Platforms, Inc. and affiliates.

#include <gtest/gtest.h>

#include <cstring>

#include "cinderx/Common/ref.h"
#include "cinderx/Jit/bytecode.h"
#include "cinderx/Jit/codegen/arch.h"
#include "cinderx/Jit/codegen/autogen.h"
#include "cinderx/Jit/codegen/environ.h"
#include "cinderx/Jit/codegen/gen_asm.h"
#include "cinderx/Jit/jit_rt.h"
#include "cinderx/Jit/lir/inliner.h"
#include "cinderx/Jit/lir/instruction.h"
#include "cinderx/Jit/lir/parser.h"
#include "cinderx/Jit/lir/postalloc.h"
#include "cinderx/Jit/lir/postgen.h"
#include "cinderx/Jit/lir/regalloc.h"
#include "cinderx/RuntimeTests/fixtures.h"
#include "cinderx/module_state.h"

#include <regex>
#include <sstream>

#ifdef BUCK_BUILD
#include "tools/cxx/Resources.h"
#endif

using namespace jit;
using namespace jit::lir;

namespace jit::codegen {

class BackendTest : public RuntimeTest {
 public:
  // compile a function without generating prologue and epilogue.
  // the function is self-contained.
  // this function is used to test LIR, rewrite passes, register allocation,
  // and machine code generation.
  void* SimpleCompile(Function* lir_func, int arg_buffer_size = 0) {
    Environ environ;
    InitEnviron(environ);
    PostGenerationRewrite post_gen(lir_func, &environ);
    post_gen.run();

    LinearScanAllocator lsalloc(lir_func);
    lsalloc.run();

    environ.shadow_frames_and_spill_size = lsalloc.getFrameSize();
    environ.changed_regs = lsalloc.getChangedRegs();

    PostRegAllocRewrite post_rewrite(lir_func, &environ);
    post_rewrite.run();

    asmjit::CodeHolder code;
    ICodeAllocator* code_allocator =
        cinderx::getModuleState()->code_allocator.get();
    code.init(code_allocator->asmJitEnvironment());

    arch::Builder as(&code);

    environ.as = &as;

#if defined(CINDER_X86_64)
    as.push(asmjit::x86::rbp);
    as.mov(asmjit::x86::rbp, asmjit::x86::rsp);
#elif defined(CINDER_AARCH64)
    as.stp(arch::fp, arch::lr, asmjit::a64::ptr_pre(asmjit::a64::sp, -16));
    as.mov(arch::fp, asmjit::a64::sp);
#else
    CINDER_UNSUPPORTED
#endif

    auto saved_regs = environ.changed_regs & CALLEE_SAVE_REGS;

#if defined(CINDER_X86_64)
    int saved_regs_size = saved_regs.count() * 8;
#elif defined(CINDER_AARCH64)
    int saved_regs_size = saved_regs.count() * 16;
#else
    CINDER_UNSUPPORTED
    int saved_regs_size = saved_regs.count() * 8;
#endif

    // Allocate stack space for the function's stack.
    // Allocate 8 bytes for the function's stack.
    // If the stack size is not a multiple of 16, add 8 bytes to the stack size.
    // This is to ensure that the stack is aligned to 16 bytes.

    int allocate_stack = std::max(environ.shadow_frames_and_spill_size, 8);
    if ((allocate_stack + saved_regs_size + arg_buffer_size) % 16 != 0) {
      allocate_stack += 8;
    }

#if defined(CINDER_X86_64)
    // Allocate stack space and save the size of the function's stack.
    as.sub(asmjit::x86::rsp, allocate_stack);

    // Push used callee-saved registers.
    std::vector<int> pushed_regs;
    pushed_regs.reserve(saved_regs.count());
    while (!saved_regs.Empty()) {
      as.push(asmjit::x86::gpq(saved_regs.GetFirst().loc));
      pushed_regs.push_back(saved_regs.GetFirst().loc);
      saved_regs.RemoveFirst();
    }

    if (arg_buffer_size > 0) {
      as.sub(asmjit::x86::rsp, arg_buffer_size);
    }

    NativeGenerator gen(nullptr);
    gen.env_ = std::move(environ);
    gen.lir_func_.reset(lir_func);
    gen.generateAssemblyBody(code);

    if (arg_buffer_size > 0) {
      as.add(asmjit::x86::rsp, arg_buffer_size);
    }

    for (auto riter = pushed_regs.rbegin(); riter != pushed_regs.rend();
         ++riter) {
      as.pop(asmjit::x86::gpq(*riter));
    }

    as.leave();
    as.ret();
#elif defined(CINDER_AARCH64)
    // Allocate stack space and save the size of the function's stack.
    JIT_CHECK(allocate_stack % kStackAlign == 0, "unaligned");
    as.sub(asmjit::a64::sp, asmjit::a64::sp, allocate_stack);

    // Push used callee-saved registers, handling GP and FP separately.
    auto gp_regs = saved_regs & ALL_GP_REGISTERS;
    auto vecd_regs = saved_regs & ALL_VECD_REGISTERS;

    std::vector<int> pushed_gp_regs;
    pushed_gp_regs.reserve(gp_regs.count());
    while (!gp_regs.Empty()) {
      as.str(
          asmjit::a64::x(gp_regs.GetFirst().loc),
          asmjit::a64::ptr_pre(asmjit::a64::sp, -16));
      pushed_gp_regs.push_back(gp_regs.GetFirst().loc);
      gp_regs.RemoveFirst();
    }

    std::vector<int> pushed_vecd_regs;
    pushed_vecd_regs.reserve(vecd_regs.count());
    while (!vecd_regs.Empty()) {
      as.str(
          asmjit::a64::d(vecd_regs.GetFirst().loc - VECD_REG_BASE),
          asmjit::a64::ptr_pre(asmjit::a64::sp, -16));
      pushed_vecd_regs.push_back(vecd_regs.GetFirst().loc);
      vecd_regs.RemoveFirst();
    }

    if (arg_buffer_size > 0) {
      JIT_CHECK(arg_buffer_size % kStackAlign == 0, "unaligned");
      as.sub(asmjit::a64::sp, asmjit::a64::sp, arg_buffer_size);
    }

    NativeGenerator gen(nullptr);
    gen.env_ = std::move(environ);
    gen.lir_func_.reset(lir_func);
    gen.generateAssemblyBody(code);

    if (arg_buffer_size > 0) {
      as.add(asmjit::a64::sp, asmjit::a64::sp, arg_buffer_size);
    }

    for (auto riter = pushed_vecd_regs.rbegin();
         riter != pushed_vecd_regs.rend();
         ++riter) {
      as.ldr(
          asmjit::a64::d(*riter - VECD_REG_BASE),
          asmjit::a64::ptr_post(asmjit::a64::sp, 16));
    }

    for (auto riter = pushed_gp_regs.rbegin(); riter != pushed_gp_regs.rend();
         ++riter) {
      as.ldr(
          asmjit::a64::x(*riter), asmjit::a64::ptr_post(asmjit::a64::sp, 16));
    }

    as.mov(asmjit::a64::sp, arch::fp);
    as.ldp(arch::fp, arch::lr, asmjit::a64::ptr_post(asmjit::a64::sp, 16));
    as.ret(arch::lr);
#else
    NativeGenerator gen(nullptr);
    CINDER_UNSUPPORTED
#endif

    as.finalize();

    AllocateResult result = code_allocator->addCode(&code);
    EXPECT_EQ(result.error, asmjit::kErrorOk);
    EXPECT_TRUE(code_allocator->contains(result.addr))
        << "Compiled function should exist within the CodeAllocator";
    gen.lir_func_.release();
    return result.addr;
  }

  void InitEnviron(Environ& environ) {
    for (const auto& loc : ARGUMENT_REGS) {
      environ.arg_locations.push_back(loc);
    }
  }

  void CheckCast(Function* lir_func) {
    auto func =
        (PyObject * (*)(PyObject*, PyTypeObject*)) SimpleCompile(lir_func);

    auto test_noerror = [&](PyObject* a_in, PyTypeObject* b_in) -> void {
      auto ret_test = func(a_in, b_in);
      ASSERT_TRUE(PyErr_Occurred() == nullptr);
      auto ret_jitrt = JITRT_Cast(a_in, b_in);
      ASSERT_TRUE(PyErr_Occurred() == nullptr);
      ASSERT_EQ(ret_test, ret_jitrt);
    };

    auto test_error = [&](PyObject* a_in, PyTypeObject* b_in) -> void {
      auto ret_test = func(a_in, b_in);
      ASSERT_TRUE(PyErr_ExceptionMatches(PyExc_TypeError));
      PyErr_Clear();

      auto ret_jitrt = JITRT_Cast(a_in, b_in);
      ASSERT_TRUE(PyErr_ExceptionMatches(PyExc_TypeError));
      PyErr_Clear();

      ASSERT_EQ(ret_test, ret_jitrt);
    };

    test_noerror(Py_False, &PyBool_Type);
    test_noerror(Py_False, &PyLong_Type);
    test_error(Py_False, &PyUnicode_Type);
  }
};

namespace {

#if PY_VERSION_HEX >= 0x030E0000
uint16_t readCacheU16(PyCodeObject* code, BCIndex opcode_index, int cache_index) {
  return codeUnit(code)[opcode_index.value() + cache_index].cache;
}

uint32_t readCacheU32(PyCodeObject* code, BCIndex opcode_index, int cache_index) {
  uint32_t lo = readCacheU16(code, opcode_index, cache_index);
  uint32_t hi = readCacheU16(code, opcode_index, cache_index + 1);
  return lo | (hi << 16);
}

PyObject* readCacheObj(PyCodeObject* code, BCIndex opcode_index, int cache_index) {
  PyObject* obj = nullptr;
  std::memcpy(
      &obj,
      &codeUnit(code)[opcode_index.value() + cache_index].cache,
      sizeof(obj));
  return obj;
}

struct SpecializedAttrCache {
  int64_t type_version;
  int64_t offset;
  Ref<> name;
};

struct SpecializedMethodCache {
  int64_t type_version;
  int64_t keys_version;
  Ref<> descr;
  Ref<> name;
};

BytecodeInstruction findSpecializedInstr(
    BorrowedRef<PyCodeObject> code,
    int specialized_opcode) {
  for (auto& instr : BytecodeInstructionBlock{code}) {
    if (instr.specializedOpcode() == specialized_opcode) {
      return instr;
    }
  }
  JIT_ABORT("Failed to find specialized opcode {}", specialized_opcode);
}

SpecializedAttrCache getSpecializedAttrCache(
    BorrowedRef<PyFunctionObject> func,
    int specialized_opcode) {
  auto code = reinterpret_cast<PyCodeObject*>(func->func_code);
  auto instr = findSpecializedInstr(code, specialized_opcode);
  return SpecializedAttrCache{
      static_cast<int64_t>(readCacheU32(code, instr.opcodeIndex(), 2)),
      static_cast<int64_t>(readCacheU16(code, instr.opcodeIndex(), 4)),
      Ref<>::create(PyTuple_GET_ITEM(code->co_names, instr.oparg()))};
}

SpecializedMethodCache getSpecializedMethodCache(
    BorrowedRef<PyFunctionObject> func,
    int specialized_opcode) {
  auto code = reinterpret_cast<PyCodeObject*>(func->func_code);
  auto instr = findSpecializedInstr(code, specialized_opcode);
  return SpecializedMethodCache{
      static_cast<int64_t>(readCacheU32(code, instr.opcodeIndex(), 2)),
      static_cast<int64_t>(readCacheU32(code, instr.opcodeIndex(), 4)),
      Ref<>::create(readCacheObj(code, instr.opcodeIndex(), 6)),
      Ref<>::create(PyTuple_GET_ITEM(code->co_names, loadAttrIndex(instr.oparg())))};
}

Ref<> call1(PyObject* func, BorrowedRef<PyObject> arg) {
  return Ref<>::steal(PyObject_CallFunctionObjArgs(func, arg, nullptr));
}

Ref<> call2(
    PyObject* func,
    BorrowedRef<PyObject> arg0,
    BorrowedRef<PyObject> arg1) {
  return Ref<>::steal(PyObject_CallFunctionObjArgs(func, arg0, arg1, nullptr));
}
#endif

} // namespace

class AttrInstanceValueHelperTest : public RuntimeTest {
 public:
  AttrInstanceValueHelperTest() : RuntimeTest(static_cast<Flags>(0)) {}
};

#if PY_VERSION_HEX >= 0x030E0000
TEST_F(AttrInstanceValueHelperTest, LoadAttrInstanceValueFastPathAndFallbacks) {
  const char* src = R"(
class C:
  pass

def load_x(obj):
  return obj.x
)";
  runCode(src);
  Ref<PyObject> klass(getGlobal("C"));
  Ref<PyFunctionObject> load_x(getGlobal("load_x"));
  ASSERT_NE(klass, nullptr);
  ASSERT_NE(load_x, nullptr);

  Ref<> obj = Ref<>::steal(PyObject_CallFunctionObjArgs(klass, nullptr));
  Ref<> value = Ref<>::steal(PyLong_FromLong(123));
  ASSERT_NE(obj, nullptr);
  ASSERT_NE(value, nullptr);
  ASSERT_EQ(PyObject_SetAttrString(obj, "x", value), 0);

  for (int i = 0; i < 32; i++) {
    auto result = call1(reinterpret_cast<PyObject*>(load_x.get()), obj);
    ASSERT_NE(result, nullptr);
    EXPECT_TRUE(isIntEquals(result, 123));
  }

  auto cache = getSpecializedAttrCache(load_x, LOAD_ATTR_INSTANCE_VALUE);

  auto fast_result = Ref<>::steal(JITRT_LoadAttrInstanceValue(
      obj, cache.type_version, cache.offset, cache.name));
  ASSERT_NE(fast_result, nullptr);
  EXPECT_TRUE(isIntEquals(fast_result, 123));

  auto mismatch_result = Ref<>::steal(JITRT_LoadAttrInstanceValue(
      obj, cache.type_version + 1, cache.offset, cache.name));
  ASSERT_NE(mismatch_result, nullptr);
  EXPECT_TRUE(isIntEquals(mismatch_result, 123));

  Ref<> spill = Ref<>::steal(PyLong_FromLong(999));
  ASSERT_NE(spill, nullptr);
  ASSERT_EQ(PyObject_SetAttrString(obj, "spill", spill), 0);
  PyObject** dictptr = _PyObject_GetDictPtr(obj);
  ASSERT_NE(dictptr, nullptr);
  ASSERT_NE(*dictptr, nullptr);
  ASSERT_NE(_PyObject_GetManagedDict(obj), nullptr);
  _PyObject_InlineValues(obj)->valid = 0;
  auto invalid_result = Ref<>::steal(JITRT_LoadAttrInstanceValue(
      obj, cache.type_version, cache.offset, cache.name));
  ASSERT_NE(invalid_result, nullptr);
  EXPECT_TRUE(isIntEquals(invalid_result, 123));
}

TEST_F(AttrInstanceValueHelperTest, StoreAttrInstanceValueFastPathAndFallbacks) {
  const char* src = R"(
class C:
  pass

def store_x(obj, value):
  obj.x = value
)";
  runCode(src);
  Ref<PyObject> klass(getGlobal("C"));
  Ref<PyFunctionObject> store_x(getGlobal("store_x"));
  ASSERT_NE(klass, nullptr);
  ASSERT_NE(store_x, nullptr);

  Ref<> warm_obj = Ref<>::steal(PyObject_CallFunctionObjArgs(klass, nullptr));
  Ref<> warm_value = Ref<>::steal(PyLong_FromLong(1));
  ASSERT_NE(warm_obj, nullptr);
  ASSERT_NE(warm_value, nullptr);
  for (int i = 0; i < 32; i++) {
    auto result =
        call2(reinterpret_cast<PyObject*>(store_x.get()), warm_obj, warm_value);
    ASSERT_NE(result, nullptr);
    EXPECT_EQ(result.get(), Py_None);
  }

  auto cache = getSpecializedAttrCache(store_x, STORE_ATTR_INSTANCE_VALUE);

  Ref<> fast_obj = Ref<>::steal(PyObject_CallFunctionObjArgs(klass, nullptr));
  Ref<> fast_value = Ref<>::steal(PyLong_FromLong(456));
  ASSERT_NE(fast_obj, nullptr);
  ASSERT_NE(fast_value, nullptr);
  ASSERT_EQ(
      JITRT_StoreAttrInstanceValue(
          fast_obj, cache.type_version, cache.offset, cache.name, fast_value),
      0);
  auto fast_result = Ref<>::steal(PyObject_GetAttrString(fast_obj, "x"));
  ASSERT_NE(fast_result, nullptr);
  EXPECT_TRUE(isIntEquals(fast_result, 456));

  Ref<> mismatch_obj = Ref<>::steal(PyObject_CallFunctionObjArgs(klass, nullptr));
  Ref<> mismatch_value = Ref<>::steal(PyLong_FromLong(789));
  ASSERT_NE(mismatch_obj, nullptr);
  ASSERT_NE(mismatch_value, nullptr);
  ASSERT_EQ(
      JITRT_StoreAttrInstanceValue(
          mismatch_obj,
          cache.type_version + 1,
          cache.offset,
          cache.name,
          mismatch_value),
      0);
  auto mismatch_result =
      Ref<>::steal(PyObject_GetAttrString(mismatch_obj, "x"));
  ASSERT_NE(mismatch_result, nullptr);
  EXPECT_TRUE(isIntEquals(mismatch_result, 789));

  Ref<> managed_obj = Ref<>::steal(PyObject_CallFunctionObjArgs(klass, nullptr));
  Ref<> managed_initial = Ref<>::steal(PyLong_FromLong(5));
  Ref<> managed_value = Ref<>::steal(PyLong_FromLong(111));
  Ref<> managed_spill = Ref<>::steal(PyLong_FromLong(1));
  ASSERT_NE(managed_obj, nullptr);
  ASSERT_NE(managed_initial, nullptr);
  ASSERT_NE(managed_value, nullptr);
  ASSERT_NE(managed_spill, nullptr);
  ASSERT_EQ(PyObject_SetAttrString(managed_obj, "x", managed_initial), 0);
  ASSERT_EQ(PyObject_SetAttrString(managed_obj, "spill", managed_spill), 0);
  PyObject** dictptr = _PyObject_GetDictPtr(managed_obj);
  ASSERT_NE(dictptr, nullptr);
  ASSERT_NE(*dictptr, nullptr);
  ASSERT_NE(_PyObject_GetManagedDict(managed_obj), nullptr);
  ASSERT_EQ(
      JITRT_StoreAttrInstanceValue(
          managed_obj,
          cache.type_version,
          cache.offset,
          cache.name,
          managed_value),
      0);
  auto managed_result =
      Ref<>::steal(PyObject_GetAttrString(managed_obj, "x"));
  ASSERT_NE(managed_result, nullptr);
  EXPECT_TRUE(isIntEquals(managed_result, 111));
}

TEST_F(AttrInstanceValueHelperTest, LoadAttrMethodWithValuesFastPathAndFallbacks) {
  const char* src = R"(
class C:
  def __init__(self):
    self.base = 41

  def f(self, value):
    return self.base + value

def call_f(obj, value):
  return obj.f(value)
)";
  runCode(src);
  Ref<PyObject> klass(getGlobal("C"));
  Ref<PyFunctionObject> call_f(getGlobal("call_f"));
  ASSERT_NE(klass, nullptr);
  ASSERT_NE(call_f, nullptr);

  Ref<> obj = Ref<>::steal(PyObject_CallFunctionObjArgs(klass, nullptr));
  Ref<> value = Ref<>::steal(PyLong_FromLong(1));
  ASSERT_NE(obj, nullptr);
  ASSERT_NE(value, nullptr);

  for (int i = 0; i < 64; i++) {
    auto result = call2(reinterpret_cast<PyObject*>(call_f.get()), obj, value);
    ASSERT_NE(result, nullptr);
    EXPECT_TRUE(isIntEquals(result, 42));
  }

  auto cache = getSpecializedMethodCache(call_f, LOAD_ATTR_METHOD_WITH_VALUES);

  auto fast = JITRT_LoadAttrMethodWithValues(
      obj, cache.type_version, cache.keys_version, cache.descr, cache.name);
  auto fast_callable = Ref<>::steal(fast.callable);
  auto fast_self = Ref<>::steal(fast.self_or_null);
  ASSERT_NE(fast_callable, nullptr);
  ASSERT_NE(fast_self, nullptr);
  EXPECT_EQ(fast_self.get(), obj.get());
  auto fast_result = Ref<>::steal(
      PyObject_CallFunctionObjArgs(
          fast_callable.get(), fast_self.get(), value.get(), nullptr));
  ASSERT_NE(fast_result, nullptr);
  EXPECT_TRUE(isIntEquals(fast_result, 42));

  auto mismatch = JITRT_LoadAttrMethodWithValues(
      obj,
      cache.type_version + 1,
      cache.keys_version,
      cache.descr,
      cache.name);
  auto mismatch_callable = Ref<>::steal(mismatch.callable);
  auto mismatch_self = Ref<>::steal(mismatch.self_or_null);
  ASSERT_NE(mismatch_callable, nullptr);
  ASSERT_NE(mismatch_self, nullptr);
  auto mismatch_result = Ref<>::steal(PyObject_CallFunctionObjArgs(
      mismatch_callable.get(), mismatch_self.get(), value.get(), nullptr));
  ASSERT_NE(mismatch_result, nullptr);
  EXPECT_TRUE(isIntEquals(mismatch_result, 42));

  auto keys_mismatch = JITRT_LoadAttrMethodWithValues(
      obj,
      cache.type_version,
      cache.keys_version + 1,
      cache.descr,
      cache.name);
  auto keys_callable = Ref<>::steal(keys_mismatch.callable);
  auto keys_self = Ref<>::steal(keys_mismatch.self_or_null);
  ASSERT_NE(keys_callable, nullptr);
  ASSERT_NE(keys_self, nullptr);
  auto keys_result = Ref<>::steal(PyObject_CallFunctionObjArgs(
      keys_callable.get(), keys_self.get(), value.get(), nullptr));
  ASSERT_NE(keys_result, nullptr);
  EXPECT_TRUE(isIntEquals(keys_result, 42));

  Ref<> spill = Ref<>::steal(PyLong_FromLong(7));
  ASSERT_NE(spill, nullptr);
  ASSERT_EQ(PyObject_SetAttrString(obj, "spill", spill), 0);
  _PyObject_InlineValues(obj)->valid = 0;
  auto invalid = JITRT_LoadAttrMethodWithValues(
      obj, cache.type_version, cache.keys_version, cache.descr, cache.name);
  auto invalid_callable = Ref<>::steal(invalid.callable);
  auto invalid_self = Ref<>::steal(invalid.self_or_null);
  ASSERT_NE(invalid_callable, nullptr);
  ASSERT_NE(invalid_self, nullptr);
}

TEST_F(AttrInstanceValueHelperTest, LoadAttrMethodWithValuesFallsBackForNonMethodDescr) {
  const char* src = R"(
class C:
  def __init__(self):
    self.base = 41

  def f(self, value):
    return self.base + value

def call_f(obj, value):
  return obj.f(value)
)";
  runCode(src);
  Ref<PyObject> klass(getGlobal("C"));
  Ref<PyFunctionObject> call_f(getGlobal("call_f"));
  ASSERT_NE(klass, nullptr);
  ASSERT_NE(call_f, nullptr);

  Ref<> obj = Ref<>::steal(PyObject_CallFunctionObjArgs(klass, nullptr));
  Ref<> value = Ref<>::steal(PyLong_FromLong(1));
  Ref<> fake_descr = Ref<>::steal(PyLong_FromLong(123));
  ASSERT_NE(obj, nullptr);
  ASSERT_NE(value, nullptr);
  ASSERT_NE(fake_descr, nullptr);

  for (int i = 0; i < 64; i++) {
    auto result = call2(reinterpret_cast<PyObject*>(call_f.get()), obj, value);
    ASSERT_NE(result, nullptr);
    EXPECT_TRUE(isIntEquals(result, 42));
  }

  auto cache = getSpecializedMethodCache(call_f, LOAD_ATTR_METHOD_WITH_VALUES);
  auto fallback = JITRT_LoadAttrMethodWithValues(
      obj, cache.type_version, cache.keys_version, fake_descr, cache.name);
  auto fallback_callable = Ref<>::steal(fallback.callable);
  auto fallback_self = Ref<>::steal(fallback.self_or_null);
  ASSERT_NE(fallback_callable, nullptr);
  ASSERT_NE(fallback_self, nullptr);
  auto fallback_result = Ref<>::steal(PyObject_CallFunctionObjArgs(
      fallback_callable.get(), fallback_self.get(), value.get(), nullptr));
  ASSERT_NE(fallback_result, nullptr);
  EXPECT_TRUE(isIntEquals(fallback_result, 42));
}

TEST_F(AttrInstanceValueHelperTest, BinarySubscrListIntFastPathAndFallbacks) {
  Ref<> list = Ref<>::steal(Py_BuildValue("[ss]", "a", "b"));
  Ref<> zero = Ref<>::steal(PyLong_FromLong(0));
  Ref<> neg_one = Ref<>::steal(PyLong_FromLong(-1));
  Ref<> oob = Ref<>::steal(PyLong_FromLong(99));
  ASSERT_NE(list, nullptr);
  ASSERT_NE(zero, nullptr);
  ASSERT_NE(neg_one, nullptr);
  ASSERT_NE(oob, nullptr);

  auto fast = Ref<>::steal(JITRT_BinarySubscrListInt(list, zero));
  ASSERT_NE(fast, nullptr);
  EXPECT_EQ(PyUnicode_CompareWithASCIIString(fast, "a"), 0);

  auto fallback = Ref<>::steal(JITRT_BinarySubscrListInt(list, neg_one));
  ASSERT_NE(fallback, nullptr);
  EXPECT_EQ(PyUnicode_CompareWithASCIIString(fallback, "b"), 0);

  auto oob_result = Ref<>::steal(JITRT_BinarySubscrListInt(list, oob));
  EXPECT_EQ(oob_result, nullptr);
  ASSERT_TRUE(PyErr_ExceptionMatches(PyExc_IndexError));
  PyErr_Clear();
}

TEST_F(AttrInstanceValueHelperTest, BinarySubscrListSliceFastPathAndFallbacks) {
  Ref<> list = Ref<>::steal(Py_BuildValue("[sss]", "a", "b", "c"));
  Ref<> full_slice = Ref<>::steal(PySlice_New(Py_None, Py_None, Py_None));
  Ref<> partial_slice =
      Ref<>::steal(PySlice_New(PyLong_FromLong(1), Py_None, Py_None));
  ASSERT_NE(list, nullptr);
  ASSERT_NE(full_slice, nullptr);
  ASSERT_NE(partial_slice, nullptr);

  auto fast = Ref<>::steal(JITRT_BinarySubscrListSlice(list, full_slice));
  ASSERT_NE(fast, nullptr);
  ASSERT_TRUE(PyList_Check(fast));
  EXPECT_NE(fast.get(), list.get());
  ASSERT_EQ(PyList_GET_SIZE(fast.get()), 3);
  EXPECT_EQ(
      PyUnicode_CompareWithASCIIString(PyList_GET_ITEM(fast.get(), 0), "a"), 0);

  auto fallback =
      Ref<>::steal(JITRT_BinarySubscrListSlice(list, partial_slice));
  ASSERT_NE(fallback, nullptr);
  ASSERT_TRUE(PyList_Check(fallback));
  ASSERT_EQ(PyList_GET_SIZE(fallback.get()), 2);
  EXPECT_EQ(
      PyUnicode_CompareWithASCIIString(PyList_GET_ITEM(fallback.get(), 0), "b"), 0);
}

TEST_F(AttrInstanceValueHelperTest, MinSingleArgFastPathAndFallbacks) {
  Ref<> set_items = Ref<>::steal(Py_BuildValue("[iii]", 3, 1, 2));
  Ref<> exact = Ref<>::steal(PyFrozenSet_New(set_items));
  ASSERT_NE(exact, nullptr);

  auto fast = Ref<>::steal(JITRT_MinSingleArg(exact));
  ASSERT_NE(fast, nullptr);
  EXPECT_TRUE(isIntEquals(fast, 1));

  Ref<> list = Ref<>::steal(Py_BuildValue("[iii]", 5, 4, 6));
  ASSERT_NE(list, nullptr);
  auto fallback = Ref<>::steal(JITRT_MinSingleArg(list));
  ASSERT_NE(fallback, nullptr);
  EXPECT_TRUE(isIntEquals(fallback, 4));
}

TEST_F(AttrInstanceValueHelperTest, StoreSubscrListIntFastPathAndFallbacks) {
  Ref<> list = Ref<>::steal(Py_BuildValue("[ss]", "a", "b"));
  Ref<> zero = Ref<>::steal(PyLong_FromLong(0));
  Ref<> neg_one = Ref<>::steal(PyLong_FromLong(-1));
  Ref<> oob = Ref<>::steal(PyLong_FromLong(99));
  Ref<> c = Ref<>::steal(PyUnicode_FromString("c"));
  Ref<> d = Ref<>::steal(PyUnicode_FromString("d"));
  ASSERT_NE(list, nullptr);
  ASSERT_NE(zero, nullptr);
  ASSERT_NE(neg_one, nullptr);
  ASSERT_NE(oob, nullptr);
  ASSERT_NE(c, nullptr);
  ASSERT_NE(d, nullptr);

  ASSERT_EQ(JITRT_StoreSubscrListInt(list, zero, c), 0);
  EXPECT_EQ(
      PyUnicode_CompareWithASCIIString(PyList_GET_ITEM(list.get(), 0), "c"), 0);

  ASSERT_EQ(JITRT_StoreSubscrListInt(list, neg_one, d), 0);
  EXPECT_EQ(
      PyUnicode_CompareWithASCIIString(PyList_GET_ITEM(list.get(), 1), "d"), 0);

  EXPECT_EQ(JITRT_StoreSubscrListInt(list, oob, c), -1);
  ASSERT_TRUE(PyErr_ExceptionMatches(PyExc_IndexError));
  PyErr_Clear();
}
#endif

// This is a test harness for experimenting with backends
TEST_F(BackendTest, SimpleLoadAttr) {
  const char* src = R"(
class User:
  def __init__(self, user_id):
    self._user_id = user_id

def get_user_id(user):
    return user._user_id
)";
  Ref<PyObject> globals(MakeGlobals());
  ASSERT_NE(globals.get(), nullptr) << "Failed creating globals";

  auto locals = Ref<>::steal(PyDict_New());
  ASSERT_NE(locals.get(), nullptr) << "Failed creating locals";

  auto st = Ref<>::steal(PyRun_String(src, Py_file_input, globals, locals));
  ASSERT_NE(st.get(), nullptr) << "Failed executing code";

  // Borrowed from locals
  PyObject* get_user_id = PyDict_GetItemString(locals, "get_user_id");
  ASSERT_NE(get_user_id, nullptr) << "Couldn't get get_user_id function";

  // Borrowed from get_user_id
  // code holds the code object for the function
  // code->co_consts holds the constants referenced by LoadConst
  // code->co_names holds the names referenced by LoadAttr
  PyObject* code = PyFunction_GetCode(get_user_id);
  ASSERT_NE(code, nullptr) << "Couldn't get code for user_id";

  // At this point you could patch user_id->vectorcall with a pointer to
  // your generated code for get_user_id.
  //
  // The HIR should be:
  //
  // fun get_user_id {
  //   bb 0 {
  //     CheckVar a0
  //     t0 = LoadAttr a0 0
  //     CheckExc t0
  //     Incref t0
  //     Return t0
  //   }
  // }

  // Create a user object we can use to call our function
  PyObject* user_klass = PyDict_GetItemString(locals, "User");
  ASSERT_NE(user_klass, nullptr) << "Couldn't get class User";

  auto user_id = Ref<>::steal(PyLong_FromLong(12345));
  ASSERT_NE(user_id.get(), nullptr) << "Couldn't create user id";

  auto user = Ref<>::steal(
      PyObject_CallFunctionObjArgs(user_klass, user_id.get(), nullptr));
  ASSERT_NE(user.get(), nullptr) << "Couldn't create user";

  // Finally, call get_user_id
  auto result = Ref<>::steal(
      PyObject_CallFunctionObjArgs(get_user_id, user.get(), nullptr));
  ASSERT_NE(result.get(), nullptr) << "Failed getting user id";
  ASSERT_TRUE(PyLong_CheckExact(result)) << "Incorrect type returned";
  ASSERT_EQ(PyLong_AsLong(result), PyLong_AsLong(user_id))
      << "Incorrect user id returned";
}

TEST_F(BackendTest, CallCountTest) {
  const char* src = R"(
def foo(x: int) -> int:
  return x + 1

for i in range(30):
  foo(i)
)";

  Ref<> foo = compileAndGet(src, "foo");
  ASSERT_TRUE(PyFunction_Check(foo));

  BorrowedRef<PyCodeObject> code =
      reinterpret_cast<PyFunctionObject*>(foo.get())->func_code;

#if PY_VERSION_HEX < 0x030C0000
  uint64_t ncalls = code->co_mutable->ncalls;
#else
  auto extra = codeExtra(code);
  ASSERT_NE(extra, nullptr) << "Failed to load code object extra data";
  uint64_t ncalls = Ci_code_extra_get_calls(extra);
#endif

  // TASK(T190615535): This is waiting on the 3.12 custom interpreter loop.
  // Once we have that in place, we can start incrementing call counts in 3.12.
  ASSERT_EQ(ncalls, 30);
}

// floating-point arithmetic test
TEST_F(BackendTest, FPArithmetic) {
  double a = 3.12;
  double b = 1.1616;

  auto test = [&](Instruction::Opcode opcode) -> double {
    auto lirfunc = std::make_unique<Function>();
    auto bb = lirfunc->allocateBasicBlock();

    auto pa = bb->allocateInstr(
        Instruction::kMove,
        nullptr,
        OutVReg(),
        Imm(reinterpret_cast<uint64_t>(&a)));
    auto fa = bb->allocateInstr(
        Instruction::kMove, nullptr, OutVReg(OperandBase::kDouble), Ind(pa));

    auto pb = bb->allocateInstr(
        Instruction::kMove,
        nullptr,
        OutVReg(),
        Imm(reinterpret_cast<uint64_t>(&b)));
    auto fb = bb->allocateInstr(
        Instruction::kMove, nullptr, OutVReg(OperandBase::kDouble), Ind(pb));

    auto sum = bb->allocateInstr(
        opcode, nullptr, OutVReg(OperandBase::kDouble), VReg(fa), VReg(fb));
    bb->allocateInstr(Instruction::kReturn, nullptr, VReg(sum));

    // need this because the register allocator assumes the basic blocks
    // end with Return should have one and only one successor.
    auto epilogue = lirfunc->allocateBasicBlock();
    bb->addSuccessor(epilogue);

    auto func = (double (*)())SimpleCompile(lirfunc.get());

    return func();
  };

  ASSERT_DOUBLE_EQ(test(Instruction::kFadd), a + b);
  ASSERT_DOUBLE_EQ(test(Instruction::kFsub), a - b);
  ASSERT_DOUBLE_EQ(test(Instruction::kFmul), a * b);
  ASSERT_DOUBLE_EQ(test(Instruction::kFdiv), a / b);
}

TEST_F(BackendTest, FPCompare) {
  double a = 3.12;
  double b = 1.1616;

  auto test = [&](Instruction::Opcode opcode) -> double {
    auto lirfunc = std::make_unique<Function>();
    auto bb = lirfunc->allocateBasicBlock();

    auto pa = bb->allocateInstr(
        Instruction::kMove,
        nullptr,
        OutVReg(),
        Imm(reinterpret_cast<uint64_t>(&a)));
    auto fa = bb->allocateInstr(
        Instruction::kMove, nullptr, OutVReg(OperandBase::kDouble), Ind(pa));

    auto pb = bb->allocateInstr(
        Instruction::kMove,
        nullptr,
        OutVReg(),
        Imm(reinterpret_cast<uint64_t>(&b)));
    auto fb = bb->allocateInstr(
        Instruction::kMove, nullptr, OutVReg(OperandBase::kDouble), Ind(pb));

    auto compare =
        bb->allocateInstr(opcode, nullptr, OutVReg(), VReg(fa), VReg(fb));
    bb->allocateInstr(Instruction::kReturn, nullptr, VReg(compare));

    // need this because the register allocator assumes the basic blocks
    // end with Return should have one and only one successor.
    auto epilogue = lirfunc->allocateBasicBlock();
    bb->addSuccessor(epilogue);

    auto func = (bool (*)())SimpleCompile(lirfunc.get());

    return func();
  };

  ASSERT_DOUBLE_EQ(test(Instruction::kEqual), a == b);
  ASSERT_DOUBLE_EQ(test(Instruction::kNotEqual), a != b);
  ASSERT_DOUBLE_EQ(test(Instruction::kGreaterThanUnsigned), a > b);
  ASSERT_DOUBLE_EQ(test(Instruction::kLessThanUnsigned), a < b);
  ASSERT_DOUBLE_EQ(test(Instruction::kGreaterThanEqualUnsigned), a >= b);
  ASSERT_DOUBLE_EQ(test(Instruction::kLessThanEqualUnsigned), a <= b);
}

namespace {
double rt_func(
    int a,
    int b,
    int c,
    int d,
    int e,
    double fa,
    double fb,
    double fc,
    double fd,
    double fe,
    double ff,
    double fg,
    double fh,
    double fi,
    int f,
    int g,
    int h,
    double fj) {
  return fj + a + b + c + d + e + fa * fb * fc * fd * fe * ff * fg * fh * fi +
      f + g + h;
}

template <typename... Arg>
struct AllocateOperand;

template <typename Arg, typename... Args>
struct AllocateOperand<Arg, Args...> {
  Instruction* instr;
  explicit AllocateOperand(Instruction* i) : instr(i) {}

  void operator()(Arg arg, Args... args) {
    if constexpr (std::is_same_v<int, Arg>) {
      instr->allocateImmediateInput(arg);
    } else {
      instr->allocateFPImmediateInput(arg);
    }

    (AllocateOperand<Args...>(instr))(args...);
  }
};

template <>
struct AllocateOperand<> {
  Instruction* instr;
  explicit AllocateOperand(Instruction* i) : instr(i) {}

  void operator()() {}
};

template <typename... Ts>
auto getAllocateOperand(Instruction* instr, std::tuple<Ts...>) {
  return AllocateOperand<Ts...>(instr);
}
} // namespace

TEST_F(BackendTest, ManyArguments) {
  auto args = std::make_tuple(
      1,
      2,
      3,
      4,
      5,
      1.1,
      2.2,
      3.3,
      4.4,
      5.5,
      6.6,
      7.7,
      8.8,
      9.9,
      6,
      7,
      8,
      10.1);

  auto lirfunc = std::make_unique<Function>();
  auto bb = lirfunc->allocateBasicBlock();

  Instruction* call = bb->allocateInstr(
      Instruction::kCall,
      nullptr,
      OutVReg(),
      Imm(reinterpret_cast<uint64_t>(rt_func)));

  std::apply(getAllocateOperand(call, args), args);

  bb->allocateInstr(Instruction::kReturn, nullptr, VReg(call));

  // need this because the register allocator assumes the basic blocks
  // end with Return should have one and only one successor.
  auto epilogue = lirfunc->allocateBasicBlock();
  bb->addSuccessor(epilogue);

  constexpr int kArgBufferSize = 32; // 4 arguments need to pass by stack
  auto func = (double (*)())SimpleCompile(lirfunc.get(), kArgBufferSize);

  double expected = std::apply(rt_func, args);
  double result = func();

  ASSERT_DOUBLE_EQ(result, expected);
}

namespace {
static double add(double a, double b) {
  return a + b;
}
} // namespace

TEST_F(BackendTest, FPMultipleCalls) {
  auto lirfunc = std::make_unique<Function>();
  auto bb = lirfunc->allocateBasicBlock();

  double a = 1.1;
  double b = 2.2;
  double c = 3.3;
  double d = 4.4;

  auto loadFP = [&](double* n) {
    auto m1 = bb->allocateInstr(
        Instruction::kMove,
        nullptr,
        OutVReg(),
        Imm(reinterpret_cast<uint64_t>(n)));
    auto m2 = bb->allocateInstr(
        Instruction::kMove, nullptr, OutVReg(OperandBase::kDouble), Ind(m1));
    return m2;
  };

  auto la = loadFP(&a);
  auto lb = loadFP(&b);
  auto sum1 = bb->allocateInstr(
      Instruction::kCall,
      nullptr,
      OutVReg(OperandBase::kDouble),
      Imm(reinterpret_cast<uint64_t>(add)),
      VReg(la),
      VReg(lb));

  auto lc = loadFP(&c);
  auto ld = loadFP(&d);
  auto sum2 = bb->allocateInstr(
      Instruction::kCall,
      nullptr,
      OutVReg(OperandBase::kDouble),
      Imm(reinterpret_cast<uint64_t>(add)),
      VReg(lc),
      VReg(ld));

  auto sum = bb->allocateInstr(
      Instruction::kCall,
      nullptr,
      OutVReg(OperandBase::kDouble),
      Imm(reinterpret_cast<uint64_t>(add)),
      VReg(sum1),
      VReg(sum2));

  bb->allocateInstr(Instruction::kReturn, nullptr, VReg(sum));

  auto epilogue = lirfunc->allocateBasicBlock();
  bb->addSuccessor(epilogue);

  auto func = (double (*)())SimpleCompile(lirfunc.get());
  double result = func();

  ASSERT_DOUBLE_EQ(result, a + b + c + d);
}

TEST_F(BackendTest, MoveSequenceOptTest) {
  auto lirfunc = std::make_unique<Function>();
  auto bb = lirfunc->allocateBasicBlock();

  bb->allocateInstr(
      Instruction::kMove,
      nullptr,
      OutStk(-16),
      PhyReg(arch::reg_scratch_0_loc));
  bb->allocateInstr(
      Instruction::kMove, nullptr, OutStk(-24), PhyReg(ARGUMENT_REGS[1].loc));
  bb->allocateInstr(
      lir::Instruction::kMove,
      nullptr,
      OutStk(-32),
      PhyReg(ARGUMENT_REGS[3].loc));

  auto call = bb->allocateInstr(
      Instruction::kCall,
      nullptr,
      Imm(0),
      lir::Stk(-16),
      lir::Stk(-24),
      lir::Stk(-32));
  call->getInput(3)->setLastUse();

  Environ env;
  PostRegAllocRewrite post_rewrite(lirfunc.get(), &env);
  post_rewrite.run();

  /*
  BB %0
  [RBP - 16]:Object = Move RAX:Object
  [RBP - 24]:Object = Move RSI:Object
        RDI:Object = Move RAX:Object
        RDX:Object = Move RCX:Object
                     Call Object
  */
  ASSERT_EQ(bb->getNumInstrs(), 5);
  auto& instrs = bb->instructions();

  auto iter = instrs.begin();

  ASSERT_EQ((*(iter++))->opcode(), Instruction::kMove);
  ASSERT_EQ((*(iter++))->opcode(), Instruction::kMove);
  ASSERT_EQ((*(iter++))->opcode(), Instruction::kMove);
  ASSERT_EQ((*(iter++))->opcode(), Instruction::kMove);
  ASSERT_EQ((*(iter++))->opcode(), Instruction::kCall);
}

TEST_F(BackendTest, MoveSequenceOpt2Test) {
  // OptimizeMoveSequence should not set reg operands that are also output
  auto lirfunc = std::make_unique<Function>();
  auto bb = lirfunc->allocateBasicBlock();

  bb->allocateInstr(
      Instruction::kMove,
      nullptr,
      OutStk(-16),
      PhyReg(arch::reg_general_return_loc));

  bb->allocateInstr(
      Instruction::kAdd,
      nullptr,
      OutPhyReg(arch::reg_general_return_loc),
      PhyReg(ARGUMENT_REGS[1].loc),
      lir::Stk(-16));

  Environ env;
  PostRegAllocRewrite post_rewrite(lirfunc.get(), &env);
  post_rewrite.run();

  /*
  BB %0
  [RBP - 16]:Object = Move RAX:Object
        RAX:Object = Add RSI:Object, [RBP - 16]:Object
  */
  ASSERT_EQ(bb->getNumInstrs(), 2);
  auto& instrs = bb->instructions();

  auto iter = instrs.begin();

  ASSERT_EQ((*(iter++))->opcode(), Instruction::kMove);
  ASSERT_EQ((*iter)->opcode(), Instruction::kAdd);
  ASSERT_EQ((*iter)->getInput(1)->type(), OperandBase::kStack);
}

TEST_F(BackendTest, CastTest) {
  // constants used to print out error
  static const char* errmsg = "expected '%s', got '%s'";

  auto lirfunc = std::make_unique<Function>();
  auto bb1 = lirfunc->allocateBasicBlock();
  auto bb2 = lirfunc->allocateBasicBlock();
  auto bb3 = lirfunc->allocateBasicBlock();
  auto bb4 = lirfunc->allocateBasicBlock();
  auto epilogue = lirfunc->allocateBasicBlock();

  // BB 1 : Py_TYPE(ob) == (tp)
  auto a =
      bb1->allocateInstr(Instruction::kLoadArg, nullptr, OutVReg(), Imm(0));
  auto b =
      bb1->allocateInstr(Instruction::kLoadArg, nullptr, OutVReg(), Imm(1));

  auto a_tp = bb1->allocateInstr(
      Instruction::kMove,
      nullptr,
      OutVReg(),
      Ind(a, offsetof(PyObject, ob_type)));
  auto eq1 = bb1->allocateInstr(
      Instruction::kEqual, nullptr, OutVReg(), VReg(a_tp), VReg(b));
  bb1->allocateInstr(Instruction::kCondBranch, nullptr, VReg(eq1));
  bb1->addSuccessor(bb3); // true
  bb1->addSuccessor(bb2); // false

  // BB2 : PyType_IsSubtype(Py_TYPE(ob), (tp))
  auto subtype = bb2->allocateInstr(
      Instruction::kCall,
      nullptr,
      OutVReg(),
      Imm(reinterpret_cast<uint64_t>(PyType_IsSubtype)),
      VReg(a_tp),
      VReg(b));
  bb2->allocateInstr(Instruction::kCondBranch, nullptr, VReg(subtype));
  bb2->addSuccessor(bb3); // true
  bb2->addSuccessor(bb4); // false

  // BB3 : return object
  bb3->allocateInstr(Instruction::kReturn, nullptr, VReg(a));
  bb3->addSuccessor(epilogue);

  // BB4 : return null
  auto a_name = bb4->allocateInstr(
      Instruction::kMove,
      nullptr,
      OutVReg(),
      Ind(a_tp, offsetof(PyTypeObject, tp_name)));
  auto b_name = bb4->allocateInstr(
      Instruction::kMove,
      nullptr,
      OutVReg(),
      Ind(b, offsetof(PyTypeObject, tp_name)));
  bb4->allocateInstr(
      Instruction::kCall,
      nullptr,
      Imm(reinterpret_cast<uint64_t>(PyErr_Format)),
      Imm(reinterpret_cast<uint64_t>(PyExc_TypeError)),
      Imm(reinterpret_cast<uint64_t>(errmsg)),
      VReg(b_name),
      VReg(a_name));
  auto nll = bb4->allocateInstr(Instruction::kMove, nullptr, OutVReg(), Imm(0));
  bb4->allocateInstr(Instruction::kReturn, nullptr, VReg(nll));
  bb4->addSuccessor(epilogue);

  CheckCast(lirfunc.get());
}

TEST_F(BackendTest, ParserStringInputTest) {
  auto lir_str = fmt::format(R"(Function:
BB %0 - succs: %4
        %1:Object = Move "hello"
        Return %1:Object

BB %4 - preds: %0

)");
  Parser parser;
  auto parsed_func = parser.parse(lir_str);
  auto func = (char* (*)())SimpleCompile(parsed_func.get());
  std::string ret = func();
  ASSERT_EQ(ret, "hello");
}

TEST_F(BackendTest, ParserMultipleStringInputTest) {
  auto lir_str = fmt::format(R"(Function:
BB %0 - succs: %8
        %1:Object = Move "hello1"
        %2:Object = Move "hello2"
        %3:Object = Move "hello3"
        %4:Object = Move "hello4"
        %5:Object = Move "hello5"
        %6:Object = Move "hello6"
                    Return %1:Object

BB %8 - preds: %0

)");
  Parser parser;
  auto parsed_func = parser.parse(lir_str);
  auto func = (char* (*)())SimpleCompile(parsed_func.get());
  std::string ret = func();
  ASSERT_EQ(ret, "hello1");
}

TEST_F(BackendTest, SplitBasicBlockTest) {
  auto lirfunc = std::make_unique<Function>();
  auto bb1 = lirfunc->allocateBasicBlock();
  auto bb2 = lirfunc->allocateBasicBlock();
  auto bb3 = lirfunc->allocateBasicBlock();
  auto bb4 = lirfunc->allocateBasicBlock();
  auto epilogue = lirfunc->allocateBasicBlock();

  auto r1 =
      bb1->allocateInstr(Instruction::kLoadArg, nullptr, OutVReg(), Imm(0));
  bb1->allocateInstr(Instruction::kCondBranch, nullptr, VReg(r1));
  bb1->addSuccessor(bb2);
  bb1->addSuccessor(bb3);

  auto r2 = bb2->allocateInstr(
      Instruction::kAdd, nullptr, OutVReg(), VReg(r1), Imm(8));
  bb2->addSuccessor(bb4);

  auto r3 = bb3->allocateInstr(
      Instruction::kAdd, nullptr, OutVReg(), VReg(r1), Imm(8));
  auto r4 = bb3->allocateInstr(
      Instruction::kAdd, nullptr, OutVReg(), VReg(r3), Imm(8));
  bb3->addSuccessor(bb4);

  auto r5 = bb4->allocateInstr(
      Instruction::kPhi,
      nullptr,
      OutVReg(),
      Lbl(bb2),
      VReg(r2),
      Lbl(bb3),
      VReg(r4));
  bb4->allocateInstr(Instruction::kReturn, nullptr, VReg(r5));
  bb4->addSuccessor(epilogue);

  // split blocks and then test that function output is still correct
  auto bb_new = bb1->splitBefore(r1);
  bb_new->splitBefore(r1); // test that bb_new is valid
  bb2->splitBefore(r2); // test fixupPhis
  auto bb_nullptr = bb2->splitBefore(r3); // test instruction not in block
  ASSERT_EQ(bb_nullptr, nullptr);
  bb3->splitBefore(r4); // test split in middle of block

  auto func = (uint64_t (*)(int64_t))SimpleCompile(lirfunc.get());

  ASSERT_EQ(func(0), 16);
  ASSERT_EQ(func(1), 9);
}

TEST_F(BackendTest, InlineJITRTCastTest) {
  Function caller;
  auto bb = caller.allocateBasicBlock();
  auto r1 =
      bb->allocateInstr(Instruction::kLoadArg, nullptr, OutVReg(), Imm(0));
  auto r2 =
      bb->allocateInstr(Instruction::kLoadArg, nullptr, OutVReg(), Imm(1));
  auto call_instr = bb->allocateInstr(
      Instruction::kCall,
      nullptr,
      OutVReg(),
      Imm(reinterpret_cast<uint64_t>(JITRT_Cast)),
      VReg(r1),
      VReg(r2));
  bb->allocateInstr(Instruction::kReturn, nullptr, VReg(call_instr));
  auto epilogue = caller.allocateBasicBlock();
  bb->addSuccessor(epilogue);
  LIRInliner inliner{&caller, call_instr};
  inliner.inlineCall();

  // Check that caller LIR is as expected.
  auto expected_caller = fmt::format(
      R"(Function:
BB %0 - succs: %7
       %1:Object = LoadArg 0(0x0):64bit
       %2:Object = LoadArg 1(0x1):64bit

BB %7 - preds: %0 - succs: %9 %8
      %14:Object = Move [%1:Object + 0x8]:Object
      %15:Object = Equal %14:Object, %2:Object
                   CondBranch %15:Object

BB %8 - preds: %7 - succs: %9 %10
      %17:Object = Call {0}({0:#x}):Object, %14:Object, %2:Object
                   CondBranch %17:Object

BB %10 - preds: %8 - succs: %11
      %20:Object = Move [%14:Object + 0x18]:Object
      %21:Object = Move [%2:Object + 0x18]:Object
                   Call {1}({1:#x}):Object, {2}({2:#x}):Object, string_literal, %21:Object, %20:Object
      %23:Object = Move 0(0x0):Object

BB %9 - preds: %7 %8 - succs: %11

BB %11 - preds: %9 %10 - succs: %6
      %25:Object = Phi (BB%9, %1:Object), (BB%10, %23:Object)

BB %6 - preds: %11 - succs: %5
       %3:Object = Move %25:Object
                   Return %3:Object

BB %5 - preds: %6

)",
      reinterpret_cast<uint64_t>(PyType_IsSubtype),
      reinterpret_cast<uint64_t>(PyErr_Format),
      reinterpret_cast<uint64_t>(PyExc_TypeError));
  std::stringstream ss;
  caller.sortBasicBlocks();
  ss << caller;
  // Replace the string literal address
  std::regex reg(R"(\d+\(0x[0-9a-fA-F]+\):Object, %21:Object, %20:Object)");
  std::string caller_str =
      regex_replace(ss.str(), reg, "string_literal, %21:Object, %20:Object");
  ASSERT_EQ(expected_caller, caller_str);

  // Test execution of caller
  CheckCast(&caller);
}

TEST_F(BackendTest, PostgenJITRTCastTest) {
  auto caller = std::make_unique<Function>();
  auto bb = caller->allocateBasicBlock();
  auto r1 =
      bb->allocateInstr(Instruction::kLoadArg, nullptr, OutVReg(), Imm(0));
  auto r2 =
      bb->allocateInstr(Instruction::kLoadArg, nullptr, OutVReg(), Imm(1));
  auto call_instr = bb->allocateInstr(
      Instruction::kCall,
      nullptr,
      OutVReg(),
      Imm(reinterpret_cast<uint64_t>(JITRT_Cast)),
      VReg(r1),
      VReg(r2));
  bb->allocateInstr(Instruction::kReturn, nullptr, VReg(call_instr));
  auto epilogue = caller->allocateBasicBlock();
  bb->addSuccessor(epilogue);

  Environ environ;
  InitEnviron(environ);
  PostGenerationRewrite post_gen(caller.get(), &environ);
  post_gen.run();

  // Check that caller LIR is as expected.
  auto expected_caller = fmt::format(
      R"(Function:
BB %0 - succs: %7
       %1:Object = Bind {0}:Object
       %2:Object = Bind {1}:Object

BB %7 - preds: %0 - succs: %9 %8
      %14:Object = Move [%1:Object + 0x8]:Object
      %15:Object = Equal %14:Object, %2:Object
                   CondBranch %15:Object

BB %8 - preds: %7 - succs: %9 %10
)"
#if defined(CINDER_AARCH64)
      R"(       %26:64bit = Move {2}({2:#x}):64bit
      %17:Object = Call %26:64bit, %14:Object, %2:Object
)"
#else
      R"(      %17:Object = Call {2}({2:#x}):Object, %14:Object, %2:Object
)"
#endif
      R"(                   CondBranch %17:Object

BB %10 - preds: %8 - succs: %11
      %20:Object = Move [%14:Object + 0x18]:Object
      %21:Object = Move [%2:Object + 0x18]:Object
)"
#if defined(CINDER_AARCH64)
      R"(       %27:64bit = Move {3}({3:#x}):64bit
                   Call %27:64bit, {4}({4:#x}):Object, string_literal, %21:Object, %20:Object
)"
#else
      R"(                   Call {3}({3:#x}):Object, {4}({4:#x}):Object, string_literal, %21:Object, %20:Object
)"
#endif
      R"(      %23:Object = Move 0(0x0):Object

BB %9 - preds: %7 %8 - succs: %11

BB %11 - preds: %9 %10 - succs: %6
      %25:Object = Phi (BB%9, %1:Object), (BB%10, %23:Object)

BB %6 - preds: %11 - succs: %5
       %3:Object = Move %25:Object
                   Return %3:Object

BB %5 - preds: %6

)",
      ARGUMENT_REGS[0],
      ARGUMENT_REGS[1],
      reinterpret_cast<uint64_t>(PyType_IsSubtype),
      reinterpret_cast<uint64_t>(PyErr_Format),
      reinterpret_cast<uint64_t>(PyExc_TypeError));
  std::stringstream ss;
  caller->sortBasicBlocks();
  ss << *caller;
  // Replace the string literal address
  std::regex reg(R"(\d+\(0x[0-9a-fA-F]+\):Object, %21:Object, %20:Object)");
  std::string caller_str =
      regex_replace(ss.str(), reg, "string_literal, %21:Object, %20:Object");
  ASSERT_EQ(expected_caller, caller_str);
}

TEST_F(BackendTest, ParserErrorFromExpectTest) {
  // Test throw from expect
  Parser parser;
  parser.parse(R"(Function:
BB %0
)");
  try {
    // Bad basic block header
    parser.parse(R"(Function:
BB %0 %3
)");
    FAIL();
  } catch (ParserException&) {
  }

  try {
    // Dupicate ID
    parser.parse(R"(Function:
BB %0
%1:Object = Bind RDI:Object
%1:Object
)");
    FAIL();
  } catch (ParserException&) {
  }
}

TEST_F(BackendTest, ParserErrorFromMapGetTest) {
  // Test throw from map_get_throw
  Parser parser;
  try {
    // Invalid opcode
    parser.parse(R"(Function:
BB %0
%1:Object = InvalidInstruction
)");
    FAIL();
  } catch (ParserException&) {
  }
  try {
    // Missing basic block
    parser.parse(R"(Function:
BB %0 - succs: %2
Return 0(0x0):Object
BB %1
)");
    FAIL();
  } catch (ParserException&) {
  }
}

} // namespace jit::codegen
