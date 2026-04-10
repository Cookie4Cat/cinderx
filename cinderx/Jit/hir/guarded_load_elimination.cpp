// Copyright (c) Meta Platforms, Inc. and affiliates.

#include "cinderx/Jit/hir/guarded_load_elimination.h"

#include "cinderx/Jit/hir/analysis.h"
#include "cinderx/Jit/hir/instr_effects.h"

#include <optional>
#include <string>
#include <unordered_map>

namespace jit::hir {

namespace {

enum class GuardedValueKind {
  kGuardType,
  kLoadField,
  kLoadTupleItem,
  kLoadMethod,
  kLoadMethodCached,
};

struct GuardedLoadKey {
  GuardedValueKind kind;
  Register* receiver;
  const PyCodeObject* code;
  int name_idx;
  std::size_t offset_or_index;
  Type type;
  bool borrowed;

  bool operator==(const GuardedLoadKey& other) const = default;
};

struct GuardedLoadKeyHash {
  std::size_t operator()(const GuardedLoadKey& key) const {
    std::size_t h = std::hash<int>{}(static_cast<int>(key.kind));
    auto combine = [&h](std::size_t value) {
      h ^= value + 0x9e3779b9 + (h << 6) + (h >> 2);
    };

    combine(std::hash<Register*>{}(key.receiver));
    combine(std::hash<const PyCodeObject*>{}(key.code));
    combine(std::hash<int>{}(key.name_idx));
    combine(std::hash<std::size_t>{}(key.offset_or_index));
    combine(std::hash<Type>{}(key.type));
    combine(std::hash<bool>{}(key.borrowed));
    return h;
  }
};

using AvailableLoads =
    std::unordered_map<GuardedLoadKey, Register*, GuardedLoadKeyHash>;

Register* canonicalizeReceiver(Register* reg) {
  return chaseAssignOperand(reg);
}

bool hasStableExactReceiverType(Register* reg) {
  reg = canonicalizeReceiver(reg);
  if (reg == nullptr) {
    return false;
  }
  Type type = reg->type();
  return type.isExact() && type.runtimePyType() != nullptr;
}

std::optional<GuardedLoadKey> makeGuardedLoadKey(const Instr& instr) {
  switch (instr.opcode()) {
    case Opcode::kGuardType: {
      const auto& guard = static_cast<const GuardType&>(instr);
      return GuardedLoadKey{
          GuardedValueKind::kGuardType,
          canonicalizeReceiver(guard.GetOperand(0)),
          nullptr,
          -1,
          0,
          guard.target(),
          false};
    }
    case Opcode::kLoadField: {
      const auto& load = static_cast<const LoadField&>(instr);
      return GuardedLoadKey{
          GuardedValueKind::kLoadField,
          canonicalizeReceiver(load.receiver()),
          nullptr,
          -1,
          load.offset(),
          load.type(),
          load.borrowed()};
    }
    case Opcode::kLoadTupleItem: {
      const auto& load = static_cast<const LoadTupleItem&>(instr);
      return GuardedLoadKey{
          GuardedValueKind::kLoadTupleItem,
          canonicalizeReceiver(load.tuple()),
          nullptr,
          -1,
          load.idx(),
          TBottom,
          true};
    }
    case Opcode::kLoadMethod:
    case Opcode::kLoadMethodCached: {
      const auto& load = static_cast<const DeoptBaseWithNameIdx&>(instr);
      Register* receiver = canonicalizeReceiver(load.GetOperand(0));
      if (!hasStableExactReceiverType(receiver)) {
        return std::nullopt;
      }

      GuardedValueKind kind = GuardedValueKind::kLoadMethod;
      switch (instr.opcode()) {
        case Opcode::kLoadMethod:
          kind = GuardedValueKind::kLoadMethod;
          break;
        case Opcode::kLoadMethodCached:
          kind = GuardedValueKind::kLoadMethodCached;
          break;
        default:
          JIT_ABORT("unexpected opcode {}", instr.opname());
      }

      auto* frame = load.frameState();
      return GuardedLoadKey{
          kind,
          receiver,
          frame != nullptr ? frame->code.get() : nullptr,
          load.name_idx(),
          0,
          TBottom,
          false};
    }
    default:
      return std::nullopt;
  }
}

AliasClass aliasClassForKey(const GuardedLoadKey& key) {
  switch (key.kind) {
    case GuardedValueKind::kGuardType:
      return AEmpty;
    case GuardedValueKind::kLoadField:
      return AInObjectAttr;
    case GuardedValueKind::kLoadTupleItem:
      return ATupleItem;
    case GuardedValueKind::kLoadMethod:
    case GuardedValueKind::kLoadMethodCached:
      return AManagedHeapAny;
  }

  JIT_ABORT("bad guarded value kind");
}

bool canInvalidateGuardedLoad(const GuardedLoadKey& key, const Instr& instr) {
  if (hasArbitraryExecution(instr)) {
    return true;
  }

  if (instr.IsPhi() || instr.IsBranch() || instr.IsCondBranch() ||
      instr.IsCondBranchCheckType() || instr.IsCondBranchIterNotDone()) {
    return false;
  }

  if (key.kind == GuardedValueKind::kGuardType) {
    return false;
  }

  AliasClass may_store = memoryEffects(instr).may_store;
  return (may_store & aliasClassForKey(key)).bits() != 0;
}

void invalidateGuardedLoads(AvailableLoads& state, const Instr& instr) {
  for (auto it = state.begin(); it != state.end();) {
    if (canInvalidateGuardedLoad(it->first, instr)) {
      it = state.erase(it);
      continue;
    }
    ++it;
  }
}

void replaceAllUses(Function& func, Register* orig, Register* replacement) {
  for (auto& block : func.cfg.blocks) {
    for (Instr& instr : block) {
      instr.ReplaceUsesOf(orig, replacement);
    }
  }
}

AvailableLoads intersectAvailableLoads(
    const BasicBlock* block,
    const std::unordered_map<const BasicBlock*, AvailableLoads>& out_states) {
  AvailableLoads result;
  bool first_pred = true;
  for (const Edge* edge : block->in_edges()) {
    const BasicBlock* pred = edge->from();
    auto it = out_states.find(pred);
    if (it == out_states.end()) {
      return {};
    }

    if (first_pred) {
      result = it->second;
      first_pred = false;
      continue;
    }

    for (auto result_it = result.begin(); result_it != result.end();) {
      auto pred_it = it->second.find(result_it->first);
      if (pred_it == it->second.end() || pred_it->second != result_it->second) {
        result_it = result.erase(result_it);
        continue;
      }
      ++result_it;
    }
  }
  return result;
}

bool processBlock(
    Function& func,
    BasicBlock* block,
    const AvailableLoads& in_state,
    AvailableLoads& out_state) {
  bool modified = false;
  AvailableLoads state = in_state;

  for (auto it = block->begin(); it != block->end();) {
    Instr& instr = *it;
    ++it;

    auto key = makeGuardedLoadKey(instr);
    if (key.has_value()) {
      auto existing = state.find(*key);
      if (existing != state.end()) {
        replaceAllUses(func, instr.output(), existing->second);
        instr.unlink();
        modified = true;
        continue;
      }
    }

    invalidateGuardedLoads(state, instr);

    if (key.has_value()) {
      state[*key] = instr.output();
    }
  }

  out_state = std::move(state);
  return modified;
}

} // namespace

void GuardedLoadElimination::Run(Function& func) {
  bool modified = false;
  auto blocks = func.cfg.GetRPOTraversal();
  std::unordered_map<const BasicBlock*, AvailableLoads> out_states;

  for (BasicBlock* block : blocks) {
    AvailableLoads in_state = intersectAvailableLoads(block, out_states);
    AvailableLoads out_state;
    modified |= processBlock(func, block, in_state, out_state);
    out_states[block] = std::move(out_state);
  }

  if (modified) {
    reflowTypes(func);
  }
}

} // namespace jit::hir
