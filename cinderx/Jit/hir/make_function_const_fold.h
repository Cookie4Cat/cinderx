// Copyright (c) Meta Platforms, Inc. and affiliates.

#pragma once

#include "cinderx/Jit/hir/pass.h"

#include <memory>

namespace jit::hir {

class MakeFunctionConstFold : public Pass {
 public:
  MakeFunctionConstFold() : Pass("MakeFunctionConstFold") {}

  void Run(Function& irfunc) override;

  static std::unique_ptr<MakeFunctionConstFold> Factory() {
    return std::make_unique<MakeFunctionConstFold>();
  }
};

} // namespace jit::hir
