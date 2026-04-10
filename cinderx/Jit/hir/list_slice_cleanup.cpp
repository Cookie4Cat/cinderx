// Copyright (c) Meta Platforms, Inc. and affiliates.

#include "cinderx/Jit/hir/list_slice_cleanup.h"

namespace jit::hir {

namespace {

bool hasMatchingListSlice(const BuildSlice& build_slice) {
  BasicBlock* block = build_slice.block();
  if (block == nullptr || build_slice.NumOperands() != 2) {
    return false;
  }

  for (auto it = block->iterator_to(const_cast<BuildSlice&>(build_slice));
       it != block->end();
       ++it) {
    Instr& instr = *it;
    if (!instr.IsListSlice()) {
      continue;
    }
    if (instr.bytecodeOffset() != build_slice.bytecodeOffset()) {
      continue;
    }
    if (instr.GetOperand(1) == build_slice.start() &&
        instr.GetOperand(2) == build_slice.stop()) {
      return true;
    }
  }

  return false;
}

} // namespace

void ListSliceCleanup::Run(Function& irfunc) {
  auto direct_uses = collectDirectRegUses(irfunc);
  std::vector<BuildSlice*> dead_slices;
  std::vector<Instr*> removable_uses;

  for (auto& block : irfunc.cfg.blocks) {
    for (auto& instr : block) {
      if (!instr.IsBuildSlice()) {
        continue;
      }

      auto& build_slice = static_cast<BuildSlice&>(instr);
      auto use_it = direct_uses.find(build_slice.output());
      if (use_it == direct_uses.end()) {
        continue;
      }
      if (!hasMatchingListSlice(build_slice)) {
        continue;
      }

      bool removable = true;
      for (Instr* use : use_it->second) {
        if (!use->IsDecref() && !use->IsXDecref()) {
          removable = false;
          break;
        }
      }
      if (!removable) {
        continue;
      }

      dead_slices.push_back(&build_slice);
      removable_uses.insert(
          removable_uses.end(), use_it->second.begin(), use_it->second.end());
    }
  }

  for (Instr* use : removable_uses) {
    use->unlink();
    delete use;
  }
  for (BuildSlice* build_slice : dead_slices) {
    if (build_slice->block() == nullptr) {
      continue;
    }
    build_slice->unlink();
    delete build_slice;
  }
}

} // namespace jit::hir
