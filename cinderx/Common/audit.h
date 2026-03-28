// Copyright (c) Meta Platforms, Inc. and affiliates.

#pragma once

#include "cinderx/python.h"

#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

// Wraps PySys_AddAuditHook().
//
// PySys_AddAuditHook() can fail to add the hook but still return 0 if an
// existing audit function aborts the sys.addaudithook event. Since we rely
// on it for correctness, walk the linked list of audit functions and make
// sure ours is there.
bool installAuditHook(Py_AuditHookFunction func, void* userData);

// Register an internal audit hook that is known not to observe builtins.id.
// These hooks are ignored by canBypassBuiltinIdAudit().
void registerBuiltinIdIgnorableAuditHook(
    Py_AuditHookFunction func,
    void* userData);

// Return 1 when it is safe for JIT code to bypass the builtin id() audit call,
// or 0 when JIT must preserve the full builtin path.
int canBypassBuiltinIdAudit(void);

// Return id(obj) as a signed 64-bit integer while preserving builtin id()
// audit semantics. Returns -1 with an exception set if auditing fails.
int64_t builtinIdAsInt64(PyObject* obj);

#ifdef __cplusplus
}
#endif
