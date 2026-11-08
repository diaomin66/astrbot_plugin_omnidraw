"""GIF request/response regressions using fake HTTP, without paid API calls."""

import base64
import importlib
import types
import unittest
from unittest.mock import patch

import test_custom_endpoint as fixtures


options_module = importlib.import_module(f"{fixtures.PACKAGE_NAME}.core.image_options")
normalize_gif_options = options_module.normalize_gif_options
provider_supports_gif = options_module.provider_supports_gif
GIF_BYTES = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAAUAAAAIf8LTkVUU0NBUEUyLjADAQAAACwAAAAAAQAB"
    "AAACAkQBADs="
)
GIF_B64 = base64.b64encode(GIF_BYTES).decode("ascii")
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"image-bytes" * 20


def provider_config(**overrides):
    settings = {
        "id": "gif-node",
        "api_type": "openai_image",
        "base_url": "https://example.com/v1",
        "api_keys": ["test-key"],
        "model": "gpt-image-2.6-flare",
        "timeout": 120.0,
        "default_size": "1536x1024",
    }
    settings.update(overrides)
    return fixtures.ProviderConfig(**settings)


def chain_config(providers):
    by_id = {provider.id: provider for provider in providers}
    return types.SimpleNamespace(
        chains={"text2img": list(by_id)}, get_provider=by_id.get,
    )


class SequenceSession(fixtures.FakeSession):
    def __init__(self, payloads):
        super().__init__(None)
        self.responses = iter(fixtures.FakeResponse(payload) for payload in payloads)

    def post(self, url, **kwargs):
        self.posts.append({"url": url, **kwargs})
        return fixtures.FakePost(next(self.responses))


class GifOptionsTest(unittest.TestCase):
    def test_static_requests_keep_all_values_and_are_not_mutated(self):
        original = {"quality": "hd", "aspect_ratio": "16:9", "frame_count": "99", "vendor": True}
        normalized = normalize_gif_options(original)
        self.assertEqual(normalized, original)
        self.assertIsNot(normalized, original)

    def test_default_gif_options(self):
        original = {"output_format": " GIF ", "vendor": "unchanged"}
        normalized = normalize_gif_options(original)
        self.assertEqual(normalized, {
            "output_format": "gif", "frame_count": 9, "frame_duration_ms": 200,
            "size": "auto", "vendor": "unchanged",
        })
        self.assertNotIn("size", original)

    def test_integer_strings_and_size_are_normalized(self):
        normalized = normalize_gif_options({
            "output_format": "gif", "frame_count": " 16 ", "frame_duration_ms": "205",
            "resolution": "512X512", "complexity": " MEDIUM ", "stream": "false", "partial_images": 0,
        })
        self.assertEqual(normalized["frame_count"], 16)
        self.assertEqual(normalized["frame_duration_ms"], 205)
        self.assertEqual(normalized["size"], "512x512")
        self.assertEqual(normalized["complexity"], "medium")
        for key in ("resolution", "stream", "partial_images"):
            self.assertNotIn(key, normalized)

    def test_invalid_integer_values_are_rejected(self):
        for key, values in {
            "frame_count": [True, False, 1, 17, 2.0, "2.0", "two", "", "-1"],
            "frame_duration_ms": [True, 19, 2001, 200.5, "nan", "200ms"],
        }.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, key):
                    normalize_gif_options({"output_format": "gif", key: value})

    def test_minimum_and_maximum_values_are_accepted(self):
        for frame_count, duration in ((2, 20), (16, 2000)):
            result = normalize_gif_options({
                "output_format": "gif", "frame_count": frame_count, "frame_duration_ms": duration,
            })
            self.assertEqual((result["frame_count"], result["frame_duration_ms"]), (frame_count, duration))

    def test_incompatible_gif_options_are_rejected(self):
        for key, value in [
            ("stream", True), ("stream", "true"), ("partial_images", "1"),
            ("mask", "a.png"), ("output_compression", 0), ("aspect_ratio", "16:9"),
            ("complexity", "max"), ("size", "1023x1024"), ("size", "0x16"), ("size", "2k"),
        ]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                normalize_gif_options({"output_format": "gif", key: value})

    def test_supported_models_and_endpoint_types(self):
        for model in ("gpt-image-2.6-flare", "gpt-image-2.6-sunburst", "gpt-image-2.6-flare-2026-11-08"):
            self.assertTrue(provider_supports_gif(provider_config(model=model)))
        for model in ("gpt-image-2.6", "gpt-image-2.5-flare", "gpt-image-2.60-flare", "gpt-image-2.6-flare-custom"):
            self.assertFalse(provider_supports_gif(provider_config(model=model)))
        for api_type in ("openai_chat", "gemini_official", "unknown"):
            self.assertFalse(provider_supports_gif(provider_config(api_type=api_type)))
        for suffix in ("images/generations", "images/edits"):
            self.assertTrue(provider_supports_gif(provider_config(
                api_type="custom_endpoint", base_url=f"https://example.com/v1/{suffix}?route=1",
            )))
        self.assertFalse(provider_supports_gif(provider_config(
            api_type="custom_endpoint", base_url="https://example.com/v1/responses",
        )))

    def test_original_chain_metadata_construction_remains_valid(self):
        result = fixtures.ChainRunResult("https://example.com/image.png", "node", "model", 1.0)
        self.assertEqual(result.output_format, "")


class GifResponseTest(unittest.TestCase):
    def test_b64_uses_actual_gif_mime(self):
        result = fixtures.extract_image_url_from_response({"data": [{"b64_json": GIF_B64}]}, "https://example.com")
        self.assertEqual(result, "data:image/gif;base64," + GIF_B64)

    def test_short_gif_is_not_discarded_by_old_base64_length_heuristic(self):
        short = base64.b64encode(b"GIF89a" + b"\0" * 20).decode("ascii")
        result = fixtures.extract_image_url_from_response({"data": [{"b64_json": short}]}, "https://example.com")
        self.assertEqual(result, "data:image/gif;base64," + short)

    def test_existing_png_extraction_is_unchanged(self):
        png = base64.b64encode(PNG_BYTES).decode("ascii")
        result = fixtures.extract_image_url_from_response({"data": [{"b64_json": png}]}, "https://example.com")
        self.assertEqual(result, "data:image/png;base64," + png)

    def test_inline_gif_mime_is_corrected_without_reencoding(self):
        self.assertEqual(
            fixtures.base_module.validate_gif_result("data:image/png;base64," + GIF_B64),
            "data:image/gif;base64," + GIF_B64,
        )

    def test_static_or_invalid_inline_gif_is_rejected(self):
        for value in (
            "data:image/gif;base64," + base64.b64encode(PNG_BYTES).decode("ascii"),
            "data:image/gif;base64,broken!", "data:image/gif,bytes", "file:///tmp/image.gif",
        ):
            with self.subTest(value=value[:60]), self.assertRaises(ValueError):
                fixtures.base_module.validate_gif_result(value)

    def test_gif_output_byte_limit(self):
        with patch.object(fixtures.base_module, "MAX_IMAGE_BYTES", len(GIF_BYTES) - 1):
            with self.assertRaisesRegex(ValueError, "20 MiB"):
                fixtures.base_module.validate_gif_result("data:image/gif;base64," + GIF_B64)

    def test_inline_size_limit_precedes_base64_decode(self):
        with patch.object(fixtures.base_module.base64, "b64decode", side_effect=AssertionError("must not decode")):
            with self.assertRaisesRegex(ValueError, "MiB"):
                fixtures.extract_image_url_from_response(
                    {"data": [{"b64_json": GIF_B64}]}, "https://example.com", max_inline_bytes=8,
                )

    def test_remote_url_is_left_for_checked_download(self):
        url = "https://example.com/output?signature=abc"
        self.assertEqual(fixtures.base_module.validate_gif_result(url), url)


class GifProviderTest(unittest.IsolatedAsyncioTestCase):
    async def test_generation_json_and_result(self):
        session = fixtures.FakeSession(fixtures.FakeResponse({"data": [{"b64_json": GIF_B64}]}))
        result = await fixtures.OpenAIProvider(provider_config(), session).generate_image(
            "A dog waves in a seamless loop", output_format="gif", frame_count="6", frame_duration_ms="150",
            complexity="low", vendor_option="keep",
        )
        self.assertTrue(result.startswith("data:image/gif;base64,"))
        self.assertEqual(session.posts[0]["url"], "https://example.com/v1/images/generations")
        payload = session.posts[0]["json"]
        self.assertEqual(payload["n"], 1)
        self.assertEqual(payload["frame_count"], 6)
        self.assertEqual(payload["frame_duration_ms"], 150)
        self.assertEqual(payload["size"], "auto")
        self.assertEqual(payload["vendor_option"], "keep")

    async def test_reference_gif_uses_edits_even_with_explicit_generation_url(self):
        session = fixtures.FakeSession(fixtures.FakeResponse({"data": [{"b64_json": GIF_B64}]}))
        config = provider_config(base_url="https://example.com/v1/images/generations?route=1")
        reference = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")
        await fixtures.OpenAIProvider(config, session).generate_image(
            "Make this dog wave", output_format="gif", user_refs=[reference], frame_count="8",
        )
        self.assertEqual(session.posts[0]["url"], "https://example.com/v1/images/edits?route=1")
        fields = {field[0]["name"]: field[2] for field in session.posts[0]["data"]._fields}
        self.assertEqual(fields["output_format"], "gif")
        self.assertEqual(fields["frame_count"], "8")
        self.assertEqual(fields["image[]"], PNG_BYTES)

    async def test_static_reference_generation_endpoint_keeps_legacy_json(self):
        session = fixtures.FakeSession(fixtures.FakeResponse({"data": [{"url": "https://example.com/static.png"}]}))
        config = provider_config(base_url="https://example.com/v1/images/generations")
        reference = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")
        await fixtures.OpenAIProvider(config, session).generate_image("A dog", user_refs=[reference])
        self.assertEqual(session.posts[0]["url"], config.base_url)
        self.assertIn("image", session.posts[0]["json"])
        self.assertNotIn("output_format", session.posts[0]["json"])

    async def test_direct_provider_rejects_unsupported_model_without_post(self):
        session = fixtures.FakeSession(None)
        with self.assertRaisesRegex(ValueError, "gpt-image-2.6"):
            await fixtures.OpenAIProvider(provider_config(model="gpt-image-1.5"), session).generate_image(
                "A dog", output_format="gif", model="gpt-image-2.6-flare",
            )
        self.assertEqual(session.posts, [])

    async def test_custom_edits_preserve_exact_endpoint(self):
        session = fixtures.FakeSession(fixtures.FakeResponse({"data": [{"b64_json": GIF_B64}]}))
        config = provider_config(api_type="custom_endpoint", base_url="https://example.com/custom/images/edits?key=1")
        reference = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")
        await fixtures.CustomEndpointProvider(config, session).generate_image(
            "Wave", output_format="gif", user_ref=reference,
        )
        self.assertEqual(session.posts[0]["url"], config.base_url)
        fields = {field[0]["name"]: field[2] for field in session.posts[0]["data"]._fields}
        self.assertEqual(fields["output_format"], "gif")

    async def test_custom_generation_with_references_requires_edit_configuration(self):
        session = fixtures.FakeSession(None)
        config = provider_config(api_type="custom_endpoint", base_url="https://example.com/v1/images/generations")
        with self.assertRaisesRegex(ValueError, "/images/edits"):
            await fixtures.CustomEndpointProvider(config, session).generate_image(
                "Wave", output_format="gif", user_ref="https://example.com/ref.png",
            )
        self.assertEqual(session.posts, [])
        self.assertEqual(session.gets, [])

    async def test_custom_generation_without_references_accepts_gif(self):
        session = fixtures.FakeSession(fixtures.FakeResponse({"data": [{"b64_json": GIF_B64}]}))
        config = provider_config(api_type="custom_endpoint", base_url="https://example.com/v1/images/generations")
        result = await fixtures.CustomEndpointProvider(config, session).generate_image("Wave", output_format="gif")
        self.assertTrue(result.startswith("data:image/gif;base64,"))


class GifChainTest(unittest.IsolatedAsyncioTestCase):
    async def test_skips_static_nodes_and_ignores_static_default_size(self):
        providers = [provider_config(id="old", model="gpt-image-1.5"), provider_config(id="gif")]
        session = fixtures.FakeSession(fixtures.FakeResponse({"data": [{"b64_json": GIF_B64}]}))
        result = await fixtures.ChainManager(chain_config(providers), session).run_chain_with_metadata(
            "text2img", "Wave", output_format="gif",
        )
        self.assertEqual(len(session.posts), 1)
        self.assertEqual(result.provider_id, "gif")
        self.assertEqual(result.output_format, "gif")
        self.assertEqual(session.posts[0]["json"]["size"], "auto")

    async def test_static_chain_preserves_node_default_size(self):
        providers = [provider_config()]
        session = fixtures.FakeSession(fixtures.FakeResponse({"data": [{"url": "https://example.com/image.png"}]}))
        result = await fixtures.ChainManager(chain_config(providers), session).run_chain_with_metadata("text2img", "Still")
        self.assertEqual(session.posts[0]["json"]["size"], "1536x1024")
        self.assertNotIn("output_format", session.posts[0]["json"])
        self.assertEqual(result.output_format, "")

    async def test_no_gif_node_does_not_fall_back_to_static(self):
        session = fixtures.FakeSession(None)
        config = chain_config([provider_config(model="gpt-image-1.5")])
        with self.assertRaisesRegex(RuntimeError, "GIF"):
            await fixtures.ChainManager(config, session).run_chain("text2img", "Wave", output_format="gif")
        self.assertEqual(session.posts, [])

    async def test_gif_metadata_uses_model_actually_sent_not_filtered_override(self):
        session = fixtures.FakeSession(fixtures.FakeResponse({"data": [{"b64_json": GIF_B64}]}))
        config = chain_config([provider_config()])
        result = await fixtures.ChainManager(config, session).run_chain_with_metadata(
            "text2img", "Wave", output_format="gif", model="gpt-image-1.5",
        )
        self.assertEqual(result.model, "gpt-image-2.6-flare")
        self.assertEqual(session.posts[0]["json"]["model"], result.model)

    async def test_static_inline_result_tries_next_gif_provider(self):
        providers = [provider_config(id="first"), provider_config(id="next", model="gpt-image-2.6-sunburst")]
        session = SequenceSession([
            {"data": [{"b64_json": base64.b64encode(PNG_BYTES).decode("ascii")}]},
            {"data": [{"b64_json": GIF_B64}]},
        ])
        result = await fixtures.ChainManager(chain_config(providers), session).run_chain_with_metadata(
            "text2img", "Wave", output_format="gif", size="512x512",
        )
        self.assertEqual(result.provider_id, "next")
        self.assertEqual(len(session.posts), 2)
        self.assertTrue(all(post["json"]["size"] == "512x512" for post in session.posts))

    async def test_invalid_gif_parameters_fail_before_any_provider(self):
        session = fixtures.FakeSession(None)
        config = chain_config([provider_config()])
        with self.assertRaisesRegex(ValueError, "frame_count"):
            await fixtures.ChainManager(config, session).run_chain("text2img", "Wave", output_format="gif", frame_count=17)
        self.assertEqual(session.posts, [])
