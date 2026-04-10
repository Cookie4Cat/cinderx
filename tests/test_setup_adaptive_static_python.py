import unittest
from unittest.mock import patch

import setup


class AdaptiveStaticDefaultTests(unittest.TestCase):
    def test_enable_for_314_aarch64(self) -> None:
        self.assertTrue(
            setup.should_enable_adaptive_static_python(
                py_version="3.14",
                meta_python=False,
                machine="aarch64",
            )
        )

    def test_enable_for_314_arm64(self) -> None:
        self.assertTrue(
            setup.should_enable_adaptive_static_python(
                py_version="3.14",
                meta_python=False,
                machine="arm64",
            )
        )

    def test_disable_for_314_x86_64(self) -> None:
        self.assertFalse(
            setup.should_enable_adaptive_static_python(
                py_version="3.14",
                meta_python=False,
                machine="x86_64",
            )
        )

    def test_enable_for_meta_312(self) -> None:
        self.assertTrue(
            setup.should_enable_adaptive_static_python(
                py_version="3.12",
                meta_python=True,
                machine="x86_64",
            )
        )

    def test_disable_for_315_arm64(self) -> None:
        self.assertFalse(
            setup.should_enable_adaptive_static_python(
                py_version="3.15",
                meta_python=False,
                machine="arm64",
            )
        )


class BuildEnvFlagTests(unittest.TestCase):
    def test_env_flag_unset_uses_default(self) -> None:
        with patch.dict(setup.os.environ, {}, clear=True):
            self.assertFalse(setup.is_env_flag_enabled("CINDERX_ENABLE_LTO"))
            self.assertTrue(
                setup.is_env_flag_enabled("CINDERX_ENABLE_LTO", default=True)
            )

    def test_env_flag_false_values_disable(self) -> None:
        false_values = ["0", "false", "off", "no", ""]
        for value in false_values:
            with self.subTest(value=value):
                with patch.dict(
                    setup.os.environ,
                    {"CINDERX_ENABLE_LTO": value},
                    clear=True,
                ):
                    self.assertFalse(setup.is_env_flag_enabled("CINDERX_ENABLE_LTO"))

    def test_env_flag_true_values_enable(self) -> None:
        true_values = ["1", "true", "on", "yes", "anything-else"]
        for value in true_values:
            with self.subTest(value=value):
                with patch.dict(
                    setup.os.environ,
                    {"CINDERX_ENABLE_LTO": value},
                    clear=True,
                ):
                    self.assertTrue(setup.is_env_flag_enabled("CINDERX_ENABLE_LTO"))


if __name__ == "__main__":
    unittest.main()
