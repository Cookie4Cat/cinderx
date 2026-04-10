// Copyright (c) Meta Platforms, Inc. and affiliates.

#include "cinderx/Jit/hir/dynamic_comparison_elimination.h"

#include "cinderx/Jit/hir/analysis.h"

namespace jit::hir {

namespace {

template <typename CompareInstr>
Instr* replaceCompare(CompareInstr* compare, IsTruthy* truthy) {
  return CompareBool::create(
      truthy->output(),
      compare->op(),
      compare->GetOperand(0),
      compare->GetOperand(1),
      *get_frame_state(*truthy));
}

Instr* replaceLongComparePrimitiveCompare(
    LongCompare* compare,
    PrimitiveCompare* prim_compare,
    const FrameState& frame) {
  return CompareBool::create(
      prim_compare->output(),
      compare->op(),
      compare->GetOperand(0),
      compare->GetOperand(1),
      frame);
}

} // namespace

void DynamicComparisonElimination::Run(Function& irfunc) {
  LivenessAnalysis liveness{irfunc};
  liveness.Run();
  auto last_uses = liveness.GetLastUses();

  // Optimize "if x is y" case
  for (auto& block : irfunc.cfg.blocks) {
    auto& instr = block.back();

    // Looking for:
    //   $some_conditional = ...
    //   $truthy = IsTruthy $compare
    //   CondBranch<x, y> $truthy
    // Which we then re-write to a form which doesn't use IsTruthy anymore.
    if (!instr.IsCondBranch()) {
      continue;
    }

    Instr* truthy = instr.GetOperand(0)->instr();

    if (truthy->IsPrimitiveCompare()) {
      auto prim_compare = static_cast<PrimitiveCompare*>(truthy);
      LongCompare* long_compare = nullptr;
      if (prim_compare->op() == PrimitiveCompareOp::kEqual) {
        if (prim_compare->left()->instr()->IsLongCompare() &&
            prim_compare->right()->type().asObject() == Py_True) {
          long_compare = static_cast<LongCompare*>(prim_compare->left()->instr());
        } else if (
            prim_compare->right()->instr()->IsLongCompare() &&
            prim_compare->left()->type().asObject() == Py_True) {
          long_compare =
              static_cast<LongCompare*>(prim_compare->right()->instr());
        }
      }

      if (long_compare != nullptr && long_compare->block() == &block) {
        auto& dying_regs = map_get(last_uses, prim_compare, kEmptyRegSet);
        if (dying_regs.contains(long_compare->output())) {
          std::vector<Instr*> dead_uses;
          bool can_optimize = false;
          for (auto it = std::next(block.rbegin()); it != block.rend(); ++it) {
            if (&*it == long_compare) {
              can_optimize = true;
              break;
            }
            if (&*it == prim_compare) {
              continue;
            }
            if (it->IsSnapshot() || it->IsUseType()) {
              if (it->Uses(long_compare->output())) {
                dead_uses.push_back(&*it);
              }
              continue;
            }
            if (!it->isReplayable() || it->Uses(long_compare->output())) {
              can_optimize = false;
              break;
            }
          }

          const FrameState* frame = nullptr;
          if (can_optimize) {
            auto it = block.reverse_iterator_to(*long_compare);
            while (++it != block.rend()) {
              if (it->IsSnapshot()) {
                frame = get_frame_state(*it);
                break;
              }
            }
          }

          if (can_optimize && frame != nullptr) {
            Instr* replacement = replaceLongComparePrimitiveCompare(
                long_compare, prim_compare, *frame);
            replacement->copyBytecodeOffset(instr);
            prim_compare->ReplaceWith(*replacement);

            long_compare->unlink();
            delete long_compare;
            delete prim_compare;

            for (auto dead_use : dead_uses) {
              dead_use->unlink();
              delete dead_use;
            }
            continue;
          }
        }
      }
    }

    if (!truthy->IsIsTruthy() || truthy->block() != &block) {
      continue;
    }

    Instr* truthy_target = truthy->GetOperand(0)->instr();
    if (truthy_target->block() != &block ||
        (!truthy_target->IsCompare() && !truthy_target->IsLongCompare() &&
         !truthy_target->IsVectorCall())) {
      continue;
    }

    auto& dying_regs = map_get(last_uses, truthy, kEmptyRegSet);

    if (!dying_regs.contains(truthy->GetOperand(0))) {
      // Compare output lives on, we can't re-write...
      continue;
    }

    // Make sure the output of compare isn't getting used between the compare
    // and the branch other than by the truthy instruction.
    std::vector<Instr*> snapshots;
    bool can_optimize = true;
    for (auto it = std::next(block.rbegin()); it != block.rend(); ++it) {
      if (&*it == truthy_target) {
        break;
      } else if (&*it != truthy) {
        if (it->IsSnapshot()) {
          if (it->Uses(truthy_target->output())) {
            snapshots.push_back(&*it);
          }
          continue;
        } else if (!it->isReplayable()) {
          can_optimize = false;
          break;
        }

        if (it->Uses(truthy->GetOperand(0))) {
          can_optimize = false;
          break;
        }
      }
    }
    if (!can_optimize) {
      continue;
    }

    Instr* replacement = nullptr;
    if (truthy_target->IsCompare()) {
      auto compare = static_cast<Compare*>(truthy_target);

      replacement = replaceCompare(compare, static_cast<IsTruthy*>(truthy));
    } else if (truthy_target->IsLongCompare()) {
      auto compare = static_cast<LongCompare*>(truthy_target);

      replacement = replaceCompare(compare, static_cast<IsTruthy*>(truthy));
    }

    if (replacement != nullptr) {
      replacement->copyBytecodeOffset(instr);
      truthy->ReplaceWith(*replacement);

      truthy_target->unlink();
      delete truthy_target;
      delete truthy;

      // There may be zero or more Snapshots between the Compare and the
      // IsTruthy that uses the output of the Compare (which we want to delete).
      // Since we're fusing the two operations together, the Snapshot and
      // its use of the dead intermediate value should be deleted.
      for (auto snapshot : snapshots) {
        snapshot->unlink();
        delete snapshot;
      }
    }
  }

  reflowTypes(irfunc);
}

} // namespace jit::hir
