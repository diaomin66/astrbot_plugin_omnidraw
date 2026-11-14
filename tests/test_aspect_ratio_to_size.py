"""Issue #65 regressions: OpenAI image channel must never send aspect_ratio.

The OpenAI standard Images API rejects `aspect_ratio` with
`Unknown parameter: 'aspect_ratio'`. The plugin converts it to `size`
(long side 1024, both sides multiples of 16) for the OpenAI channel only.
"""

import unittest
from pathlib import Path

import test_custom_endpoint as fixtures


PLUGIN_DIR = Path(__file__).resolve().parents[1]
base_module = fixtures.base_module
aspect_ratio_to_size = base_module.aspect_ratio_to_size
convert = base_module.convert_openai_image_size_kwargs
filter_kwargs = base_module.filter_provider_api_kwargs


class AspectRatioToSizeTest(unittest.TestCase):
    def test_conversion_table(self):
        cases = {
            "1:1": "1024x1024",
            "16:9": "1024x576",
            "9:16": "576x1024",
            "3:4": "768x1024",
            "4:3": "1024x768",
            "3:2": "1024x688",
            "2:3": "688x1024",
            "21:9": "1024x432",
        }
        for ratio, expected in cases.items():
            with self.subTest(ratio=ratio):
                self.assertEqual(aspect_ratio_to_size(ratio), expected)

    def test_alternate_spellings(self):
        self.assertEqual(aspect_ratio_to_size("16/9"), "1024x576")
        self.assertEqual(aspect_ratio_to_size(" 16 : 9 "), "1024x576")
        self.assertEqual(aspect_ratio_to_size("1.78"), "1024x576")
        self.assertEqual(aspect_ratio_to_size(2), "1024x512")

    def test_extreme_ratios_clamp_to_minimum_side(self):
        self.assertEqual(aspect_ratio_to_size("1000:1"), "1024x16")
        self.assertEqual(aspect_ratio_to_size("1:1000"), "16x1024")

    def test_invalid_ratios_return_empty(self):
        for bad in ("", None, "bogus", "0:9", "9:0", "-16:9", "16:9:30", ":", "0", "16:"):
            with self.subTest(bad=bad):
                self.assertEqual(aspect_ratio_to_size(bad), "")

    def test_output_invariants_over_many_ratios(self):
        for w in range(1, 33):
            for h in range(1, 33):
                size = aspect_ratio_to_size(f"{w}:{h}")
                width, height = (int(part) for part in size.split("x"))
                self.assertEqual(max(width, height), 1024)
                self.assertEqual(width % 16, 0)
                self.assertEqual(height % 16, 0)
                # The non-long side is the ideal side rounded to a
                # multiple of 16, so it is never more than 8px off.
                if w >= h:
                    self.assertLessEqual(abs(height - 1024 * h / w), 8)
                else:
                    self.assertLessEqual(abs(width - 1024 * w / h), 8)


class ConvertOpenAIImageSizeKwargsTest(unittest.TestCase):
    def test_no_aspect_ratio_passthrough(self):
        self.assertEqual(convert({}), {})
        original = {"size": "800x800", "quality": "hd"}
        result = convert(original)
        self.assertEqual(result, original)
        self.assertIsNot(result, original)

    def test_ratio_only_is_converted(self):
        self.assertEqual(convert({"aspect_ratio": "16:9"}), {"size": "1024x576"})
        self.assertEqual(
            convert({"aspect_ratio": "9:16", "quality": "hd"}),
            {"size": "576x1024", "quality": "hd"},
        )

    def test_explicit_size_wins(self):
        self.assertEqual(
            convert({"aspect_ratio": "16:9", "size": "512x512"}),
            {"size": "512x512"},
        )

    def test_auto_or_empty_size_is_replaced_by_conversion(self):
        self.assertEqual(
            convert({"aspect_ratio": "16:9", "size": "auto"}),
            {"size": "1024x576"},
        )
        self.assertEqual(
            convert({"aspect_ratio": "16:9", "size": ""}),
            {"size": "1024x576"},
        )

    def test_invalid_ratio_is_dropped_never_sent(self):
        self.assertEqual(convert({"aspect_ratio": "bogus"}), {})
        self.assertEqual(convert({"aspect_ratio": ""}), {})

    def test_key_matching_is_case_insensitive(self):
        self.assertEqual(convert({"Aspect_Ratio": "9:16"}), {"size": "576x1024"})

    def test_size_case_variant_is_normalized_when_converting(self):
        self.assertEqual(
            convert({"aspect_ratio": "16:9", "Size": "auto"}),
            {"size": "1024x576"},
        )
        self.assertEqual(
            convert({"aspect_ratio": "16:9", "Size": "512x512"}),
            {"size": "512x512"},
        )

    def test_duplicate_case_variants_are_all_dropped(self):
        # Found by fuzzing: two case variants can coexist as dict keys,
        # and a leftover one would still be rejected by OpenAI.
        result = convert({"aspect_ratio": "16:9", "Aspect_Ratio": "9:16"})
        self.assertEqual(result, {"size": "1024x576"})

    def test_input_dict_is_not_mutated(self):
        original = {"aspect_ratio": "16:9"}
        convert(original)
        self.assertEqual(original, {"aspect_ratio": "16:9"})

    def test_result_never_contains_aspect_ratio(self):
        samples = [
            {"aspect_ratio": "16:9"},
            {"aspect_ratio": "bogus", "size": "auto"},
            {"ASPECT_RATIO": "1:1", "size": "100x100"},
            {"quality": "hd"},
        ]
        for sample in samples:
            result = convert(sample)
            self.assertFalse(
                any(str(key).casefold() == "aspect_ratio" for key in result),
                f"aspect_ratio leaked in {result!r}",
            )


class OpenAIChannelPipelineTest(unittest.TestCase):
    """Mirror OpenAIProvider.generate_image: filter, then convert."""

    def test_filtered_kwargs_reaching_payload_have_no_aspect_ratio(self):
        api_kwargs = filter_kwargs({"aspect_ratio": "3:4", "quality": "hd"})
        api_kwargs = convert(api_kwargs, "test-node")
        self.assertEqual(api_kwargs, {"quality": "hd", "size": "768x1024"})

    def test_openai_impl_source_hooks_conversion_before_payload_update(self):
        source = (PLUGIN_DIR / "providers" / "openai_impl.py").read_text(encoding="utf-8")
        hook = source.index("convert_openai_image_size_kwargs(api_kwargs")
        first_payload_update = source.index("payload.update(api_kwargs)")
        self.assertLess(hook, first_payload_update)


if __name__ == "__main__":
    unittest.main()
