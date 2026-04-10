// Copyright (c) Meta Platforms, Inc. and affiliates.

#include "cinderx/Jit/hir/primitive_box_remat.h"

#include "cinderx/Jit/codegen/arch/detection.h"
#include "cinderx/Jit/hir/copy_propagation.h"
#include "cinderx/Jit/deopt.h"

namespace jit::hir {

namespace {

#if defined(CINDER_AARCH64)

struct RematCandidate {
  PrimitiveBox* box;
  Register* boxed;
  Register* unboxed;
  std::vector<Instr*> removable_uses;
};

bool replaceInFrameState(FrameState* fs, Register* boxed, Register* unboxed) {
  bool changed = false;
  while (fs != nullptr) {
    for (auto& local : fs->localsplus) {
      if (local == boxed) {
        local = unboxed;
        changed = true;
      }
    }
    for (auto& stack_value : fs->stack) {
      if (stack_value == boxed) {
        stack_value = unboxed;
        changed = true;
      }
    }
    fs = fs->parent;
  }
  return changed;
}

bool replaceInAllFrameStates(Function& func, Register* boxed, Register* unboxed) {
  bool changed = false;
  for (auto& block : func.cfg.blocks) {
    for (auto& instr : block) {
      FrameState* fs = get_frame_state(instr);
      if (fs != nullptr) {
        changed |= replaceInFrameState(fs, boxed, unboxed);
      }
      auto* deopt = instr.asDeoptBase();
      if (deopt == nullptr) {
        continue;
      }
      for (auto& reg_state : deopt->live_regs()) {
        if (reg_state.reg != boxed) {
          continue;
        }
        reg_state.reg = unboxed;
        reg_state.value_kind = jit::deoptValueKind(unboxed->type());
        if (reg_state.value_kind != ValueKind::kObject) {
          reg_state.ref_kind = RefKind::kUncounted;
        }
        changed = true;
      }
      deopt->sortLiveRegs();
      if (deopt->guiltyReg() == boxed) {
        deopt->setGuiltyReg(unboxed);
        changed = true;
      }
    }
  }
  return changed;
}

bool collectRemovableUses(
    const RegUses& direct_uses,
    Register* boxed,
    std::vector<Instr*>& removable_uses) {
  auto use_it = direct_uses.find(boxed);
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

#endif

} // namespace

void PrimitiveBoxRemat::Run(Function& irfunc) {
#if !defined(CINDER_AARCH64)
  return;
#else
  bool changed = false;
  auto direct_uses = collectDirectRegUses(irfunc);
  std::vector<RematCandidate> candidates;

  for (auto& block : irfunc.cfg.blocks) {
    for (auto& instr : block) {
      if (!instr.IsPrimitiveBox()) {
        continue;
      }
      auto& box = static_cast<PrimitiveBox&>(instr);
      if (box.type() != TCDouble) {
        continue;
      }

      Register* boxed = box.output();
      Register* unboxed = box.value();
      if (unboxed == nullptr || !(unboxed->type() <= TCDouble)) {
        continue;
      }

      std::vector<Instr*> removable_uses;
      if (!collectRemovableUses(direct_uses, boxed, removable_uses)) {
        continue;
      }

      candidates.push_back(
          RematCandidate{&box, boxed, unboxed, std::move(removable_uses)});
    }
  }

  for (auto& candidate : candidates) {
    if (!replaceInAllFrameStates(irfunc, candidate.boxed, candidate.unboxed)) {
      continue;
    }

    for (Instr* use : candidate.removable_uses) {
      use->unlink();
      delete use;
    }

    if (candidate.box->block() == nullptr) {
      continue;
    }

    candidate.box->unlink();
    delete candidate.box;
    changed = true;
  }

  if (changed) {
    CopyPropagation{}.Run(irfunc);
    reflowTypes(irfunc);
  }
#endif
}

} // namespace jit::hir
