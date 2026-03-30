// Copyright (c) Meta Platforms, Inc. and affiliates.

#pragma once

#include "cinderx/Jit/hir/pass.h"

namespace jit::hir {

class InlineGenexprMakeFunctionHoist : public Pass {
 public:
  InlineGenexprMakeFunctionHoist()
      : Pass("InlineGenexprMakeFunctionHoist") {}

  void Run(Function& irfunc) override;

  static std::unique_ptr<InlineGenexprMakeFunctionHoist> Factory() {
    return std::make_unique<InlineGenexprMakeFunctionHoist>();
  }
};

} // namespace jit::hir
