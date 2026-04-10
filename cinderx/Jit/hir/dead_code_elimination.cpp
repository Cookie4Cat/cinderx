// Copyright (c) Meta Platforms, Inc. and affiliates.

#include "cinderx/Jit/hir/dead_code_elimination.h"

#include "cinderx/Jit/hir/instr_effects.h"

#include <cstring>

namespace jit::hir {

namespace {

int countUses(const Function& func, const Register* reg) {
  int uses = 0;
  for (auto& block : func.cfg.blocks) {
    for (const auto& instr : block) {
      instr.visitUses([&](Register* use) {
        if (use == reg) {
          uses++;
        }
        return true;
      });
    }
  }
  return uses;
}

bool isBuiltinMathSqrtLoad(const LoadModuleAttrCached& instr) {
  Register* receiver = instr.GetOperand(0);
  Type receiver_type = receiver->type();
  if (!receiver_type.hasObjectSpec()) {
    return false;
  }

  BorrowedRef<> module_obj = receiver_type.objectSpec();
  if (!PyModule_Check(module_obj)) {
    return false;
  }

  PyModuleDef* def = PyModule_GetDef(module_obj);
  if (def == nullptr) {
    PyErr_Clear();
    return false;
  }
  if (std::strcmp(def->m_name, "math") != 0) {
    return false;
  }
  if (PyUnicode_CompareWithASCIIString(instr.name(), "sqrt") != 0) {
    PyErr_Clear();
    return false;
  }

  auto* dict = PyModule_GetDict(module_obj);
  BorrowedRef<> value = PyDict_GetItemWithError(dict, instr.name());
  if (value == nullptr) {
    PyErr_Clear();
    return false;
  }
  return PyCFunction_Check(value);
}

bool isDiscardableMathSqrtLoad(const Function& func, Instr& instr) {
  if (!instr.IsLoadModuleAttrCached()) {
    return false;
  }

  auto& load = static_cast<LoadModuleAttrCached&>(instr);
  if (!isBuiltinMathSqrtLoad(load)) {
    return false;
  }

  Register* output = load.output();
  if (output == nullptr || countUses(func, output) != 1) {
    return false;
  }

  for (auto& block : func.cfg.blocks) {
    for (auto& user : block) {
      if (!user.IsDecref()) {
        continue;
      }
      if (user.GetOperand(0) == output) {
        return true;
      }
    }
  }
  return false;
}

bool isUseful(Function& func, Instr& instr) {
  if (instr.IsDecref()) {
    auto* value = instr.GetOperand(0);
    if (value != nullptr && value->instr() != nullptr &&
        isDiscardableMathSqrtLoad(func, *value->instr())) {
      return false;
    }
  }

  if (isDiscardableMathSqrtLoad(func, instr)) {
    return false;
  }

  return instr.IsTerminator() || instr.IsSnapshot() ||
      (instr.asDeoptBase() != nullptr && !instr.IsPrimitiveBox()) ||
      (!instr.IsPhi() && memoryEffects(instr).may_store != AEmpty);
}

} // namespace

void DeadCodeElimination::Run(Function& func) {
  Worklist<Instr*> worklist;
  for (auto& block : func.cfg.blocks) {
    for (Instr& instr : block) {
      if (isUseful(func, instr)) {
        worklist.push(&instr);
      }
    }
  }
  std::unordered_set<Instr*> live_set;
  while (!worklist.empty()) {
    auto live_op = worklist.front();
    worklist.pop();
    if (live_set.insert(live_op).second) {
      live_op->visitUses([&](Register*& reg) {
        if (!live_set.contains(reg->instr())) {
          worklist.push(reg->instr());
        }
        return true;
      });
    }
  }
  for (auto& block : func.cfg.blocks) {
    for (auto it = block.begin(); it != block.end();) {
      auto& instr = *it;
      ++it;
      if (!live_set.contains(&instr)) {
        instr.unlink();
        delete &instr;
      }
    }
  }
}

} // namespace jit::hir
