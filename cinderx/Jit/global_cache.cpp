// Copyright (c) Meta Platforms, Inc. and affiliates.

#include "cinderx/Jit/global_cache.h"

#include "cinderx/Common/dict.h"
#include "cinderx/Common/util.h"
#include "cinderx/Common/watchers.h"
#include "cinderx/Jit/threaded_compile.h"
#include "cinderx/module_state.h"

#include <algorithm>

#ifndef ENABLE_LAZY_IMPORTS
#ifdef PyLazyImport_CheckExact
#undef PyLazyImport_CheckExact
#endif
#define PyLazyImport_CheckExact(OBJ) false
#endif

namespace jit {

GlobalCacheKey::GlobalCacheKey(
    BorrowedRef<PyDictObject> builtins,
    BorrowedRef<PyDictObject> globals,
    BorrowedRef<PyUnicodeObject> name)
    : builtins{builtins}, globals{globals} {
  ThreadedCompileSerialize guard;
  JIT_CHECK(
      PyUnicode_CHECK_INTERNED(name.get()),
      "Global cache names must be interned; they'll be compared by pointer "
      "value");
  this->name = Ref<>::create(name);
}

GlobalCacheKey::~GlobalCacheKey() {
  ThreadedCompileSerialize guard;
  name.reset();
}

std::size_t GlobalCacheKeyHash::operator()(const GlobalCacheKey& key) const {
  std::hash<PyObject*> hasher;
  return combineHash(
      hasher(key.builtins), hasher(key.globals), hasher(key.name));
}

GlobalCache::GlobalCache(GlobalCacheMap::value_type* pair) : pair_(pair) {}

const GlobalCacheKey& GlobalCache::key() const {
  return pair_->first;
}

PyObject** GlobalCache::valuePtr() const {
  return pair_->second;
}

void GlobalCache::init(PyObject** cache) const {
  pair_->second = cache;
}

void GlobalCache::clear() {
  *valuePtr() = nullptr;
}

bool GlobalCache::operator==(const GlobalCache& other) const {
  return pair_ == other.pair_;
}

bool GlobalCache::operator<(const GlobalCache& other) const {
  return pair_ < other.pair_;
}

bool GlobalCacheWatchers::contains(GlobalCache cache) const {
  if (single_.has_value()) {
    return *single_ == cache;
  }
  return std::find(many_.begin(), many_.end(), cache) != many_.end();
}

bool GlobalCacheWatchers::empty() const {
  return !single_.has_value() && many_.empty();
}

void GlobalCacheWatchers::addUnchecked(GlobalCache cache) {
  if (!single_.has_value() && many_.empty()) {
    single_.emplace(cache);
    return;
  }
  if (single_.has_value()) {
    many_.reserve(2);
    many_.push_back(*single_);
    single_.reset();
  }
  many_.push_back(cache);
}

void GlobalCacheWatchers::remove(GlobalCache cache) {
  if (single_.has_value()) {
    JIT_CHECK(*single_ == cache, "cache was not watching key");
    single_.reset();
    return;
  }

  auto cache_it = std::find(many_.begin(), many_.end(), cache);
  JIT_CHECK(cache_it != many_.end(), "cache was not watching key");
  *cache_it = many_.back();
  many_.pop_back();
  if (many_.size() == 1) {
    single_.emplace(many_.back());
    many_.clear();
  }
}

void GlobalCacheWatchers::appendTo(std::vector<GlobalCache>& out) const {
  if (single_.has_value()) {
    out.push_back(*single_);
    return;
  }
  out.insert(out.end(), many_.begin(), many_.end());
}

std::vector<GlobalCache> GlobalCacheWatchers::snapshot() const {
  std::vector<GlobalCache> watchers;
  if (single_.has_value()) {
    watchers.push_back(*single_);
    return watchers;
  }
  watchers = many_;
  return watchers;
}

GlobalCacheManager::~GlobalCacheManager() {
  clear();
}

GlobalCache GlobalCacheManager::findGlobalCache(
    BorrowedRef<PyDictObject> builtins,
    BorrowedRef<PyDictObject> globals,
    BorrowedRef<PyUnicodeObject> key) {
  auto result = map_.emplace(
      std::piecewise_construct,
      std::forward_as_tuple(builtins, globals, key),
      std::forward_as_tuple());
  GlobalCache cache(&*result.first);

  // This is a new global cache entry, so we have to initialize it.
  if (result.second) {
    initCache(cache);
  }

  return cache;
}

PyObject** GlobalCacheManager::getGlobalCache(
    BorrowedRef<PyDictObject> builtins,
    BorrowedRef<PyDictObject> globals,
    BorrowedRef<PyUnicodeObject> key) {
  try {
#ifdef Py_GIL_DISABLED
    std::lock_guard<std::recursive_mutex> lock(mutex_);
#endif
    auto cache = findGlobalCache(builtins, globals, key);
    return cache.valuePtr();
  } catch (std::bad_alloc&) {
    return nullptr;
  }
}

void GlobalCacheManager::notifyDictUpdate(
    BorrowedRef<PyDictObject> dict,
    BorrowedRef<PyUnicodeObject> key,
    BorrowedRef<> value) {
  JIT_CHECK(
      PyUnicode_CHECK_INTERNED(key.get()),
      "Dict key must be interned as it'll be compared by pointer value");

#ifdef Py_GIL_DISABLED
  std::lock_guard<std::recursive_mutex> lock(mutex_);
#endif
  auto dict_it = watch_map_.find(dict);
  // Something else in Cinderx could be watching this dict. Return early if no
  // watchers were registered for this key.
  if (dict_it == watch_map_.end()) {
    return;
  }
  auto key_it = dict_it->second.find(key);
  if (key_it == dict_it->second.end()) {
    return;
  }
  std::vector<GlobalCache> to_disable;
  if (value != nullptr) {
    key_it->second.forEach([&](GlobalCache cache) {
      if (updateCache(cache, dict, value)) {
        to_disable.emplace_back(cache);
      }
    });
  } else {
    auto watchers = key_it->second.snapshot();
    for (GlobalCache cache : watchers) {
      if (updateCache(cache, dict, value)) {
        to_disable.emplace_back(cache);
      }
    }
  }
  disableCaches(to_disable);
}

void GlobalCacheManager::notifyDictClear(BorrowedRef<PyDictObject> dict) {
#ifdef Py_GIL_DISABLED
  std::lock_guard<std::recursive_mutex> lock(mutex_);
#endif
  auto dict_it = watch_map_.find(dict);
  // Something else in Cinderx could be watching this dict. Return early if no
  // matchers were registered.
  if (dict_it == watch_map_.end()) {
    return;
  }
  std::vector<GlobalCache> watched_caches;
  for (auto& [key, watchers] : dict_it->second) {
    watchers.appendTo(watched_caches);
  }

  std::vector<GlobalCache> to_disable;
  for (GlobalCache cache : watched_caches) {
    if (updateCache(cache, dict, nullptr)) {
      to_disable.emplace_back(cache);
    }
  }
  disableCaches(to_disable);
}

void GlobalCacheManager::notifyDictUnwatch(BorrowedRef<PyDictObject> dict) {
#ifdef Py_GIL_DISABLED
  std::lock_guard<std::recursive_mutex> lock(mutex_);
#endif
  auto dict_it = watch_map_.find(dict);
  // Something else in Cinderx could be watching this dict. Return early if no
  // matchers were registered.
  if (dict_it == watch_map_.end()) {
    return;
  }
  std::vector<GlobalCache> caches;
  for (auto& [key, watchers] : dict_it->second) {
    watchers.appendTo(caches);
  }

  for (auto cache : caches) {
    // Unsubscribe from the corresponding globals/builtins dict if needed.
    PyObject* globals = cache.key().globals;
    PyObject* builtins = cache.key().builtins;
    if (globals != builtins) {
      if (dict == globals) {
        // when shutting down builtins goes away and we won't be
        // watching builtins if the value we are watching was defined
        // globally at the module level but was never deleted.
        if (isWatchedDictKey(builtins, cache.key().name, cache)) {
          unwatchDictKey(builtins, cache.key().name, cache);
        }
      } else {
        unwatchDictKey(globals, cache.key().name, cache);
      }
    }

    disableCache(cache);
  }
  watch_map_.erase(dict);
}

void GlobalCacheManager::clear() {
  std::vector<PyObject*> keys;
#ifdef Py_GIL_DISABLED
  std::lock_guard<std::recursive_mutex> lock(mutex_);
#endif
  for (auto& pair : watch_map_) {
    keys.push_back(pair.first);
  }
  for (auto dict : keys) {
    auto dict_it = watch_map_.find(dict);
    // notifyDictUnwatch may clear out our dictionary and builtins,
    // so we need to make sure each dictionary is still being watched
    if (dict_it != watch_map_.end()) {
      notifyDictUnwatch(dict);
      cinderx::getModuleState()->watcher_state.unwatchDict(dict);
    }
  }
}

bool GlobalCacheManager::isWatchedDictKey(
    BorrowedRef<PyDictObject> dict,
    BorrowedRef<PyUnicodeObject> key,
    GlobalCache cache) {
  auto dict_it = watch_map_.find(dict);
  if (dict_it == watch_map_.end()) {
    return false;
  }
  auto key_it = dict_it->second.find(key);
  if (key_it == dict_it->second.end()) {
    return false;
  }
  return key_it->second.contains(cache);
}

void GlobalCacheManager::watchDictKey(
    BorrowedRef<PyDictObject> dict,
    BorrowedRef<PyUnicodeObject> key,
    GlobalCache cache) {
  auto [dict_it, inserted_dict] = watch_map_.try_emplace(dict);
  if (inserted_dict) {
    JIT_CHECK(
        cinderx::getModuleState()->watcher_state.watchDict(dict) == 0,
        "Failed to watch globals or builtins dict");
  }
  auto [key_it, inserted_key] = dict_it->second.try_emplace(key);
  if (inserted_key) {
    key_it->second.addUnchecked(cache);
    return;
  }
  bool inserted = !key_it->second.contains(cache);
  JIT_CHECK(inserted, "cache was already watching key");
  key_it->second.addUnchecked(cache);
}

void GlobalCacheManager::unwatchDictKey(
    BorrowedRef<PyDictObject> dict,
    BorrowedRef<PyUnicodeObject> key,
    GlobalCache cache) {
  auto dict_it = watch_map_.find(dict);
  JIT_CHECK(dict_it != watch_map_.end(), "dict has no watchers");
  auto key_it = dict_it->second.find(key);
  JIT_CHECK(key_it != dict_it->second.end(), "key has no watchers");
  key_it->second.remove(cache);
  if (key_it->second.empty()) {
    dict_it->second.erase(key_it);
    if (dict_it->second.empty()) {
      watch_map_.erase(dict_it);
      JIT_CHECK(
          cinderx::getModuleState()->watcher_state.unwatchDict(dict) == 0,
          "Failed to unwatch globals or builtins dictionary");
    }
  }
}

void GlobalCacheManager::initCache(GlobalCache cache) {
  cache.init(arena_.allocate());

  BorrowedRef<PyDictObject> globals = cache.key().globals;
  BorrowedRef<PyDictObject> builtins = cache.key().builtins;
  BorrowedRef<PyUnicodeObject> key = cache.key().name;

  JIT_DCHECK(
      hasOnlyUnicodeKeys(globals),
      "Should have already checked that globals dict was watchable");

  // We want to try and only watch builtins if this is really a builtin.  So we
  // will start only watching globals, and if the value gets deleted from
  // globals then we'll start tracking builtins as well.  Once we start tracking
  // builtins we'll never stop rather than trying to handle all of the
  // transitions.
  watchDictKey(globals, key, cache);

  // We don't need to immediately watch builtins if the value is found in
  // globals.
  if ([[maybe_unused]] PyObject* globals_value = PyDict_GetItem(globals, key)) {
    // The dict getitem could have triggered a lazy import with side effects
    // that unwatched the dict.
#ifdef ENABLE_LAZY_IMPORTS
    if (cache.valuePtr())
#endif
    {
      *cache.valuePtr() = globals_value;
    }
    return;
  }

  // The getitem on globals might have had side effects and made this dict
  // unwatchable, so it needs to be checked again.
  if (hasOnlyUnicodeKeys(builtins)) {
    *cache.valuePtr() = PyDict_GetItem(builtins, key);
    if (globals != builtins) {
      watchDictKey(builtins, key, cache);
    }
  }
}

bool GlobalCacheManager::updateCache(
    GlobalCache cache,
    BorrowedRef<PyDictObject> dict,
    BorrowedRef<> new_value) {
  if (new_value && PyLazyImport_CheckExact(new_value)) {
    return true;
  }

  BorrowedRef<PyDictObject> globals = cache.key().globals;
  BorrowedRef<PyDictObject> builtins = cache.key().builtins;
  BorrowedRef<PyUnicodeObject> name = cache.key().name;

  if (dict == globals) {
    if (new_value == nullptr && globals != builtins) {
      if (!hasOnlyUnicodeKeys(builtins)) {
        // builtins is no longer watchable. Mark this cache for disabling.
        return true;
      }

      // Fall back to the builtin (which may also be null).
      *cache.valuePtr() = PyDict_GetItem(builtins, name);

      // it changed, and it changed from something to nothing, so
      // we weren't watching builtins and need to start now.
      if (!isWatchedDictKey(builtins, name, cache)) {
        watchDictKey(builtins, name, cache);
      }
    } else {
      *cache.valuePtr() = new_value;
    }
  } else {
    JIT_CHECK(dict == builtins, "Unexpected dict");
    JIT_CHECK(hasOnlyUnicodeKeys(globals), "Bad globals dict");
    // Check if this value is shadowed.
    PyObject* globals_value = PyDict_GetItem(globals, name);
    if (globals_value == nullptr) {
      *cache.valuePtr() = new_value;
    }
  }

  return false;
}

void GlobalCacheManager::disableCache(GlobalCache cache) {
  cache.clear();
  map_.erase(cache.key());
}

void GlobalCacheManager::disableCaches(const std::vector<GlobalCache>& caches) {
  for (GlobalCache cache : caches) {
    BorrowedRef<PyDictObject> dict = cache.key().globals;
    BorrowedRef<PyUnicodeObject> name = cache.key().name;
    unwatchDictKey(dict, name, cache);
    disableCache(cache);
  }
}

} // namespace jit
