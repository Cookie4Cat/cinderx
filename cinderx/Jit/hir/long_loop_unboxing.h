// Copyright (c) Meta Platforms, Inc. and affiliates.

#pragma once

#include "cinderx/Jit/hir/pass.h"

#include <memory>

namespace jit::hir {

class LongLoopUnboxing : public Pass {
 public:
  LongLoopUnboxing() : Pass("LongLoopUnboxing") {}

  void Run(Function& irfunc) override;

  static std::unique_ptr<LongLoopUnboxing> Factory() {
    return std::make_unique<LongLoopUnboxing>();
  }
};

} // namespace jit::hir
