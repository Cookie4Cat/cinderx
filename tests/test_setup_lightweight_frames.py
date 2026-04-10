import unittest

import setup


class LightweightFramesDefaultTests(unittest.TestCase):
    def test_enable_for_314_aarch64(self) -> None:
        self.assertTrue(
            setup.should_enable_lightweight_frames(
                py_version="3.14",
                meta_python=False,
                machine="aarch64",
            )
        )

    def test_enable_for_314_arm64(self) -> None:
        self.assertTrue(
            setup.should_enable_lightweight_frames(
                py_version="3.14",
                meta_python=False,
                machine="arm64",
            )
        )

    def test_disable_for_314_x86_64(self) -> None:
        self.assertFalse(
            setup.should_enable_lightweight_frames(
                py_version="3.14",
                meta_python=False,
                machine="x86_64",
            )
        )

    def test_disable_for_315_arm64_in_stage_a(self) -> None:
        self.assertFalse(
            setup.should_enable_lightweight_frames(
                py_version="3.15",
                meta_python=False,
                machine="arm64",
            )
        )

    def test_enable_for_meta_312(self) -> None:
        self.assertTrue(
            setup.should_enable_lightweight_frames(
                py_version="3.12",
                meta_python=True,
                machine="x86_64",
            )
        )


if __name__ == "__main__":
    unittest.main()
