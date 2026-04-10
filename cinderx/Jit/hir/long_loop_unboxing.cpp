// Copyright (c) Meta Platforms, Inc. and affiliates.

#include "cinderx/Jit/hir/long_loop_unboxing.h"

#include "cinderx/Jit/config.h"
#include "cinderx/Jit/hir/hir.h"

#include <algorithm>
#include <optional>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace jit::hir {

namespace {

struct PhiCandidate {
  Phi* phi;
  BasicBlock* preheader;
  BasicBlock* backedge;
  Register* init_boxed;
  LongInPlaceOp* update;
  Register* raw{nullptr};
  Register* raw_init{nullptr};
  Register* raw_update{nullptr};
};

struct LoopCandidate {
  BasicBlock* header;
  BasicBlock* preheader;
  BasicBlock* backedge;
  CompareBool* compare;
  std::vector<PhiCandidate> phis;
};

std::optional<int64_t> getBoxedLongConst(Register* reg) {
  reg = chaseAssignOperand(reg);
  Type ty = reg->type();
  if (ty.hasIntSpec()) {
    return ty.intSpec();
  }
  if (!ty.hasObjectSpec() || !PyLong_CheckExact(ty.objectSpec())) {
    return std::nullopt;
  }

  int overflow = 0;
  long long value = PyLong_AsLongLongAndOverflow(ty.objectSpec(), &overflow);
  PyErr_Clear();
  if (overflow != 0) {
    return std::nullopt;
  }
  return static_cast<int64_t>(value);
}

bool replaceInFrameState(FrameState* fs, Register* boxed, Register* raw) {
  bool changed = false;
  while (fs != nullptr) {
    for (auto& local : fs->localsplus) {
      if (local == boxed) {
        local = raw;
        changed = true;
      }
    }
    for (auto& stack_value : fs->stack) {
      if (stack_value == boxed) {
        stack_value = raw;
        changed = true;
      }
    }
    fs = fs->parent;
  }
  return changed;
}

void replaceInAllFrameStates(Function& func, Register* boxed, Register* raw) {
  for (auto& block : func.cfg.blocks) {
    for (auto& instr : block) {
      FrameState* fs = get_frame_state(instr);
      if (fs != nullptr) {
        replaceInFrameState(fs, boxed, raw);
      }
    }
  }
}

std::optional<PrimitiveCompareOp> toSignedPrimitiveCompareOp(CompareOp op) {
  switch (op) {
    case CompareOp::kEqual:
      return PrimitiveCompareOp::kEqual;
    case CompareOp::kNotEqual:
      return PrimitiveCompareOp::kNotEqual;
    case CompareOp::kGreaterThan:
      return PrimitiveCompareOp::kGreaterThan;
    case CompareOp::kGreaterThanEqual:
      return PrimitiveCompareOp::kGreaterThanEqual;
    case CompareOp::kLessThan:
      return PrimitiveCompareOp::kLessThan;
    case CompareOp::kLessThanEqual:
      return PrimitiveCompareOp::kLessThanEqual;
    default:
      return std::nullopt;
  }
}

bool identifyPhiCandidate(Phi& phi, PhiCandidate& candidate) {
  if (!(phi.output()->type() <= TLongExact) || phi.NumOperands() != 2) {
    return false;
  }

  BasicBlock* preheader = nullptr;
  BasicBlock* backedge = nullptr;
  Register* init_boxed = nullptr;
  LongInPlaceOp* update = nullptr;

  auto blocks = phi.basic_blocks();
  for (size_t i = 0; i < phi.NumOperands(); ++i) {
    BasicBlock* pred = blocks.at(i);
    Register* input = phi.GetOperand(i);
    Instr* input_instr = input->instr();
    if (input_instr->IsLongInPlaceOp() && input_instr->block() == pred) {
      auto* long_update = static_cast<LongInPlaceOp*>(input_instr);
      if (long_update->op() != InPlaceOpKind::kAdd &&
          long_update->op() != InPlaceOpKind::kSubtract) {
        return false;
      }
      if (update != nullptr) {
        return false;
      }
      backedge = pred;
      update = long_update;
    } else {
      if (init_boxed != nullptr) {
        return false;
      }
      preheader = pred;
      init_boxed = input;
    }
  }

  if (preheader == nullptr || backedge == nullptr || init_boxed == nullptr ||
      update == nullptr) {
    return false;
  }

  candidate = PhiCandidate{
      .phi = &phi,
      .preheader = preheader,
      .backedge = backedge,
      .init_boxed = init_boxed,
      .update = update,
  };
  return true;
}

bool isSupportedCompare(const CompareBool& compare) {
  return toSignedPrimitiveCompareOp(compare.op()).has_value();
}

bool canGuardAsExactLong(Register* reg) {
  reg = chaseAssignOperand(reg);
  return reg->type() <= TObject;
}

bool collectCandidate(
    const RegUses& direct_uses,
    CompareBool& compare,
    LoopCandidate& candidate) {
  if (!isSupportedCompare(compare)) {
    return false;
  }

  BasicBlock* header = nullptr;
  std::unordered_set<Register*> compare_phi_outputs;
  for (Register* operand : {compare.left(), compare.right()}) {
    operand = chaseAssignOperand(operand);
    if (!operand->instr()->IsPhi() || !(operand->type() <= TLongExact)) {
      continue;
    }
    if (header == nullptr) {
      header = operand->instr()->block();
    } else if (header != operand->instr()->block()) {
      return false;
    }
    compare_phi_outputs.insert(operand);
  }

  if (header == nullptr) {
    return false;
  }

  BasicBlock* preheader = nullptr;
  BasicBlock* backedge = nullptr;
  std::vector<PhiCandidate> phis;
  std::unordered_set<Instr*> update_instrs;

  header->forEachPhi([&](Phi& phi) {
    PhiCandidate phi_candidate{};
    if (!identifyPhiCandidate(phi, phi_candidate)) {
      return;
    }
    if (preheader == nullptr) {
      preheader = phi_candidate.preheader;
      backedge = phi_candidate.backedge;
    }
    if (phi_candidate.preheader != preheader ||
        phi_candidate.backedge != backedge) {
      return;
    }
    phis.push_back(phi_candidate);
    update_instrs.insert(phi_candidate.update);
  });

  if (phis.empty() || preheader == nullptr || backedge == nullptr) {
    return false;
  }

  for (Register* compare_phi : compare_phi_outputs) {
    bool found = false;
    for (auto& phi_candidate : phis) {
      if (phi_candidate.phi->output() == compare_phi) {
        found = true;
        break;
      }
    }
    if (!found) {
      return false;
    }
  }

  for (auto& phi_candidate : phis) {
    auto use_it = direct_uses.find(phi_candidate.phi->output());
    if (use_it == direct_uses.end()) {
      continue;
    }
    for (Instr* use : use_it->second) {
      if (update_instrs.contains(use) || use == &compare || use->IsReturn() ||
          use->IsUseType()) {
        continue;
      }
      return false;
    }
  }

  for (Register* operand : {compare.left(), compare.right()}) {
    operand = chaseAssignOperand(operand);
    if (compare_phi_outputs.contains(operand)) {
      continue;
    }
    if (operand->type() <= TCInt64 || getBoxedLongConst(operand).has_value() ||
        operand->type() <= TLongExact || canGuardAsExactLong(operand)) {
      continue;
    }
    return false;
  }

  candidate = LoopCandidate{
      .header = header,
      .preheader = preheader,
      .backedge = backedge,
      .compare = &compare,
      .phis = std::move(phis),
  };
  return true;
}

Instr::List::iterator beforeInstr(Instr& instr) {
  return instr.block()->iterator_to(instr);
}

Instr::List::iterator beforeTerminator(BasicBlock* block) {
  return block->iterator_to(*block->GetTerminator());
}

Register* emitLoadConstInt64(
    Function& func,
    BasicBlock* block,
    Instr::List::iterator insert_it,
    const Instr& anchor,
    int64_t value) {
  Register* out = func.env.AllocateRegister();
  auto* load = LoadConst::create(out, Type::fromCInt(value, TCInt64));
  load->copyBytecodeOffset(anchor);
  block->insert(load, insert_it);
  return out;
}

Register* materializeRawLong(
    Function& func,
    BasicBlock* block,
    Instr::List::iterator insert_it,
    const Instr& anchor,
    const FrameState& frame,
    Register* reg,
    const std::unordered_map<Register*, Register*>& raw_phis,
    const std::unordered_map<Register*, Register*>& invariant_raws) {
  reg = chaseAssignOperand(reg);

  if (auto it = raw_phis.find(reg); it != raw_phis.end()) {
    return it->second;
  }
  if (auto it = invariant_raws.find(reg); it != invariant_raws.end()) {
    return it->second;
  }
  if (reg->type() <= TCInt64) {
    return reg;
  }
  if (auto value = getBoxedLongConst(reg)) {
    return emitLoadConstInt64(func, block, insert_it, anchor, *value);
  }

  Register* long_reg = reg;
  if (!(reg->type() <= TLongExact)) {
    if (!canGuardAsExactLong(reg)) {
      return nullptr;
    }
    long_reg = func.env.AllocateRegister();
    auto* guard = GuardType::create(long_reg, TLongExact, reg, frame);
    guard->copyBytecodeOffset(anchor);
    block->insert(guard, insert_it);
  }

  Register* raw = func.env.AllocateRegister();
  auto* unbox = LongUnboxCompact::create(raw, long_reg, frame);
  unbox->copyBytecodeOffset(anchor);
  block->insert(unbox, insert_it);
  return raw;
}

Register* materializeInvariantRawLong(
    Function& func,
    LoopCandidate& candidate,
    Register* reg,
    std::unordered_map<Register*, Register*>& raw_phis,
    std::unordered_map<Register*, Register*>& invariant_raws) {
  reg = chaseAssignOperand(reg);
  if (auto it = raw_phis.find(reg); it != raw_phis.end()) {
    return it->second;
  }
  if (auto it = invariant_raws.find(reg); it != invariant_raws.end()) {
    return it->second;
  }

  if (!(reg->type() <= TCInt64) && !getBoxedLongConst(reg).has_value()) {
    Instr* def_instr = reg->instr();
    if (def_instr == nullptr || def_instr->block() != candidate.preheader) {
      return nullptr;
    }
  }

  const FrameState* frame =
      candidate.preheader->GetTerminator()->getDominatingFrameState();
  if (frame == nullptr) {
    return nullptr;
  }

  Register* raw = materializeRawLong(
      func,
      candidate.preheader,
      beforeTerminator(candidate.preheader),
      *candidate.compare,
      *frame,
      reg,
      raw_phis,
      invariant_raws);
  if (raw != nullptr) {
    invariant_raws.emplace(reg, raw);
  }
  return raw;
}

bool rewriteCandidate(Function& func, LoopCandidate& candidate) {
  std::unordered_map<Register*, Register*> raw_phis;
  std::unordered_map<Register*, Register*> invariant_raws;

  const FrameState* preheader_frame =
      candidate.preheader->GetTerminator()->getDominatingFrameState();
  if (preheader_frame == nullptr) {
    return false;
  }

  for (auto& phi_candidate : candidate.phis) {
    phi_candidate.raw = func.env.AllocateRegister();
    raw_phis.emplace(phi_candidate.phi->output(), phi_candidate.raw);
  }

  for (auto& phi_candidate : candidate.phis) {
    phi_candidate.raw_init = materializeRawLong(
        func,
        candidate.preheader,
        beforeTerminator(candidate.preheader),
        *candidate.compare,
        *preheader_frame,
        phi_candidate.init_boxed,
        raw_phis,
        invariant_raws);
    if (phi_candidate.raw_init == nullptr) {
      return false;
    }
  }

  Register* compare_left_raw = materializeInvariantRawLong(
      func, candidate, candidate.compare->left(), raw_phis, invariant_raws);
  Register* compare_right_raw = materializeInvariantRawLong(
      func, candidate, candidate.compare->right(), raw_phis, invariant_raws);
  if (compare_left_raw == nullptr || compare_right_raw == nullptr) {
    return false;
  }

  for (auto& phi_candidate : candidate.phis) {
    Instr::List::iterator insert_it = beforeInstr(*phi_candidate.update);
    const FrameState* update_frame = phi_candidate.update->frameState();
    if (update_frame == nullptr) {
      return false;
    }

    Register* left_raw = materializeRawLong(
        func,
        candidate.backedge,
        insert_it,
        *phi_candidate.update,
        *update_frame,
        phi_candidate.update->left(),
        raw_phis,
        invariant_raws);
    Register* right_raw = materializeRawLong(
        func,
        candidate.backedge,
        insert_it,
        *phi_candidate.update,
        *update_frame,
        phi_candidate.update->right(),
        raw_phis,
        invariant_raws);
    if (left_raw == nullptr || right_raw == nullptr) {
      return false;
    }

    auto binop = phi_candidate.update->op() == InPlaceOpKind::kAdd
        ? BinaryOpKind::kAdd
        : BinaryOpKind::kSubtract;
    auto* raw_update = CheckedIntBinaryOp::create(
        phi_candidate.raw_update = func.env.AllocateRegister(),
        binop,
        left_raw,
        right_raw,
        *update_frame);
    raw_update->copyBytecodeOffset(*phi_candidate.update);
    candidate.backedge->insert(raw_update, insert_it);
    phi_candidate.raw_update = raw_update->output();
  }

  auto phi_insert_it = candidate.header->begin();
  while (phi_insert_it != candidate.header->end() && phi_insert_it->IsPhi()) {
    ++phi_insert_it;
  }
  for (auto& phi_candidate : candidate.phis) {
    std::unordered_map<BasicBlock*, Register*> args{
        {candidate.preheader, phi_candidate.raw_init},
        {candidate.backedge, phi_candidate.raw_update},
    };
    auto* raw_phi = Phi::create(phi_candidate.raw, args);
    raw_phi->copyBytecodeOffset(*phi_candidate.phi);
    candidate.header->insert(raw_phi, phi_insert_it);
  }

  auto prim_op = toSignedPrimitiveCompareOp(candidate.compare->op());
  if (!prim_op.has_value()) {
    return false;
  }
  auto* new_compare = PrimitiveCompare::create(
      candidate.compare->output(), *prim_op, compare_left_raw, compare_right_raw);
  new_compare->copyBytecodeOffset(*candidate.compare);
  candidate.compare->block()->insert(new_compare, beforeInstr(*candidate.compare));

  std::vector<Instr*> use_types_to_delete;
  auto direct_uses = collectDirectRegUses(func);
  for (auto& phi_candidate : candidate.phis) {
    replaceInAllFrameStates(func, phi_candidate.phi->output(), phi_candidate.raw);
    replaceInAllFrameStates(
        func, phi_candidate.update->output(), phi_candidate.raw_update);

    auto use_it = direct_uses.find(phi_candidate.phi->output());
    if (use_it == direct_uses.end()) {
      continue;
    }
    for (Instr* use : use_it->second) {
      if (use->IsUseType()) {
        use_types_to_delete.push_back(use);
        continue;
      }
      if (!use->IsReturn()) {
        continue;
      }
      const FrameState* return_frame = use->getDominatingFrameState();
      if (return_frame == nullptr) {
        return false;
      }
      Register* boxed = func.env.AllocateRegister();
      auto* box =
          PrimitiveBox::create(boxed, phi_candidate.raw, TCInt64, *return_frame);
      box->copyBytecodeOffset(*use);
      use->block()->insert(box, beforeInstr(*use));
      use->SetOperand(0, boxed);
    }
  }

  for (Instr* use_type : use_types_to_delete) {
    if (use_type->block() != nullptr) {
      use_type->unlink();
      delete use_type;
    }
  }

  if (candidate.compare->block() != nullptr) {
    candidate.compare->unlink();
    delete candidate.compare;
  }
  for (auto& phi_candidate : candidate.phis) {
    if (phi_candidate.update->block() != nullptr) {
      phi_candidate.update->unlink();
      delete phi_candidate.update;
    }
  }
  for (auto& phi_candidate : candidate.phis) {
    if (phi_candidate.phi->block() != nullptr) {
      phi_candidate.phi->unlink();
      delete phi_candidate.phi;
    }
  }

  return true;
}

} // namespace

void LongLoopUnboxing::Run(Function& irfunc) {
  if (!getConfig().specialized_opcodes) {
    return;
  }

  auto direct_uses = collectDirectRegUses(irfunc);
  std::vector<LoopCandidate> candidates;

  for (auto& block : irfunc.cfg.blocks) {
    for (auto& instr : block) {
      if (!instr.IsCompareBool()) {
        continue;
      }
      LoopCandidate candidate{};
      if (collectCandidate(
              direct_uses, static_cast<CompareBool&>(instr), candidate)) {
        candidates.push_back(std::move(candidate));
      }
    }
  }

  bool changed = false;
  for (auto& candidate : candidates) {
    if (candidate.compare->block() == nullptr) {
      continue;
    }
    changed |= rewriteCandidate(irfunc, candidate);
  }

  if (changed) {
    reflowTypes(irfunc);
  }
}

} // namespace jit::hir
