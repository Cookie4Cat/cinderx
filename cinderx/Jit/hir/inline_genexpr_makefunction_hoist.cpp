// Copyright (c) Meta Platforms, Inc. and affiliates.

#include "cinderx/Jit/hir/inline_genexpr_makefunction_hoist.h"

#include "cinderx/Jit/deopt.h"
#include "cinderx/Jit/hir/analysis.h"
#include "cinderx/Jit/hir/copy_propagation.h"

#include <iterator>
#include <unordered_set>
#include <vector>

namespace jit::hir {

namespace {

struct Candidate {
  BasicBlock* outer_header;
  BasicBlock* iter_block;
  BasicBlock* body;
  BasicBlock* preheader;
  std::vector<BasicBlock*> backedges;
  std::unordered_set<BasicBlock*> metadata_blocks;
  MakeTuple* tuple;
  MakeFunction* make_func;
  SetFunctionAttr* closure_attr;
  std::vector<Instr*> removable_func_uses;
  std::vector<Instr*> removable_tuple_uses;
};

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

bool isInlineGenexprMakeFunction(const MakeFunction& make_func) {
  auto code = getMakeFunctionCode(make_func);
  if (code == nullptr || !isNullQualname(make_func)) {
    return false;
  }
  const char* name = PyUnicode_AsUTF8(code->co_name);
  if (name == nullptr) {
    PyErr_Clear();
    return false;
  }
  return std::strcmp(name, "<genexpr>") == 0;
}

bool isDiscardableUse(const Instr& instr) {
  return instr.IsUseType() || instr.IsDecref() || instr.IsXDecref();
}

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

void replaceMetadataUses(
    Function& func,
    const std::unordered_set<BasicBlock*>& blocks,
    Register* old_reg,
    Register* new_reg) {
  for (auto& block : func.cfg.blocks) {
    if (!blocks.contains(&block)) {
      continue;
    }
    for (auto& instr : block) {
      FrameState* fs = get_frame_state(instr);
      if (fs != nullptr) {
        replaceInFrameState(fs, old_reg, new_reg);
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
      }
      deopt->sortLiveRegs();
      if (deopt->guiltyReg() == old_reg) {
        deopt->setGuiltyReg(new_reg);
      }
    }
  }
}

bool collectDiscardableUses(
    const RegUses& direct_uses,
    Register* reg,
    std::vector<Instr*>& removable) {
  auto it = direct_uses.find(reg);
  if (it == direct_uses.end()) {
    return true;
  }
  for (Instr* use : it->second) {
    if (!isDiscardableUse(*use)) {
      return false;
    }
    removable.push_back(use);
  }
  return true;
}

bool collectLoopShape(
    BasicBlock* body,
    DominatorAnalysis& dom,
    BasicBlock*& outer_header,
    BasicBlock*& iter_block,
    BasicBlock*& preheader,
    std::vector<BasicBlock*>& backedges) {
  if (body->in_edges().size() != 1) {
    return false;
  }
  iter_block = (*body->in_edges().begin())->from();
  if (iter_block == nullptr || !iter_block->back().IsCondBranchIterNotDone()) {
    return false;
  }
  auto* branch = static_cast<CondBranchIterNotDone*>(&iter_block->back());
  if (branch->true_bb() != body) {
    return false;
  }
  if (!body->empty() && body->front().IsPhi()) {
    return false;
  }

  outer_header = iter_block;
  for (;;) {
    const auto& header_dom = dom.getBlocksDominatedBy(outer_header);
    preheader = nullptr;
    backedges.clear();
    for (const Edge* edge : outer_header->in_edges()) {
      BasicBlock* pred = edge->from();
      if (pred == nullptr) {
        continue;
      }
      if (header_dom.contains(pred)) {
        backedges.push_back(pred);
      } else if (preheader == nullptr) {
        preheader = pred;
      } else {
        preheader = nullptr;
        break;
      }
    }
    if (preheader != nullptr && !backedges.empty()) {
      break;
    }
    outer_header =
        const_cast<BasicBlock*>(dom.immediateDominator(outer_header));
    if (outer_header == nullptr) {
      return false;
    }
  }

  const auto& body_dom = dom.getBlocksDominatedBy(body);
  for (BasicBlock* backedge : backedges) {
    if (!body_dom.contains(backedge)) {
      return false;
    }
  }
  return true;
}

bool isLoopInvariantOperand(
    Register* reg,
    const std::unordered_set<const BasicBlock*>& loop_blocks) {
  reg = chaseAssignOperand(reg);
  if (reg == nullptr || reg->instr() == nullptr) {
    return true;
  }
  BasicBlock* def_block = reg->instr()->block();
  return def_block == nullptr || !loop_blocks.contains(def_block);
}

bool collectCandidate(
    Function& func,
    DominatorAnalysis& dom,
    const RegUses& direct_uses,
    MakeFunction& make_func,
    Candidate& candidate) {
  if (!isInlineGenexprMakeFunction(make_func)) {
    return false;
  }

  BasicBlock* body = make_func.block();
  BasicBlock* outer_header = nullptr;
  BasicBlock* iter_block = nullptr;
  BasicBlock* preheader = nullptr;
  std::vector<BasicBlock*> backedges;
  if (!collectLoopShape(
          body, dom, outer_header, iter_block, preheader, backedges)) {
    return false;
  }

  auto use_it = direct_uses.find(make_func.output());
  if (use_it == direct_uses.end()) {
    return false;
  }

  SetFunctionAttr* closure_attr = nullptr;
  std::vector<Instr*> removable_func_uses;
  for (Instr* use : use_it->second) {
    if (isDiscardableUse(*use)) {
      removable_func_uses.push_back(use);
      continue;
    }
    if (!use->IsSetFunctionAttr()) {
      return false;
    }
    auto* set_attr = static_cast<SetFunctionAttr*>(use);
    if (set_attr->base() != make_func.output() ||
        set_attr->field() != FunctionAttr::kClosure) {
      return false;
    }
    if (closure_attr != nullptr) {
      return false;
    }
    closure_attr = set_attr;
  }
  if (closure_attr == nullptr) {
    return false;
  }

  Register* tuple_reg = chaseAssignOperand(closure_attr->value());
  if (tuple_reg == nullptr || !tuple_reg->instr()->IsMakeTuple()) {
    return false;
  }
  auto* tuple = static_cast<MakeTuple*>(tuple_reg->instr());
  if (tuple->block() != body) {
    return false;
  }
  if (&body->front() == tuple) {
    return false;
  }

  const auto& loop_blocks = dom.getBlocksDominatedBy(outer_header);
  std::unordered_set<BasicBlock*> metadata_blocks;
  const auto& body_dominated = dom.getBlocksDominatedBy(body);
  metadata_blocks.insert(body);
  for (const BasicBlock* dominated : body_dominated) {
    metadata_blocks.insert(const_cast<BasicBlock*>(dominated));
  }
  for (Register* operand : tuple->GetOperands()) {
    if (!isLoopInvariantOperand(operand, loop_blocks)) {
      return false;
    }
  }

  std::vector<Instr*> removable_tuple_uses;
  auto tuple_use_it = direct_uses.find(tuple->output());
  if (tuple_use_it != direct_uses.end()) {
    for (Instr* use : tuple_use_it->second) {
      if (use == closure_attr || isDiscardableUse(*use)) {
        removable_tuple_uses.push_back(use);
        continue;
      }
      return false;
    }
  }

  candidate = Candidate{
      outer_header,
      iter_block,
      body,
      preheader,
      std::move(backedges),
      std::move(metadata_blocks),
      tuple,
      &make_func,
      closure_attr,
      std::move(removable_func_uses),
      std::move(removable_tuple_uses),
  };
  return true;
}

Register* emitLoadConstClone(
    Function& func,
    BasicBlock* block,
    Instr::List::iterator insert_it,
    Register* original,
    BCOffset bc_off) {
  auto* load = static_cast<LoadConst*>(original->instr());
  Register* out = func.env.AllocateRegister();
  auto* clone = LoadConst::create(out, load->type());
  clone->setBytecodeOffset(bc_off);
  block->insert(clone, insert_it);
  return out;
}

void removeIfLinked(Instr* instr) {
  if (instr != nullptr && instr->block() != nullptr) {
    instr->unlink();
    delete instr;
  }
}

void hoistCandidate(Function& func, Candidate& candidate) {
  BasicBlock* outer_header = candidate.outer_header;
  BasicBlock* body = candidate.body;
  BasicBlock* preheader = candidate.preheader;

  Register* null_reg = func.env.AllocateRegister();
  auto* null_load = LoadConst::create(null_reg, TNullptr);
  null_load->setBytecodeOffset(candidate.make_func->bytecodeOffset());
  preheader->insert(null_load, preheader->iterator_to(preheader->back()));

  Register* phi_input_reg = func.env.AllocateRegister();
  std::unordered_map<BasicBlock*, Register*> state_inputs{{preheader, null_reg}};
  for (BasicBlock* backedge : candidate.backedges) {
    state_inputs.emplace(backedge, phi_input_reg);
  }
  auto* state_phi = Phi::create(func.env.AllocateRegister(), state_inputs);
  state_phi->setBytecodeOffset(candidate.make_func->bytecodeOffset());
  outer_header->push_front(state_phi);

  auto tuple_it = body->iterator_to(*candidate.tuple);
  auto prev_it = std::prev(tuple_it);
  Instr* split_after = &*prev_it;
  BasicBlock* remainder = func.cfg.splitAfter(*split_after);
  BasicBlock* setup = func.cfg.AllocateBlock();
  auto* dispatch_branch =
      CondBranch::create(state_phi->output(), remainder, setup);
  dispatch_branch->setBytecodeOffset(candidate.make_func->bytecodeOffset());
  body->Append(dispatch_branch);

  Register* tuple_reg = func.env.AllocateRegister();
  auto* tuple_clone = MakeTuple::create(
      candidate.tuple->NumOperands(), tuple_reg, *candidate.tuple->frameState());
  tuple_clone->setBytecodeOffset(candidate.tuple->bytecodeOffset());
  for (size_t i = 0; i < candidate.tuple->NumOperands(); ++i) {
    tuple_clone->SetOperand(i, candidate.tuple->GetOperand(i));
  }
  setup->Append(tuple_clone);

  Register* code_reg = emitLoadConstClone(
      func,
      setup,
      setup->end(),
      candidate.make_func->GetOperand(0),
      candidate.make_func->bytecodeOffset());
  Register* qualname_reg = emitLoadConstClone(
      func,
      setup,
      setup->end(),
      candidate.make_func->GetOperand(1),
      candidate.make_func->bytecodeOffset());

  Register* setup_func_reg = func.env.AllocateRegister();
  auto* make_clone = MakeFunction::create(
      setup_func_reg,
      code_reg,
      qualname_reg,
      *candidate.make_func->frameState());
  make_clone->setBytecodeOffset(candidate.make_func->bytecodeOffset());
  replaceInFrameState(
      make_clone->frameState(),
      candidate.tuple->output(),
      tuple_reg);
  setup->Append(make_clone);

  auto* attr_clone = SetFunctionAttr::create(
      tuple_reg, setup_func_reg, candidate.closure_attr->field());
  attr_clone->setBytecodeOffset(candidate.closure_attr->bytecodeOffset());
  setup->Append(attr_clone);
  setup->Append(Branch::create(remainder));

  std::unordered_map<BasicBlock*, Register*> body_inputs{
      {body, state_phi->output()},
      {setup, setup_func_reg},
  };
  auto* body_phi = Phi::create(phi_input_reg, body_inputs);
  body_phi->setBytecodeOffset(candidate.make_func->bytecodeOffset());
  remainder->push_front(body_phi);

  auto metadata_blocks = candidate.metadata_blocks;
  metadata_blocks.insert(remainder);

  replaceMetadataUses(
      func,
      metadata_blocks,
      candidate.make_func->output(),
      body_phi->output());

  for (Instr* use : candidate.removable_func_uses) {
    removeIfLinked(use);
  }
  for (Instr* use : candidate.removable_tuple_uses) {
    removeIfLinked(use);
  }
  removeIfLinked(candidate.closure_attr);
  removeIfLinked(candidate.make_func);
  removeIfLinked(candidate.tuple);
}

} // namespace

void InlineGenexprMakeFunctionHoist::Run(Function& irfunc) {
  DominatorAnalysis dom(irfunc);
  RegUses direct_uses = collectDirectRegUses(irfunc);
  std::vector<Candidate> candidates;

  for (auto& block : irfunc.cfg.blocks) {
    for (auto& instr : block) {
      if (!instr.IsMakeFunction()) {
        continue;
      }
      Candidate candidate{};
      if (collectCandidate(
              irfunc,
              dom,
              direct_uses,
              static_cast<MakeFunction&>(instr),
              candidate)) {
        candidates.push_back(std::move(candidate));
      }
    }
  }

  if (candidates.empty()) {
    return;
  }

  for (auto& candidate : candidates) {
    hoistCandidate(irfunc, candidate);
  }

  CopyPropagation{}.Run(irfunc);
  reflowTypes(irfunc);
}

} // namespace jit::hir
