// Copyright (c) Meta Platforms, Inc. and affiliates.

#pragma once

#include "cinderx/Jit/hir/pass.h"

namespace jit::hir {

class GuardedLoadElimination : public Pass {
 public:
  GuardedLoadElimination() : Pass("GuardedLoadElimination") {}

  void Run(Function& func) override;

  static std::unique_ptr<GuardedLoadElimination> Factory() {
    return std::make_unique<GuardedLoadElimination>();
  }

 private:
  DISALLOW_COPY_AND_ASSIGN(GuardedLoadElimination);
};

} // namespace jit::hir
