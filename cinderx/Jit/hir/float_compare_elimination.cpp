// Copyright (c) Meta Platforms, Inc. and affiliates.

#include "cinderx/Jit/hir/float_compare_elimination.h"

#include "cinderx/Common/log.h"

namespace jit::hir {

namespace {

struct Candidate {
  FloatCompare* float_compare;
  PrimitiveCompare* object_compare;
  Instr* true_const;
  std::vector<Instr*> removable_float_compare_uses;
};

std::optional<PrimitiveCompareOp> toDoublePrimitiveCompareOp(CompareOp op) {
  switch (op) {
    case CompareOp::kEqual:
      return PrimitiveCompareOp::kEqual;
    case CompareOp::kNotEqual:
      return PrimitiveCompareOp::kNotEqual;
    case CompareOp::kGreaterThan:
      return PrimitiveCompareOp::kGreaterThanUnsigned;
    case CompareOp::kGreaterThanEqual:
      return PrimitiveCompareOp::kGreaterThanEqualUnsigned;
    case CompareOp::kLessThan:
      return PrimitiveCompareOp::kLessThanUnsigned;
    case CompareOp::kLessThanEqual:
      return PrimitiveCompareOp::kLessThanEqualUnsigned;
    default:
      return std::nullopt;
  }
}

bool isTrueConst(Register* reg) {
  return reg != nullptr && reg->type().asObject() == Py_True;
}

bool collectCandidate(
    const RegUses& direct_uses,
    PrimitiveCompare& compare,
    Candidate& candidate) {
  if (compare.op() != PrimitiveCompareOp::kEqual) {
    return false;
  }

  Register* float_result = nullptr;
  Register* true_const = nullptr;

  if (compare.left()->instr()->IsFloatCompare() && isTrueConst(compare.right())) {
    float_result = compare.left();
    true_const = compare.right();
  } else if (
      compare.right()->instr()->IsFloatCompare() && isTrueConst(compare.left())) {
    float_result = compare.right();
    true_const = compare.left();
  } else {
    return false;
  }

  auto* float_compare = static_cast<FloatCompare*>(float_result->instr());
  if (float_compare->block() != compare.block()) {
    return false;
  }
  if (!toDoublePrimitiveCompareOp(float_compare->op()).has_value()) {
    return false;
  }

  auto use_it = direct_uses.find(float_result);
  if (use_it == direct_uses.end()) {
    return false;
  }

  std::vector<Instr*> removable_uses;
  for (Instr* use : use_it->second) {
    if (use == &compare) {
      continue;
    }
    if (!use->IsUseType() && !use->IsDecref() && !use->IsXDecref()) {
      return false;
    }
    removable_uses.push_back(use);
  }

  candidate = Candidate{
      float_compare, &compare, true_const->instr(), std::move(removable_uses)};
  return true;
}

} // namespace

void FloatCompareElimination::Run(Function& irfunc) {
  auto direct_uses = collectDirectRegUses(irfunc);
  std::vector<Candidate> candidates;

  for (auto& block : irfunc.cfg.blocks) {
    for (auto& instr : block) {
      if (!instr.IsPrimitiveCompare()) {
        continue;
      }

      Candidate candidate{};
      if (collectCandidate(
              direct_uses, static_cast<PrimitiveCompare&>(instr), candidate)) {
        candidates.push_back(std::move(candidate));
      }
    }
  }

  bool changed = false;

  for (auto& candidate : candidates) {
    if (candidate.float_compare->block() == nullptr ||
        candidate.object_compare->block() == nullptr) {
      continue;
    }

    auto prim_op = toDoublePrimitiveCompareOp(candidate.float_compare->op());
    JIT_CHECK(prim_op.has_value(), "unexpected float compare op");

    BasicBlock* block = candidate.float_compare->block();
    auto insert_it = block->iterator_to(*candidate.float_compare);

    Register* unbox_left = irfunc.env.AllocateRegister();
    auto* unbox_left_instr = PrimitiveUnbox::create(
        unbox_left, candidate.float_compare->left(), TCDouble);
    unbox_left_instr->copyBytecodeOffset(*candidate.float_compare);
    block->insert(unbox_left_instr, insert_it);

    Register* unbox_right = irfunc.env.AllocateRegister();
    auto* unbox_right_instr = PrimitiveUnbox::create(
        unbox_right, candidate.float_compare->right(), TCDouble);
    unbox_right_instr->copyBytecodeOffset(*candidate.float_compare);
    block->insert(unbox_right_instr, insert_it);

    auto* new_compare = PrimitiveCompare::create(
        candidate.object_compare->output(),
        *prim_op,
        unbox_left,
        unbox_right);
    new_compare->copyBytecodeOffset(*candidate.float_compare);
    block->insert(new_compare, insert_it);

    for (Instr* use : candidate.removable_float_compare_uses) {
      use->unlink();
      delete use;
    }

    auto true_const_use_it =
        direct_uses.find(candidate.true_const != nullptr
                             ? candidate.true_const->output()
                             : nullptr);
    if (candidate.true_const != nullptr && candidate.true_const->IsLoadConst() &&
        true_const_use_it != direct_uses.end() &&
        true_const_use_it->second.size() == 1 &&
        true_const_use_it->second.contains(candidate.object_compare)) {
      candidate.true_const->unlink();
      delete candidate.true_const;
    }

    candidate.object_compare->unlink();
    delete candidate.object_compare;

    candidate.float_compare->unlink();
    delete candidate.float_compare;

    changed = true;
  }

  if (changed) {
    reflowTypes(irfunc);
  }
}

} // namespace jit::hir
