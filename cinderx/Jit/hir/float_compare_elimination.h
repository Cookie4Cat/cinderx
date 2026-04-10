// Copyright (c) Meta Platforms, Inc. and affiliates.

#pragma once

#include "cinderx/Jit/hir/pass.h"

#include <memory>

namespace jit::hir {

class FloatCompareElimination : public Pass {
 public:
  FloatCompareElimination() : Pass("FloatCompareElimination") {}

  void Run(Function& irfunc) override;

  static std::unique_ptr<FloatCompareElimination> Factory() {
    return std::make_unique<FloatCompareElimination>();
  }
};

} // namespace jit::hir
