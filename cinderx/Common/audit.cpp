// Copyright (c) Meta Platforms, Inc. and affiliates.

#include "cinderx/Common/audit.h"

#include "internal/pycore_runtime.h"

#if PY_VERSION_HEX >= 0x030C0000
#include "internal/pycore_interp_structs.h"
#endif

#if PY_VERSION_HEX >= 0x030E0000
#include "internal/pycore_audit.h"
#endif

#include <vector>

extern "C" {

namespace {

struct IgnorableAuditHook {
  Py_AuditHookFunction func;
  void* userData;
};

_Py_AuditHookEntry* auditHookHead() {
  _PyRuntimeState* runtime = &_PyRuntime;
#if PY_VERSION_HEX >= 0x030E0000
  // If the actual runtime state is a different size than we were compiled with
  // we cannot safely inspect the audit-hook list.
  if (runtime->debug_offsets.runtime_state.size != sizeof(_PyRuntimeState)) {
    return reinterpret_cast<_Py_AuditHookEntry*>(-1);
  }
#endif
#if PY_VERSION_HEX < 0x030C0000
  return runtime->audit_hook_head;
#else
  return runtime->audit_hooks.head;
#endif
}

std::vector<IgnorableAuditHook>& builtinIdIgnorableHooks() {
  static auto* hooks = new std::vector<IgnorableAuditHook>();
  return *hooks;
}

bool isBuiltinIdIgnorableHook(_Py_AuditHookEntry* entry) {
  for (const auto& hook : builtinIdIgnorableHooks()) {
    if (entry->hookCFunction == hook.func && entry->userData == hook.userData) {
      return true;
    }
  }
  return false;
}

bool hasPythonAuditHooks() {
#if PY_VERSION_HEX >= 0x030C0000
  PyThreadState* tstate = PyThreadState_GetUnchecked();
  if (tstate == nullptr || tstate->interp == nullptr) {
    return false;
  }

  PyInterpreterState* interp = tstate->interp;
  if (interp->audit_hooks == nullptr) {
    return false;
  }

  if (PyList_Check(interp->audit_hooks)) {
    return PyList_GET_SIZE(interp->audit_hooks) > 0;
  }

  Py_ssize_t size = PyObject_Size(interp->audit_hooks);
  return size > 0;
#else
  return false;
#endif
}

} // namespace

bool installAuditHook(Py_AuditHookFunction func, void* userData) {
  if (PySys_AddAuditHook(func, userData) < 0) {
    return false;
  }

  _Py_AuditHookEntry* audit_hook_head = auditHookHead();
  if (audit_hook_head == reinterpret_cast<_Py_AuditHookEntry*>(-1)) {
    return true;
  }

  // Verify that the hook was actually installed.
  for (_Py_AuditHookEntry* e = audit_hook_head; e != nullptr; e = e->next) {
    if (e->hookCFunction == func && e->userData == userData) {
      return true;
    }
  }

  return false;
}

void registerBuiltinIdIgnorableAuditHook(
    Py_AuditHookFunction func,
    void* userData) {
  auto& hooks = builtinIdIgnorableHooks();
  for (const auto& hook : hooks) {
    if (hook.func == func && hook.userData == userData) {
      return;
    }
  }
  hooks.push_back({func, userData});
}

int canBypassBuiltinIdAudit(void) {
  // Python-level hooks from sys.addaudithook() must be observed by id().
  // They are stored separately from the C audit hook linked list.
  if (hasPythonAuditHooks()) {
    return 0;
  }

  _Py_AuditHookEntry* audit_hook_head = auditHookHead();
  if (audit_hook_head == reinterpret_cast<_Py_AuditHookEntry*>(-1)) {
    return 0;
  }
  for (_Py_AuditHookEntry* e = audit_hook_head; e != nullptr; e = e->next) {
    if (!isBuiltinIdIgnorableHook(e)) {
      return 0;
    }
  }
  return 1;
}

int64_t builtinIdAsInt64(PyObject* obj) {
  if (!canBypassBuiltinIdAudit()) {
    if (PySys_Audit("builtins.id", "O", obj) < 0) {
      return -1;
    }
  }
  return static_cast<int64_t>(reinterpret_cast<uintptr_t>(obj));
}

} // extern "C"
