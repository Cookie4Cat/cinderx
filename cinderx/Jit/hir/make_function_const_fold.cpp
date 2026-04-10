// Copyright (c) Meta Platforms, Inc. and affiliates.

#include "cinderx/Jit/hir/make_function_const_fold.h"

#include "cinderx/Jit/deopt.h"
#include "cinderx/Jit/hir/copy_propagation.h"

namespace jit::hir {

namespace {

struct Candidate {
  MakeFunction* make_func;
  Register* output;
  Register* replacement;
  std::vector<Instr*> removable_uses;
};

bool replaceInFrameState(FrameState* fs, Register* old_reg, Register* new_reg) {
  bool changed = false;
  while (fs != nullptr) {
    for (auto& local : fs->localsplus) {
      if (local == old_reg) {
        local = new_reg;
        changed = true;
      }
    }
    for (auto& stack_value : fs->stack) {
      if (stack_value == old_reg) {
        stack_value = new_reg;
        changed = true;
      }
    }
    fs = fs->parent;
  }
  return changed;
}

bool replaceInAllFrameStates(Function& func, Register* old_reg, Register* new_reg) {
  bool changed = false;
  for (auto& block : func.cfg.blocks) {
    for (auto& instr : block) {
      FrameState* fs = get_frame_state(instr);
      if (fs != nullptr) {
        changed |= replaceInFrameState(fs, old_reg, new_reg);
      }
      auto* deopt = instr.asDeoptBase();
      if (deopt == nullptr) {
        continue;
      }
      for (auto& reg_state : deopt->live_regs()) {
        if (reg_state.reg != old_reg) {
          continue;
        }
        reg_state.reg = new_reg;
        reg_state.value_kind = jit::deoptValueKind(new_reg->type());
        changed = true;
      }
      deopt->sortLiveRegs();
      if (deopt->guiltyReg() == old_reg) {
        deopt->setGuiltyReg(new_reg);
        changed = true;
      }
    }
  }
  return changed;
}

bool collectRemovableUses(
    const RegUses& direct_uses,
    Register* reg,
    std::vector<Instr*>& removable_uses) {
  auto use_it = direct_uses.find(reg);
  if (use_it == direct_uses.end()) {
    return true;
  }

  for (Instr* use : use_it->second) {
    if (!use->IsUseType() && !use->IsDecref() && !use->IsXDecref()) {
      return false;
    }
    removable_uses.push_back(use);
  }
  return true;
}

BorrowedRef<PyCodeObject> getMakeFunctionCode(const MakeFunction& make_func) {
  Register* code_reg = make_func.GetOperand(0);
  if (code_reg == nullptr || !code_reg->instr()->IsLoadConst()) {
    return nullptr;
  }
  PyObject* obj = static_cast<LoadConst*>(code_reg->instr())->type().asObject();
  return PyCode_Check(obj) ? reinterpret_cast<PyCodeObject*>(obj) : nullptr;
}

bool isNullQualname(const MakeFunction& make_func) {
  Register* qualname = make_func.GetOperand(1);
  if (qualname == nullptr || !qualname->instr()->IsLoadConst()) {
    return false;
  }
  return static_cast<LoadConst*>(qualname->instr())->type() <= TNullptr;
}

bool isConstFoldableGenexpr(const MakeFunction& make_func) {
  auto code = getMakeFunctionCode(make_func);
  if (code == nullptr || numFreevars(code) != 0) {
    return false;
  }
  const char* name = PyUnicode_AsUTF8(code->co_name);
  if (name == nullptr) {
    PyErr_Clear();
    return false;
  }
  return std::strcmp(name, "<genexpr>") == 0 && isNullQualname(make_func);
}

} // namespace

void MakeFunctionConstFold::Run(Function& irfunc) {
  auto direct_uses = collectDirectRegUses(irfunc);
  std::vector<Candidate> candidates;

  for (auto& block : irfunc.cfg.blocks) {
    for (auto& instr : block) {
      if (!instr.IsMakeFunction()) {
        continue;
      }
      auto& make_func = static_cast<MakeFunction&>(instr);
      if (!isConstFoldableGenexpr(make_func)) {
        continue;
      }

      std::vector<Instr*> removable_uses;
      if (!collectRemovableUses(direct_uses, make_func.output(), removable_uses)) {
        continue;
      }

      auto code = getMakeFunctionCode(make_func);
      auto func_obj = Ref<>::steal(PyFunction_New(code, make_func.frameState()->globals));
      if (func_obj == nullptr) {
        PyErr_Clear();
        continue;
      }

      Register* replacement = irfunc.env.AllocateRegister();
      auto* load = LoadConst::create(
          replacement, Type::fromObject(irfunc.env.addReference(std::move(func_obj))));
      load->copyBytecodeOffset(make_func);
      replacement->set_type(outputType(*load));
      make_func.block()->insert(load, make_func.block()->iterator_to(make_func));

      candidates.push_back(
          Candidate{&make_func, make_func.output(), replacement, std::move(removable_uses)});
    }
  }

  bool changed = false;
  for (auto& candidate : candidates) {
    if (!replaceInAllFrameStates(
            irfunc, candidate.output, candidate.replacement)) {
      continue;
    }

    for (Instr* use : candidate.removable_uses) {
      if (use->block() != nullptr) {
        use->unlink();
        delete use;
      }
    }

    if (candidate.make_func->block() != nullptr) {
      candidate.make_func->unlink();
      delete candidate.make_func;
      changed = true;
    }
  }

  if (changed) {
    CopyPropagation{}.Run(irfunc);
    reflowTypes(irfunc);
  }
}

} // namespace jit::hir
