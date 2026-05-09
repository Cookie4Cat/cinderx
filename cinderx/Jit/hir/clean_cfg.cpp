// Copyright (c) Meta Platforms, Inc. and affiliates.

#include "cinderx/Jit/hir/clean_cfg.h"

#include "cinderx/Jit/hir/phi_elimination.h"
#include "cinderx/Jit/hir/printer.h"

namespace jit::hir {

namespace {

bool absorbDstBlock(BasicBlock* block) {
  if (block->GetTerminator()->opcode() != Opcode::kBranch) {
    return false;
  }
  auto branch = dynamic_cast<Branch*>(block->GetTerminator());
  BasicBlock* target = branch->target();
  if (target == block) {
    return false;
  }
  if (target->in_edges().size() != 1) {
    return false;
  }
  if (target == block) {
    return false;
  }
  branch->unlink();
  while (!target->empty()) {
    Instr* instr = target->pop_front();
    JIT_CHECK(!instr->IsPhi(), "Expected no Phi but found {}", *instr);
    block->Append(instr);
  }
  // The successors to target might have Phis that still refer to target.
  // Retarget them to refer to block.
  Instr* old_term = block->GetTerminator();
  JIT_CHECK(old_term != nullptr, "block must have a terminator");
  for (std::size_t i = 0, n = old_term->numEdges(); i < n; ++i) {
    old_term->successor(i)->fixupPhis(
        /*old_pred=*/target, /*new_pred=*/block);
  }
  // Target block becomes unreachable and gets picked up by
  // removeUnreachableBlocks.
  delete branch;
  return true;
}

bool isToBoolFastValue(Register* reg) {
  Instr* instr = reg->instr();
  return instr->IsPrimitiveCompare() || instr->IsCIntToCBool() ||
      (instr->IsLoadConst() && reg->isA(TCBool));
}

BasicBlock* loadConstBoolTarget(
    Register* reg,
    BasicBlock* true_bb,
    BasicBlock* false_bb) {
  Instr* instr = reg->instr();
  if (!instr->IsLoadConst()) {
    return nullptr;
  }

  auto load_const = static_cast<LoadConst*>(instr);
  Type type = load_const->type();
  if (!(type <= TCBool) || !type.hasIntSpec()) {
    return nullptr;
  }
  return type.intSpec() ? true_bb : false_bb;
}

bool foldConstantCondBranch(BasicBlock* block) {
  Instr* term = block->GetTerminator();
  if (term == nullptr || !term->IsCondBranch()) {
    return false;
  }

  auto cond_branch = static_cast<CondBranch*>(term);
  Instr* cond_instr = cond_branch->GetOperand(0)->instr();
  if (!cond_instr->IsLoadConst()) {
    return false;
  }

  auto load_const = static_cast<LoadConst*>(cond_instr);
  Type type = load_const->type();
  if (!(type <= TCBool) || !type.hasIntSpec()) {
    return false;
  }

  BasicBlock* target =
      type.intSpec() ? cond_branch->true_bb() : cond_branch->false_bb();
  BasicBlock* skipped =
      type.intSpec() ? cond_branch->false_bb() : cond_branch->true_bb();
  if (skipped != target) {
    skipped->removePhiPredecessor(block);
  }

  auto branch = Branch::create(target);
  branch->copyBytecodeOffset(*term);
  term->ReplaceWith(*branch);
  delete term;
  return true;
}

// The TO_BOOL + POP_JUMP fusion lowers to a type-specialized fast path and a
// generic IsTruthy slow path, then joins their CBool results before branching.
// Duplicate the final branch into the predecessors after SSA is settled; doing
// this in the builder directly makes deopt state at the bytecode targets fragile.
bool duplicateBoolPhiCondBranch(BasicBlock* block) {
  if (block->in_edges().size() < 2) {
    return false;
  }

  auto it = block->begin();
  if (it == block->end() || !it->IsPhi()) {
    return false;
  }
  auto phi = static_cast<Phi*>(&*it);
  if (!phi->output()->isA(TCBool)) {
    return false;
  }
  ++it;
  if (it == block->end() || !it->IsCondBranch()) {
    return false;
  }
  auto cond_branch = static_cast<CondBranch*>(&*it);
  if (cond_branch->GetOperand(0) != phi->output()) {
    return false;
  }
  ++it;
  if (it != block->end()) {
    return false;
  }

  std::vector<BasicBlock*> preds;
  preds.reserve(block->in_edges().size());
  bool has_slow_truthiness = false;
  bool has_fast_truthiness = false;
  for (auto edge : block->in_edges()) {
    BasicBlock* pred = edge->from();
    if (pred->GetTerminator() == nullptr || !pred->GetTerminator()->IsBranch()) {
      return false;
    }
    Register* pred_value = phi->GetOperand(phi->blockIndex(pred));
    if (pred_value->instr()->IsIsTruthy()) {
      has_slow_truthiness = true;
    } else if (isToBoolFastValue(pred_value)) {
      has_fast_truthiness = true;
    } else {
      return false;
    }
    preds.emplace_back(pred);
  }
  if (!has_slow_truthiness || !has_fast_truthiness) {
    return false;
  }

  BasicBlock* true_bb = cond_branch->true_bb();
  BasicBlock* false_bb = cond_branch->false_bb();
  for (BasicBlock* pred : preds) {
    Register* pred_value = phi->GetOperand(phi->blockIndex(pred));
    Instr* old_term = pred->GetTerminator();
    Instr* new_branch;
    if (BasicBlock* target = loadConstBoolTarget(pred_value, true_bb, false_bb)) {
      new_branch = Branch::create(target);
      target->addPhiPredecessor(block, pred);
    } else {
      new_branch = CondBranch::create(pred_value, true_bb, false_bb);
      true_bb->addPhiPredecessor(block, pred);
      false_bb->addPhiPredecessor(block, pred);
    }
    new_branch->copyBytecodeOffset(*old_term);
    old_term->ReplaceWith(*new_branch);
    delete old_term;
  }
  return true;
}

} // namespace

void CleanCFG::Run(Function& irfunc) {
  bool changed = false;

  do {
    removeUnreachableInstructions(irfunc);
    // Remove any trivial Phis; absorbDstBlock cannot handle them.
    PhiElimination{}.Run(irfunc);
    std::vector<BasicBlock*> blocks = irfunc.cfg.GetRPOTraversal();
    for (auto block : blocks) {
      // Ignore transient empty blocks.
      if (block->empty()) {
        continue;
      }
      // Keep working on the current block until no further changes are made.
      for (;; changed = true) {
        if (foldConstantCondBranch(block)) {
          continue;
        }
        if (duplicateBoolPhiCondBranch(block)) {
          changed = true;
          break;
        }
        if (absorbDstBlock(block)) {
          continue;
        }
        break;
      }
    }
  } while (removeUnreachableBlocks(irfunc));

  if (changed) {
    reflowTypes(irfunc);
  }
}

} // namespace jit::hir
