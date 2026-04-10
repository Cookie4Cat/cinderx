// Copyright (c) Meta Platforms, Inc. and affiliates.

#include "cinderx/Jit/hir/slot_version_guard_elimination.h"

#include "cinderx/Jit/hir/analysis.h"
#include "cinderx/Jit/hir/instr_effects.h"
#include "cinderx/Jit/hir/pass.h"

#include <algorithm>
#include <cstdint>
#include <optional>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace jit::hir {

namespace {

struct GuardKey {
  Register* receiver;
  uint32_t expected_tag;

  bool operator==(const GuardKey& other) const {
    return receiver == other.receiver && expected_tag == other.expected_tag;
  }
};

struct GuardKeyHash {
  std::size_t operator()(const GuardKey& key) const {
    std::size_t h1 = std::hash<Register*>{}(key.receiver);
    std::size_t h2 = std::hash<uint32_t>{}(key.expected_tag);
    return h1 ^ (h2 + 0x9e3779b97f4a7c15ULL + (h1 << 6) + (h1 >> 2));
  }
};

using ActiveGuards = std::unordered_set<GuardKey, GuardKeyHash>;
using DomTree = std::unordered_map<BasicBlock*, std::vector<BasicBlock*>>;

bool isSlotVersionGuardDescr(const std::string& descr) {
  return descr == "LOAD_ATTR_SLOT" || descr == "STORE_ATTR_SLOT";
}

std::optional<uint32_t> getExpectedTag(Register* reg) {
  reg = chaseAssignOperand(reg);
  if (!reg->instr()->IsLoadConst() || !reg->type().hasIntSpec()) {
    return std::nullopt;
  }
  return static_cast<uint32_t>(reg->type().intSpec());
}

Register* getGuardedReceiver(Register* reg) {
  reg = chaseAssignOperand(reg);
  if (!reg->instr()->IsLoadField()) {
    return nullptr;
  }

  auto* version_load = static_cast<LoadField*>(reg->instr());
  if (version_load->name() != "tp_version_tag" ||
      version_load->offset() != offsetof(PyTypeObject, tp_version_tag)) {
    return nullptr;
  }

  Register* obj_type = chaseAssignOperand(version_load->receiver());
  if (!obj_type->instr()->IsLoadField()) {
    return nullptr;
  }

  auto* obj_type_load = static_cast<LoadField*>(obj_type->instr());
  if (obj_type_load->name() != "ob_type" ||
      obj_type_load->offset() != offsetof(PyObject, ob_type)) {
    return nullptr;
  }

  return modelReg(obj_type_load->receiver());
}

std::optional<GuardKey> getGuardKey(Guard* guard) {
  Register* cond = chaseAssignOperand(guard->GetOperand(0));
  if (!isSlotVersionGuardDescr(guard->descr())) {
    return std::nullopt;
  }

  if (!cond->instr()->IsPrimitiveCompare()) {
    return std::nullopt;
  }

  auto* compare = static_cast<PrimitiveCompare*>(cond->instr());
  if (compare->op() != PrimitiveCompareOp::kEqual) {
    return std::nullopt;
  }

  Register* receiver = getGuardedReceiver(compare->left());
  std::optional<uint32_t> tag = getExpectedTag(compare->right());
  if (receiver != nullptr && tag.has_value()) {
    return GuardKey{receiver, *tag};
  }

  receiver = getGuardedReceiver(compare->right());
  tag = getExpectedTag(compare->left());
  if (receiver != nullptr && tag.has_value()) {
    return GuardKey{receiver, *tag};
  }

  return std::nullopt;
}

DomTree buildDominatorTree(Function& func) {
  DominatorAnalysis doms{func};
  DomTree dom_tree;

  for (auto& block : func.cfg.blocks) {
    auto* cur = &block;
    dom_tree.try_emplace(cur);
    const BasicBlock* idom = doms.immediateDominator(cur);
    if (idom != nullptr) {
      dom_tree[const_cast<BasicBlock*>(idom)].push_back(cur);
    }
  }

  return dom_tree;
}

void walkDomTree(
    BasicBlock* block,
    const DomTree& dom_tree,
    ActiveGuards active,
    std::vector<Instr*>& redundant_guards) {
  for (auto& instr : *block) {
    if (instr.IsGuard()) {
      auto* guard = static_cast<Guard*>(&instr);
      auto key = getGuardKey(guard);
      if (key.has_value()) {
        if (active.contains(*key)) {
          redundant_guards.push_back(guard);
        } else {
          active.insert(*key);
        }
      }
    }

    if (hasArbitraryExecution(instr)) {
      active.clear();
    }
  }

  auto it = dom_tree.find(block);
  if (it == dom_tree.end()) {
    return;
  }
  for (BasicBlock* child : it->second) {
    walkDomTree(child, dom_tree, active, redundant_guards);
  }
}

} // namespace

void SlotVersionGuardElimination::Run(Function& irfunc) {
  if (irfunc.cfg.entry_block == nullptr) {
    return;
  }

  DomTree dom_tree = buildDominatorTree(irfunc);
  std::vector<Instr*> redundant_guards;
  walkDomTree(irfunc.cfg.entry_block, dom_tree, ActiveGuards{}, redundant_guards);

  if (redundant_guards.empty()) {
    return;
  }

  for (Instr* instr : redundant_guards) {
    instr->unlink();
    delete instr;
  }
}

} // namespace jit::hir
