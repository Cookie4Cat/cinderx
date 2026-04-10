# Copyright (c) Meta Platforms, Inc. and affiliates.

import platform
import sys
import unittest

# This is just a quick test to see if CinderX works. It's intended purpose is
# for quick and basic validation of OSS builds.


class CinderXOSSTest(unittest.TestCase):
    def test_import(self) -> None:
        import cinderx  # noqa: F401

        if not cinderx.is_initialized():
            try:
                import _cinderx
            except Exception as e:
                print(f"Failed to import cinder: {e}")

        self.assertTrue(cinderx.is_initialized())

    def test_adaptive_static_python_enablement_state(self) -> None:
        import cinderx

        self.assertTrue(hasattr(cinderx, "is_adaptive_static_python_enabled"))
        enabled = cinderx.is_adaptive_static_python_enabled()
        self.assertIsInstance(enabled, bool)

        machine = platform.machine().lower()
        is_meta_312 = "+meta" in sys.version and sys.version_info[:2] == (3, 12)
        is_314_arm = sys.version_info[:2] == (3, 14) and machine in {"aarch64", "arm64"}
        expected = is_meta_312 or is_314_arm
        if hasattr(cinderx, "is_static_python_enabled") and not cinderx.is_static_python_enabled():
            expected = False
        self.assertEqual(
            enabled,
            expected,
            msg=(
                "Adaptive static python enablement mismatch for this runtime: "
                f"version={sys.version_info.major}.{sys.version_info.minor}, machine={machine}, "
                f"expected={expected}, actual={enabled}"
            ),
        )

    def test_lightweight_frames_enablement_state(self) -> None:
        import cinderx

        self.assertTrue(hasattr(cinderx, "is_lightweight_frames_enabled"))
        enabled = cinderx.is_lightweight_frames_enabled()
        self.assertIsInstance(enabled, bool)

        machine = platform.machine().lower()
        is_meta_312 = "+meta" in sys.version and sys.version_info[:2] == (3, 12)
        is_314_arm = sys.version_info[:2] == (3, 14) and machine in {"aarch64", "arm64"}
        expected = is_meta_312 or is_314_arm
        self.assertEqual(
            enabled,
            expected,
            msg=(
                "Lightweight frames enablement mismatch for this runtime: "
                f"version={sys.version_info.major}.{sys.version_info.minor}, machine={machine}, "
                f"expected={expected}, actual={enabled}"
            ),
        )

    def test_static_python_enablement_state(self) -> None:
        import cinderx

        self.assertTrue(hasattr(cinderx, "is_static_python_enabled"))
        enabled = cinderx.is_static_python_enabled()
        self.assertIsInstance(enabled, bool)

        # Adaptive static python must be disabled when static python core is
        # disabled at build time.
        if not enabled:
            self.assertFalse(cinderx.is_adaptive_static_python_enabled())


if __name__ == "__main__":
    unittest.main()
