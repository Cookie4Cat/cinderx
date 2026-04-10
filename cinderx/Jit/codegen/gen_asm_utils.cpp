// Copyright (c) Meta Platforms, Inc. and affiliates.

#include "cinderx/Jit/codegen/gen_asm_utils.h"

#include "cinderx/Jit/codegen/arch.h"
#include "cinderx/Jit/codegen/code_section.h"
#include "cinderx/Jit/codegen/environ.h"
#include "cinderx/Jit/inline_cache.h"

#include <cstdlib>
#include <limits>

namespace jit::codegen {

namespace {
void recordDebugEntry(Environ& env, const jit::lir::Instruction* instr) {
  if (instr == nullptr || instr->origin() == nullptr) {
    return;
  }
  asmjit::Label addr = env.as->newLabel();
  env.as->bind(addr);
  env.pending_debug_locs.emplace_back(addr, instr->origin());
}

#if defined(CINDER_AARCH64)
Environ::Aarch64CallTarget& getOrCreateCallTarget(Environ& env, uint64_t func) {
  auto it = env.call_target_literals.find(func);
  if (it != env.call_target_literals.end()) {
    return it->second;
  }
  Environ::Aarch64CallTarget target;
  target.literal = env.as->newLabel();
  auto inserted = env.call_target_literals.emplace(func, target);
  return inserted.first->second;
}

void emitIndirectCallThroughLiteral(
    Environ& env,
    const Environ::Aarch64CallTarget& target) {
  env.as->ldr(arch::reg_scratch_br, asmjit::a64::ptr(target.literal));
  env.as->blr(arch::reg_scratch_br);
}

bool isInColdSection(const Environ& env) {
  auto* cold = env.as->code()->sectionByName(codeSectionName(CodeSection::kCold));
  if (cold == nullptr) {
    return false;
  }

  for (auto* node = env.as->cursor(); node != nullptr; node = node->prev()) {
    if (node->type() == asmjit::NodeType::kSection) {
      auto* section_node = node->as<asmjit::SectionNode>();
      return section_node->id() == cold->id();
    }
  }

  return false;
}

bool useLoadModuleAttrLookupStub(uint64_t func) {
#if PY_VERSION_HEX >= 0x030E0000 && !defined(Py_GIL_DISABLED)
  return func ==
      reinterpret_cast<uint64_t>(jit::LoadModuleAttrCache::lookupHelper);
#else
  return false;
#endif
}

bool useStoreAttrInvokeStub(uint64_t func) {
#if PY_VERSION_HEX >= 0x030E0000 && !defined(Py_GIL_DISABLED)
  return std::getenv("PYTHONJITAARCH64STOREATTRSTUBMINCALLS") != nullptr &&
      func == reinterpret_cast<uint64_t>(jit::StoreAttrCache::invoke);
#else
  return false;
#endif
}

uint32_t parseSharedStubMinCalls() {
  constexpr uint32_t kDefault = 24;
  const char* env = std::getenv("PYTHONJITAARCH64SHAREDSTUBMINCALLS");
  if (env == nullptr) {
    return kDefault;
  }

  char* end = nullptr;
  unsigned long parsed = std::strtoul(env, &end, 10);
  if (end == env || *end != '\0' || parsed == 0) {
    return kDefault;
  }
  if (parsed > std::numeric_limits<uint32_t>::max()) {
    return std::numeric_limits<uint32_t>::max();
  }
  return static_cast<uint32_t>(parsed);
}

#endif
} // namespace

uint32_t sharedStubMinCalls() {
#if defined(CINDER_AARCH64)
  return parseSharedStubMinCalls();
#else
  return 0;
#endif
}

uint32_t storeAttrStubMinCalls() {
#if defined(CINDER_AARCH64)
  constexpr uint32_t kDefault = 6;
  const char* env = std::getenv("PYTHONJITAARCH64STOREATTRSTUBMINCALLS");
  if (env == nullptr) {
    return kDefault;
  }

  char* end = nullptr;
  unsigned long parsed = std::strtoul(env, &end, 10);
  if (end == env || *end != '\0' || parsed == 0) {
    return kDefault;
  }
  if (parsed > std::numeric_limits<uint32_t>::max()) {
    return std::numeric_limits<uint32_t>::max();
  }
  return static_cast<uint32_t>(parsed);
#else
  return 0;
#endif
}

bool isStoreAttrInvokeTarget(uint64_t func) {
#if defined(CINDER_AARCH64)
  return useStoreAttrInvokeStub(func);
#else
  return false;
#endif
}

void emitCall(
    Environ& env,
    asmjit::Label label,
    const jit::lir::Instruction* instr) {
#if defined(CINDER_X86_64)
  env.as->call(label);
#elif defined(CINDER_AARCH64)
  env.as->bl(label);
#else
  CINDER_UNSUPPORTED
#endif
  recordDebugEntry(env, instr);
}

void emitCall(Environ& env, uint64_t func, const jit::lir::Instruction* instr) {
#if defined(CINDER_X86_64)
  env.as->call(func);
#elif defined(CINDER_AARCH64)
  if (isInColdSection(env)) {
    // Cold blocks can be placed >1MiB from hot text under MCS. Avoid
    // ldr-literal call lowering here because its imm19 displacement cannot
    // reach hot literals in that layout.
    env.as->mov(arch::reg_scratch_br, func);
    env.as->blr(arch::reg_scratch_br);
  } else {
    if (useStoreAttrInvokeStub(func)) {
      auto& target = getOrCreateCallTarget(env, func);
      if (!target.use_shared_stub) {
        emitIndirectCallThroughLiteral(env, target);
      } else {
        if (!env.store_attr_invoke_stub.isValid()) {
          env.store_attr_invoke_stub = env.as->newLabel();
        }
        emitCall(env, env.store_attr_invoke_stub, instr);
      }
      return;
    }
    if (useLoadModuleAttrLookupStub(func)) {
      auto& target = getOrCreateCallTarget(env, func);
      if (!target.use_shared_stub) {
        emitIndirectCallThroughLiteral(env, target);
      } else {
        if (!env.load_module_attr_lookup_stub.isValid()) {
          env.load_module_attr_lookup_stub = env.as->newLabel();
        }
        emitCall(env, env.load_module_attr_lookup_stub, instr);
      }
      return;
    }

    auto& target = getOrCreateCallTarget(env, func);
    if (!target.use_shared_stub) {
      emitIndirectCallThroughLiteral(env, target);
    } else {
      if (!target.has_shared_stub) {
        target.stub = env.as->newLabel();
        target.has_shared_stub = true;
      }
      emitCall(env, target.stub, instr);
      return;
    }
  }
#else
  CINDER_UNSUPPORTED
#endif
  recordDebugEntry(env, instr);
}

} // namespace jit::codegen
