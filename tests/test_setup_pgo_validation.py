import tempfile
import unittest
from pathlib import Path

import setup


class _DummyCinderXModule:
    def __init__(
        self,
        *,
        import_error: Exception | None = None,
        initialized: bool = True,
    ) -> None:
        self._import_error = import_error
        self._initialized = initialized

    def get_import_error(self) -> Exception | None:
        return self._import_error

    def is_initialized(self) -> bool:
        return self._initialized


class PgoRuntimeValidationTests(unittest.TestCase):
    def test_accepts_initialized_runtime(self) -> None:
        setup.validate_pgo_runtime(_DummyCinderXModule())

    def test_rejects_import_error(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "failed to import",
        ):
            setup.validate_pgo_runtime(
                _DummyCinderXModule(import_error=ImportError("boom"))
            )

    def test_rejects_uninitialized_runtime(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "did not initialize",
        ):
            setup.validate_pgo_runtime(_DummyCinderXModule(initialized=False))


class GccPgoProfileAuditTests(unittest.TestCase):
    def test_collects_profile_counts_for_required_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for target, relative_dir in setup.GCC_PGO_REQUIRED_TARGETS.items():
                target_dir = tmp_path / relative_dir
                target_dir.mkdir(parents=True, exist_ok=True)
                (target_dir / f"{target}.gcda").write_text("", encoding="utf-8")

            counts = setup.collect_gcc_pgo_profile_counts(tmp)

        self.assertEqual(counts, {"_cinderx": 1, "interpreter": 1, "jit": 1})
        setup.require_gcc_pgo_profiles(tmp, counts)

    def test_rejects_when_required_target_has_no_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for target, relative_dir in setup.GCC_PGO_REQUIRED_TARGETS.items():
                if target == "jit":
                    continue
                target_dir = tmp_path / relative_dir
                target_dir.mkdir(parents=True, exist_ok=True)
                (target_dir / f"{target}.gcda").write_text("", encoding="utf-8")

            counts = setup.collect_gcc_pgo_profile_counts(tmp)

            with self.assertRaisesRegex(RuntimeError, "jit"):
                setup.require_gcc_pgo_profiles(tmp, counts)

    def test_allows_missing_first_party_object_profiles_when_required_targets_exist(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            for target, relative_dir in setup.GCC_PGO_REQUIRED_TARGETS.items():
                target_dir = tmp_path / relative_dir
                target_dir.mkdir(parents=True, exist_ok=True)
                (target_dir / f"{target}.gcda").write_text("", encoding="utf-8")

            static_python_dir = (
                tmp_path / setup.GCC_PGO_AUDITED_TARGETS["static-python"]
            )
            static_python_dir.mkdir(parents=True, exist_ok=True)
            (static_python_dir / "descrobject_vectorcall.c.o").write_text(
                "",
                encoding="utf-8",
            )

            counts = setup.collect_gcc_pgo_profile_counts(tmp)
            missing_profiles = setup.collect_gcc_pgo_missing_profile_files(
                tmp,
                {"static-python": setup.GCC_PGO_AUDITED_TARGETS["static-python"]},
            )

            self.assertIn("static-python", missing_profiles)
            setup.require_gcc_pgo_profiles(tmp, counts)

    def test_ignores_non_arm_jit_and_dummy_parallel_gc_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            x86_dir = tmp_path / setup.GCC_PGO_AUDITED_TARGETS["jit"] / "cinderx/Jit/codegen/arch"
            x86_dir.mkdir(parents=True, exist_ok=True)
            (x86_dir / "x86_64.cpp.o").write_text("", encoding="utf-8")
            (x86_dir / "unknown.cpp.o").write_text("", encoding="utf-8")

            dummy_parallel_gc_dir = tmp_path / setup.GCC_PGO_AUDITED_TARGETS["parallel-gc"] / "generated"
            dummy_parallel_gc_dir.mkdir(parents=True, exist_ok=True)
            (dummy_parallel_gc_dir / "dummy-parallel-gc.c.o").write_text(
                "",
                encoding="utf-8",
            )

            missing_profiles = setup.collect_gcc_pgo_missing_profile_files(
                tmp,
                {
                    "jit": setup.GCC_PGO_AUDITED_TARGETS["jit"],
                    "parallel-gc": setup.GCC_PGO_AUDITED_TARGETS["parallel-gc"],
                },
            )

        self.assertEqual(missing_profiles, {})


if __name__ == "__main__":
    unittest.main()
