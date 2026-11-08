"""Gemini proxy endpoint regressions; all HTTP requests use in-memory fakes."""

import base64
import types
import unittest
from urllib.parse import urlparse

import test_custom_endpoint as fixtures


MODEL = "gemini-3.1-flash-image"
DEFAULT_ROOT = "https://generativelanguage.googleapis.com/v1beta"
IMAGE_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"test-image" * 20).decode("ascii")
GIF_B64 = "R0lGODlhAQABAIAAAAAAAP///yH5BAAUAAAAIf8LTkVUU0NBUEUyLjADAQAAACwAAAAAAQABAAACAkQBADs="


def provider_config(**overrides):
    values = {
        "id": "gemini-proxy",
        "api_type": "gemini_official",
        "base_url": "https://relay.example/v1beta",
        "api_keys": ["fake-gemini-key"],
        "model": MODEL,
        "timeout": 120.0,
    }
    values.update(overrides)
    return fixtures.ProviderConfig(**values)


def image_response():
    return {"candidates": [{"content": {"parts": [
        {"inlineData": {"mimeType": "image/png", "data": IMAGE_B64}},
    ]}, "finishReason": "STOP"}]}


def chain_config(providers):
    by_id = {provider.id: provider for provider in providers}
    return types.SimpleNamespace(chains={"text2img": list(by_id)}, get_provider=by_id.get)


class GeminiEndpointTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.fake_logger.messages.clear()

    def make_provider(self, *, status=200, response=None, **overrides):
        session = fixtures.FakeSession(fixtures.FakeResponse(
            image_response() if response is None else response, status=status,
        ))
        return fixtures.GeminiOfficialProvider(provider_config(**overrides), session), session

    async def test_only_empty_addresses_use_the_google_default(self):
        for base_url in ("", " \t ", None):
            with self.subTest(base_url=base_url):
                provider, session = self.make_provider(base_url=base_url)
                await provider.generate_image("draw a cat")
                self.assertEqual(session.posts[0]["url"], f"{DEFAULT_ROOT}/models/{MODEL}:generateContent")

    async def test_root_addresses_add_default_api_version_on_the_same_host(self):
        for base_url in (
            "https://relay.example", "https://relay.example/",
            "http://relay.example:8080", "https://[2001:db8::1]:8443/",
        ):
            with self.subTest(base_url=base_url):
                provider, session = self.make_provider(base_url=base_url)
                await provider.generate_image("draw a cat")
                self.assertEqual(session.posts[0]["url"], f"{base_url.rstrip('/')}/v1beta/models/{MODEL}:generateContent")

    async def test_explicit_versions_prefixes_and_models_collections_are_preserved(self):
        for path, expected_prefix in (
            ("/v1", "/v1"),
            ("/v1beta", "/v1beta"),
            ("/v1beta1/", "/v1beta1"),
            ("/gateway", "/gateway"),
            ("/gateway/v1", "/gateway/v1"),
            ("/gateway/v1beta", "/gateway/v1beta"),
            ("/models", ""),
            ("/v1beta/models/", "/v1beta"),
            ("/gateway/v1beta/models", "/gateway/v1beta"),
        ):
            with self.subTest(path=path):
                provider, session = self.make_provider(base_url="https://relay.example" + path)
                await provider.generate_image("draw a cat")
                self.assertEqual(
                    session.posts[0]["url"], f"https://relay.example{expected_prefix}/models/{MODEL}:generateContent",
                )

    async def test_models_segment_inside_a_gateway_prefix_is_not_a_model_resource(self):
        for path in ("/gateway/models/tenant/v1beta", "/models/tenant/router", "/proxy/models/team/v1beta/models"):
            with self.subTest(path=path):
                provider, session = self.make_provider(base_url="https://relay.example" + path)
                await provider.generate_image("draw a cat")
                prefix = path[:-len("/models")] if path.endswith("/models") else path
                self.assertEqual(
                    session.posts[0]["url"], f"https://relay.example{prefix}/models/{MODEL}:generateContent",
                )

    async def test_explicit_model_resources_keep_the_pinned_model(self):
        for path in ("/models/pinned-model", "/v1/models/pinned-model", "/gateway/v1beta/models/pinned-model/"):
            with self.subTest(path=path):
                provider, session = self.make_provider(base_url="https://relay.example" + path)
                await provider.generate_image("draw a cat", model="ignored-override")
                self.assertEqual(session.posts[0]["url"], "https://relay.example" + path.rstrip("/") + ":generateContent")
                self.assertNotIn("model", session.posts[0]["json"])

    async def test_full_generate_content_endpoints_are_never_rewritten(self):
        for endpoint in (
            "https://relay.example/v1beta/models/pinned:generateContent",
            "https://relay.example/gateway/v1/models/pinned:generateContent?route=a%2Fb&key=fake%2Bkey",
            "https://relay.example/custom:generateContent?route=1",
        ):
            with self.subTest(endpoint=endpoint):
                provider, session = self.make_provider(base_url=endpoint)
                await provider.generate_image("draw a cat", model="ignored-override")
                self.assertEqual(session.posts[0]["url"], endpoint)

    async def test_query_encoding_order_and_duplicate_parameters_are_preserved(self):
        query = "route=a%2Fb&route=two+words&key=fake%2Bkey&empty="
        for path, expected_path in (
            ("", f"/v1beta/models/{MODEL}:generateContent"),
            ("/gateway/v1beta/", f"/gateway/v1beta/models/{MODEL}:generateContent"),
            ("/v1beta/models/pinned", "/v1beta/models/pinned:generateContent"),
        ):
            with self.subTest(path=path):
                provider, session = self.make_provider(base_url=f"https://relay.example{path}?{query}")
                await provider.generate_image("draw a cat")
                self.assertEqual(session.posts[0]["url"], f"https://relay.example{expected_path}?{query}")

    async def test_model_resource_prefix_is_removed_and_reserved_overrides_stay_blocked(self):
        provider, session = self.make_provider(model=f"models/{MODEL}")
        await provider.generate_image("draw a cat", model="untrusted-other-model", contents=[{"text": "replace"}])
        self.assertEqual(session.posts[0]["url"], f"https://relay.example/v1beta/models/{MODEL}:generateContent")
        self.assertEqual(session.posts[0]["json"]["contents"][0]["parts"][0], {"text": "draw a cat"})
        self.assertNotIn("model", session.posts[0]["json"])

    async def test_configured_model_cannot_inject_a_path_or_query(self):
        provider, session = self.make_provider(model="tenant/model?key=not-an-api-key#part")
        await provider.generate_image("draw a cat")
        self.assertEqual(
            session.posts[0]["url"],
            "https://relay.example/v1beta/models/tenant%2Fmodel%3Fkey%3Dnot-an-api-key%23part:generateContent",
        )

    async def test_invalid_nonempty_addresses_fail_without_any_request_or_google_fallback(self):
        for base_url in ("relay.example/v1beta", "//relay.example/v1beta", "ftp://relay.example/v1beta", "/v1beta", "https://"):
            with self.subTest(base_url=base_url):
                provider, session = self.make_provider(base_url=base_url)
                with self.assertRaisesRegex(ValueError, "HTTP"):
                    await provider.generate_image("draw a cat")
                self.assertEqual(session.posts, [])

    async def test_custom_http_failure_never_retries_the_official_host(self):
        provider, session = self.make_provider(status=404, response={"error": {"message": "route not found"}})
        with self.assertRaisesRegex(RuntimeError, "HTTP 404"):
            await provider.generate_image("draw a cat")
        self.assertEqual(len(session.posts), 1)
        self.assertEqual(urlparse(session.posts[0]["url"]).hostname, "relay.example")

    async def test_static_proxy_payload_auth_reference_and_generation_settings_are_unchanged(self):
        provider, session = self.make_provider(base_url="https://relay.example/gateway/v1beta?route=one")
        reference = "data:image/png;base64," + IMAGE_B64
        result = await provider.generate_image(
            "edit a cat", user_refs=[reference], size="1024x1024", image_size="2k", temperature=0.7,
            safety_settings=[{"category": "test", "threshold": "BLOCK_NONE"}],
        )
        request = session.posts[0]
        self.assertEqual(result, reference)
        self.assertEqual(request["headers"], {"Content-Type": "application/json", "x-goog-api-key": "fake-gemini-key"})
        self.assertEqual(request["timeout"].total, 120.0)
        self.assertEqual(request["json"], {
            "contents": [{"role": "user", "parts": [
                {"text": "edit a cat"}, {"inlineData": {"mimeType": "image/png", "data": IMAGE_B64}},
            ]}],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"], "temperature": 0.7,
                "imageConfig": {"aspectRatio": "1:1", "imageSize": "2K"},
            },
            "safetySettings": [{"category": "test", "threshold": "BLOCK_NONE"}],
        })

    async def test_request_log_identifies_native_protocol_and_redacts_query_keys(self):
        provider, _ = self.make_provider(base_url="https://relay.example/v1beta?key=private-query-key")
        await provider.generate_image("draw a cat")
        messages = "\n".join(text for _, text in fixtures.fake_logger.messages)
        self.assertIn("relay.example/v1beta/models/", messages)
        self.assertIn("Gemini\u539f\u751f\u901a\u9053", messages)
        self.assertNotIn("private-query-key", messages)
        self.assertNotIn("fake-gemini-key", messages)

    async def test_gemini_proxy_rejects_gif_before_posting(self):
        provider, session = self.make_provider(model="gpt-image-2.6-flare")
        with self.assertRaisesRegex(ValueError, "GIF"):
            await provider.generate_image("animated cat", output_format="gif")
        self.assertEqual(session.posts, [])

    async def test_gif_chain_skips_gemini_proxy_and_keeps_native_gif_images_request(self):
        providers = [provider_config(), provider_config(
            id="gif-native", api_type="openai_image", model="gpt-image-2.6-flare",
            base_url="https://images.example/v1", default_size="1536x1024",
        )]
        session = fixtures.FakeSession(fixtures.FakeResponse({"data": [{"b64_json": GIF_B64}]}))
        result = await fixtures.ChainManager(chain_config(providers), session).run_chain_with_metadata(
            "text2img", "animated cat", output_format="gif", frame_count=8, frame_duration_ms=100,
        )
        self.assertEqual(len(session.posts), 1)
        self.assertEqual(session.posts[0]["url"], "https://images.example/v1/images/generations")
        self.assertEqual(session.posts[0]["json"]["output_format"], "gif")
        self.assertEqual(session.posts[0]["json"]["frame_count"], 8)
        self.assertEqual(session.posts[0]["json"]["frame_duration_ms"], 100)
        self.assertEqual(session.posts[0]["json"]["size"], "auto")
        self.assertEqual(result.provider_id, "gif-native")
        self.assertEqual(result.output_format, "gif")

    async def test_static_chain_uses_custom_host_and_node_defaults(self):
        config = provider_config(base_url="https://relay.example/v1", default_size="1024x1024")
        session = fixtures.FakeSession(fixtures.FakeResponse(image_response()))
        result = await fixtures.ChainManager(chain_config([config]), session).run_chain_with_metadata("text2img", "cat")
        self.assertEqual(session.posts[0]["url"], f"https://relay.example/v1/models/{MODEL}:generateContent")
        self.assertEqual(session.posts[0]["json"]["generationConfig"]["imageConfig"]["aspectRatio"], "1:1")
        self.assertEqual(result.provider_id, config.id)
        self.assertEqual(result.output_format, "")

    def test_current_and_legacy_configuration_keep_custom_addresses(self):
        endpoint = "https://relay.example/gateway/v1beta?route=a%2Fb"
        for key in ("base_url", "\u63a5\u53e3\u5730\u5740 (\u9700\u542b/v1)", "\u63a5\u53e3\u5730\u5740 (\u9700\u542b/v1\u6216/v2)"):
            with self.subTest(key=key):
                raw = {"id": "gemini-proxy", "api_type": "Gemini", key: endpoint, "model": MODEL, "api_keys": ["fake-key"]}
                original = dict(raw)
                config = fixtures.models_module._build_provider_config(raw, is_video=False)
                self.assertEqual(config.base_url, endpoint)
                self.assertEqual(config.api_type, "gemini_official")
                self.assertEqual(raw, original)


if __name__ == "__main__":
    unittest.main()
