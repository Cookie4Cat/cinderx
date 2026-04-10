// Copyright (c) Meta Platforms, Inc. and affiliates.

#pragma once

#include "cinderx/Jit/hir/pass.h"

#include <memory>

namespace jit::hir {

class ListSliceCleanup : public Pass {
 public:
  ListSliceCleanup() : Pass("ListSliceCleanup") {}

  void Run(Function& irfunc) override;

  static std::unique_ptr<ListSliceCleanup> Factory() {
    return std::make_unique<ListSliceCleanup>();
  }
};

} // namespace jit::hir
