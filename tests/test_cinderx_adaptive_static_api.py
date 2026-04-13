import unittest

import cinderx


class AdaptiveStaticApiTests(unittest.TestCase):
    def test_api_is_exported(self) -> None:
        self.assertTrue(hasattr(cinderx, "is_adaptive_static_python_enabled"))

    def test_api_returns_bool(self) -> None:
        self.assertIsInstance(cinderx.is_adaptive_static_python_enabled(), bool)


if __name__ == "__main__":
    unittest.main()
