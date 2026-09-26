"""aspect_ratio → size 静默换算的单元测试。"""

import importlib
import sys
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR.parent))

constants = importlib.import_module(f"{PLUGIN_DIR.name}.constants")


class AspectRatioToSizeTests(unittest.TestCase):
    def test_common_ratios(self):
        self.assertEqual(constants.aspect_ratio_to_size("1:1"), "1024x1024")
        self.assertEqual(constants.aspect_ratio_to_size("16:9"), "1536x864")
        self.assertEqual(constants.aspect_ratio_to_size("9:16"), "864x1536")

    def test_full_width_colon_and_spaces(self):
        self.assertEqual(constants.aspect_ratio_to_size(" 16：9 "), "1536x864")
        self.assertEqual(constants.aspect_ratio_to_size("4:3"), "1536x1152")

    def test_unknown_or_empty_ratio_returns_empty(self):
        self.assertEqual(constants.aspect_ratio_to_size("5:4"), "")
        self.assertEqual(constants.aspect_ratio_to_size(""), "")
        self.assertEqual(constants.aspect_ratio_to_size(None), "")

    def test_all_sizes_are_multiples_of_16(self):
        for ratio, size in constants.ASPECT_RATIO_TO_SIZE.items():
            width, _, height = size.partition("x")
            with self.subTest(ratio=ratio):
                self.assertEqual(int(width) % 16, 0)
                self.assertEqual(int(height) % 16, 0)


if __name__ == "__main__":
    unittest.main()
