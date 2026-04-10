import unittest

import cinderx


class LightweightFramesApiTests(unittest.TestCase):
    def test_api_is_exported(self) -> None:
        self.assertTrue(hasattr(cinderx, "is_lightweight_frames_enabled"))

    def test_api_returns_bool(self) -> None:
        self.assertIsInstance(cinderx.is_lightweight_frames_enabled(), bool)


if __name__ == "__main__":
    unittest.main()
