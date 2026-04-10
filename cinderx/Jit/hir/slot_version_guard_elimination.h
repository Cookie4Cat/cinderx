// Copyright (c) Meta Platforms, Inc. and affiliates.

#pragma once

#include "cinderx/Jit/hir/pass.h"

namespace jit::hir {

class SlotVersionGuardElimination : public Pass {
 public:
  SlotVersionGuardElimination() : Pass("SlotVersionGuardElimination") {}

  void Run(Function& irfunc) override;

  static std::unique_ptr<SlotVersionGuardElimination> Factory() {
    return std::make_unique<SlotVersionGuardElimination>();
  }
};

} // namespace jit::hir
