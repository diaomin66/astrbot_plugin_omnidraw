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
        self.assertEqual(constants.aspect_ratio_to_size("1:1", "gpt-image-2"), "1024x1024")
        self.assertEqual(constants.aspect_ratio_to_size("16:9", "gpt-image-2"), "1536x864")
        self.assertEqual(constants.aspect_ratio_to_size("9:16", "gpt-image-2"), "864x1536")

    def test_full_width_colon_and_spaces(self):
        self.assertEqual(constants.aspect_ratio_to_size(" 16：9 ", "gpt-image-2"), "1536x864")
        self.assertEqual(constants.aspect_ratio_to_size("4:3", "gpt-image-2"), "1536x1152")

    def test_unknown_or_empty_ratio_returns_empty(self):
        for model in ("gpt-image-1", "gpt-image-2"):
            for ratio in ("5:4", "", None):
                with self.subTest(model=model, ratio=ratio):
                    self.assertEqual(constants.aspect_ratio_to_size(ratio, model), "")

    def test_fixed_size_models_use_supported_landscape_portrait_and_square(self):
        for model in (
            "gpt-image-1", "gpt-image-1-mini", "gpt-image-1.5",
            "gpt-image-1.5-2025-12-16",
        ):
            for ratio, expected in (
                ("1:1", "1024x1024"),
                ("4:3", "1536x1024"), ("3:4", "1024x1536"),
                ("3:2", "1536x1024"), ("2:3", "1024x1536"),
                ("16:9", "1536x1024"), ("9:16", "1024x1536"),
                ("21:9", "1536x1024"), ("9:21", "1024x1536"),
            ):
                with self.subTest(model=model, ratio=ratio):
                    self.assertEqual(constants.aspect_ratio_to_size(ratio, model), expected)

    def test_custom_size_models_and_snapshots_preserve_ratio(self):
        for model in (
            "gpt-image-2", "gpt-image-2-2026-04-21",
            "gpt-image-2.5-sunburst", "gpt-image-2.5-sunburst-2026-09-08",
            "gpt-image-2.5-flare", "gpt-image-2.5-flare-2026-09-08",
        ):
            with self.subTest(model=model):
                self.assertEqual(constants.aspect_ratio_to_size("16:9", model), "1536x864")

    def test_unknown_model_does_not_assume_custom_size_support(self):
        for model in ("", None, "gemini-3.1-flash-image", "custom-model", "gpt-image-2-custom"):
            with self.subTest(model=model):
                self.assertEqual(constants.aspect_ratio_to_size("16:9", model), "")

    def test_model_name_whitespace_and_case(self):
        self.assertEqual(constants.aspect_ratio_to_size("16:9", " GPT-IMAGE-1 "), "1536x1024")

    def test_all_sizes_are_multiples_of_16(self):
        for ratio, size in constants.ASPECT_RATIO_TO_SIZE.items():
            width, _, height = size.partition("x")
            with self.subTest(ratio=ratio):
                self.assertEqual(int(width) % 16, 0)
                self.assertEqual(int(height) % 16, 0)
                self.assertLessEqual(max(int(width), int(height)), 3840)
                self.assertLessEqual(max(int(width), int(height)) / min(int(width), int(height)), 3)
                self.assertGreaterEqual(int(width) * int(height), 655360)
                self.assertLessEqual(int(width) * int(height), 8294400)


if __name__ == "__main__":
    unittest.main()
