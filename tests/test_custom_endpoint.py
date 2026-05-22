import base64
import importlib
import json
import sys
import types
import unittest
from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parents[1]
PACKAGE_NAME = PLUGIN_DIR.name
PACKAGE_PARENT = PLUGIN_DIR.parent
sys.path.insert(0, str(PACKAGE_PARENT))

astrbot_module = types.ModuleType("astrbot")
astrbot_api_module = types.ModuleType("astrbot.api")
astrbot_event_module = types.ModuleType("astrbot.api.event")


class _Logger:
    def __init__(self):
        self.messages = []

    def info(self, *args, **kwargs):
        self.messages.append(("info", " ".join(str(arg) for arg in args)))

    def warning(self, *args, **kwargs):
        self.messages.append(("warning", " ".join(str(arg) for arg in args)))

    def error(self, *args, **kwargs):
        self.messages.append(("error", " ".join(str(arg) for arg in args)))


fake_logger = _Logger()
astrbot_api_module.logger = fake_logger
astrbot_event_module.AstrMessageEvent = object
sys.modules.setdefault("astrbot", astrbot_module)
sys.modules.setdefault("astrbot.api", astrbot_api_module)
sys.modules.setdefault("astrbot.api.event", astrbot_event_module)

models_module = importlib.import_module(f"{PACKAGE_NAME}.models")
base_module = importlib.import_module(f"{PACKAGE_NAME}.providers.base")
custom_endpoint_module = importlib.import_module(f"{PACKAGE_NAME}.providers.custom_endpoint_impl")
openai_impl_module = importlib.import_module(f"{PACKAGE_NAME}.providers.openai_impl")
openai_chat_module = importlib.import_module(f"{PACKAGE_NAME}.providers.openai_chat_impl")

ProviderConfig = models_module.ProviderConfig
_normalize_api_type = models_module._normalize_api_type
extract_error_message = base_module.extract_error_message
extract_image_url_from_response = base_module.extract_image_url_from_response
is_complete_endpoint_url = base_module.is_complete_endpoint_url
summarize_payload_for_log = base_module.summarize_payload_for_log
summarize_text_for_log = base_module.summarize_text_for_log
summarize_url_for_log = base_module.summarize_url_for_log
CustomEndpointProvider = custom_endpoint_module.CustomEndpointProvider
OpenAIProvider = openai_impl_module.OpenAIProvider
OpenAIChatProvider = openai_chat_module.OpenAIChatProvider


def _long_b64() -> str:
    return base64.b64encode(b"image-bytes" * 20).decode("ascii")


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    async def text(self):
        return self.payload if isinstance(self.payload, str) else json.dumps(self.payload)

    async def json(self):
        if isinstance(self.payload, str):
            return json.loads(self.payload)
        return self.payload


class FakePost:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.posts = []
        self.gets = []

    def post(self, url, **kwargs):
        self.posts.append({"url": url, **kwargs})
        return FakePost(self.response)

    def get(self, url, **kwargs):
        self.gets.append({"url": url, **kwargs})
        return FakePost(self.response)


class CustomEndpointHelpersTest(unittest.TestCase):
    def test_custom_api_type_is_preserved(self):
        self.assertEqual(_normalize_api_type("custom_endpoint", is_video=False), "custom_endpoint")
        self.assertEqual(_normalize_api_type("自定义", is_video=False), "custom_endpoint")

    def test_complete_endpoint_validation_rejects_roots(self):
        self.assertTrue(is_complete_endpoint_url("https://api.example.com/v1/images/generations"))
        self.assertTrue(is_complete_endpoint_url("https://ark.cn-beijing.volces.com/api/v3/images/generations"))
        self.assertFalse(is_complete_endpoint_url("https://api.example.com"))
        self.assertFalse(is_complete_endpoint_url("https://api.example.com/v1"))
        self.assertFalse(is_complete_endpoint_url("https://api.example.com/api"))

    def test_extracts_common_image_shapes(self):
        endpoint = "https://api.example.com/v1/images/generations"
        self.assertEqual(
            extract_image_url_from_response({"data": [{"url": "https://cdn.example.com/a.png"}]}, endpoint),
            "https://cdn.example.com/a.png",
        )
        self.assertTrue(
            extract_image_url_from_response({"data": [{"b64_json": _long_b64()}]}, endpoint).startswith(
                "data:image/png;base64,"
            )
        )
        self.assertEqual(
            extract_image_url_from_response(
                {"choices": [{"message": {"content": "![image](https://cdn.example.com/chat.png)"}}]},
                endpoint,
            ),
            "https://cdn.example.com/chat.png",
        )
        self.assertEqual(
            extract_image_url_from_response(
                {"choices": [{"message": {"content": [{"type": "text", "text": "https://cdn.example.com/list.png"}]}}]},
                endpoint,
            ),
            "https://cdn.example.com/list.png",
        )
        self.assertTrue(
            extract_image_url_from_response({"output": [{"type": "image_generation_call", "result": _long_b64()}]}, endpoint).startswith(
                "data:image/png;base64,"
            )
        )
        self.assertTrue(
            extract_image_url_from_response({"image": _long_b64()}, endpoint).startswith("data:image/png;base64,")
        )
        self.assertEqual(
            extract_image_url_from_response({"images": [{"url": "/files/out.png"}]}, endpoint),
            "https://api.example.com/files/out.png",
        )
        self.assertEqual(
            extract_image_url_from_response({"image": "files/from-image-key.webp"}, endpoint),
            "https://api.example.com/files/from-image-key.webp",
        )

    def test_payload_log_summary_redacts_nested_data_urls(self):
        image_data_url = "data:image/jpeg;base64," + _long_b64()
        upper_image_data_url = "DATA:Image/PNG;base64," + _long_b64()
        raw_image = base64.b64encode(b"raw-image" * 40).decode("ascii")
        payload = {
            "model": "gpt-image-2",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                        {"type": "image_url", "image_url": {"url": upper_image_data_url}},
                        {"type": "text", "text": "x" * 220},
                    ],
                }
            ],
            "b64_json": raw_image,
            "image": raw_image,
            "api_key": "sk-test-should-not-log",
        }

        summary = summarize_payload_for_log(payload)

        image_summary = summary["messages"][0]["content"][0]["image_url"]["url"]
        upper_image_summary = summary["messages"][0]["content"][1]["image_url"]["url"]
        text_summary = summary["messages"][0]["content"][2]["text"]
        self.assertIn("<image_data_url", image_summary)
        self.assertIn("<image_data_url", upper_image_summary)
        self.assertIn("chars=", image_summary)
        self.assertNotIn(_long_b64()[:40], str(summary))
        self.assertNotIn(raw_image[:40], str(summary))
        self.assertEqual(summary["b64_json"], f"<image_base64 chars={len(raw_image)}>")
        self.assertEqual(summary["image"], f"<image_base64 chars={len(raw_image)}>")
        self.assertEqual(text_summary, "<text chars=220>")
        self.assertEqual(summary["api_key"], "<redacted>")

    def test_extract_error_message_sanitizes_echoed_payload(self):
        raw_image = base64.b64encode(b"raw-image" * 40).decode("ascii")
        payload = {
            "error": {
                "message": {
                    "api_key": "sk-test-should-not-log",
                    "image": raw_image,
                    "text": "x" * 300,
                }
            }
        }

        message = extract_error_message(json.dumps(payload))

        self.assertNotIn("sk-test-should-not-log", message)
        self.assertNotIn(raw_image[:40], message)
        self.assertIn("<redacted>", message)
        self.assertIn("<image_base64", message)

    def test_plain_text_log_summary_redacts_embedded_secrets_and_data_urls(self):
        image_data_url = "data:image/png;base64," + _long_b64()
        text = "API key: AIzaSyExampleSecret123456789 failed for image " + image_data_url + ". prompt: draw a cat"

        summary = summarize_text_for_log(text, max_string_length=500)

        self.assertNotIn("AIzaSyExampleSecret123456789", summary)
        self.assertNotIn("draw a cat", summary)
        self.assertNotIn(_long_b64()[:40], summary)
        self.assertIn("API key=<redacted>", summary)
        self.assertIn("prompt=<redacted>", summary)
        self.assertIn("<image_data_url", summary)

    def test_url_summary_redacts_custom_endpoint_query_values(self):
        endpoint = (
            "https://api.example.com/v1/images/generations"
            "?api_key=AIzaSyExampleSecret123456789&token=plain-token&size=1024x1024"
        )

        summary = summarize_url_for_log(endpoint)

        self.assertIn("https://api.example.com/v1/images/generations", summary)
        self.assertIn("api_key=<redacted>", summary)
        self.assertIn("token=<redacted>", summary)
        self.assertIn("size=<redacted>", summary)
        self.assertNotIn("AIzaSyExampleSecret123456789", summary)
        self.assertNotIn("plain-token", summary)
        self.assertNotIn("1024x1024", summary)


class CustomEndpointProviderTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fake_logger.messages.clear()

    def _provider(self, endpoint, response_payload, provider_cls=CustomEndpointProvider, status=200):
        if provider_cls is CustomEndpointProvider:
            api_type = "custom_endpoint"
        elif provider_cls is OpenAIChatProvider:
            api_type = "openai_chat"
        else:
            api_type = "openai_image"
        config = ProviderConfig(
            id="custom_node",
            api_type=api_type,
            base_url=endpoint,
            api_keys=["test-key"],
            model="image-model",
            timeout=30.0,
        )
        session = FakeSession(FakeResponse(response_payload, status=status))
        return provider_cls(config, session), session

    def _log_text(self):
        return "\n".join(message for _, message in fake_logger.messages)

    def _prompt_log_text(self):
        return "\n".join(message for _, message in fake_logger.messages if "核心提示词" in message)

    def _request_summary_log_text(self):
        return "\n".join(
            message
            for _, message in fake_logger.messages
            if "请求体摘要" in message or "高级参数" in message or "透传摘要" in message
        )

    def _non_prompt_log_text(self):
        return "\n".join(message for _, message in fake_logger.messages if "核心提示词" not in message)

    async def test_posts_exact_image_endpoint(self):
        endpoint = "https://api.example.com/v1/images/generations"
        provider, session = self._provider(endpoint, {"data": [{"url": "https://cdn.example.com/out.png"}]})

        result = await provider.generate_image("draw a cat", size="1024x1024")

        self.assertEqual(result, "https://cdn.example.com/out.png")
        self.assertEqual(session.posts[0]["url"], endpoint)
        self.assertEqual(session.posts[0]["json"]["prompt"], "draw a cat")
        self.assertEqual(session.posts[0]["json"]["size"], "1024x1024")

    async def test_custom_image_payload_uses_siliconflow_reference_fields(self):
        endpoint = "https://api.example.com/v1/images/generations"
        provider, session = self._provider(endpoint, {"images": [{"url": "https://cdn.example.com/out.png"}]})
        ref = "data:image/png;base64," + _long_b64()
        ref2 = "data:image/png;base64," + base64.b64encode(b"ref-2" * 30).decode("ascii")
        ref3 = "data:image/png;base64," + base64.b64encode(b"ref-3" * 30).decode("ascii")

        await provider.generate_image("edit a cat", user_refs=[ref, ref2, ref3])

        self.assertEqual(session.posts[0]["url"], endpoint)
        self.assertEqual(session.posts[0]["json"]["image"], ref)
        self.assertEqual(session.posts[0]["json"]["image2"], ref2)
        self.assertEqual(session.posts[0]["json"]["image3"], ref3)
        self.assertNotIn("images", session.posts[0]["json"])

    async def test_preserves_exact_custom_endpoint_url(self):
        endpoint = "https://api.example.com/v1/images/generations/"
        provider, session = self._provider(endpoint, {"data": [{"url": "https://cdn.example.com/out.png"}]})

        await provider.generate_image("draw a cat")

        self.assertEqual(session.posts[0]["url"], endpoint)

    async def test_rejects_edits_endpoint_without_reference_image(self):
        endpoint = "https://api.example.com/v1/images/edits"
        provider, session = self._provider(endpoint, {"data": [{"url": "unused"}]})

        with self.assertRaisesRegex(ValueError, "至少一张参考图"):
            await provider.generate_image("edit a cat")

        self.assertEqual(session.posts, [])

    async def test_edits_endpoint_uses_multipart_image_array_for_multiple_references(self):
        endpoint = "https://api.example.com/v1/images/edits"
        provider, session = self._provider(endpoint, {"data": [{"url": "https://cdn.example.com/out.png"}]})
        ref = "data:image/png;base64," + _long_b64()
        ref2 = "data:image/png;base64," + base64.b64encode(b"ref-2" * 30).decode("ascii")

        await provider.generate_image("edit a cat", user_refs=[ref, ref2])

        self.assertEqual(session.posts[0]["url"], endpoint)
        form = session.posts[0]["data"]
        image_field_names = [
            field[0]["name"]
            for field in getattr(form, "_fields", [])
            if field and field[0].get("name", "").startswith("image")
        ]
        self.assertEqual(image_field_names, ["image[]", "image[]"])

    async def test_posts_exact_chat_endpoint(self):
        endpoint = "https://api.example.com/v1/chat/completions"
        provider, session = self._provider(
            endpoint,
            {"choices": [{"message": {"content": "https://cdn.example.com/chat-out.png"}}]},
        )

        result = await provider.generate_image("draw a cat")

        self.assertEqual(result, "https://cdn.example.com/chat-out.png")
        self.assertEqual(session.posts[0]["url"], endpoint)
        self.assertIn("messages", session.posts[0]["json"])

    async def test_posts_exact_responses_endpoint(self):
        endpoint = "https://api.example.com/v1/responses"
        provider, session = self._provider(
            endpoint,
            {"output": [{"type": "image_generation_call", "result": _long_b64()}]},
        )

        result = await provider.generate_image("draw a cat")

        self.assertTrue(result.startswith("data:image/png;base64,"))
        self.assertEqual(session.posts[0]["url"], endpoint)
        self.assertIn("tools", session.posts[0]["json"])

    async def test_rejects_incomplete_custom_endpoint(self):
        provider, session = self._provider("https://api.example.com/v1", {"data": [{"url": "unused"}]})

        with self.assertRaisesRegex(ValueError, "完整请求路径"):
            await provider.generate_image("draw a cat")

        self.assertEqual(session.posts, [])

    async def test_local_reference_missing_does_not_post(self):
        endpoint = "https://api.example.com/v1/images/generations"
        provider, session = self._provider(endpoint, {"data": [{"url": "unused"}]})

        with self.assertRaisesRegex(RuntimeError, "本地参考图不存在"):
            await provider.generate_image("edit a cat", user_refs=["C:/definitely/missing.png"])

        self.assertEqual(session.posts, [])


    async def test_provider_logs_are_summarized_without_mutating_json_payloads(self):
        raw_b64 = base64.b64encode(b"provider-raw-image" * 35).decode("ascii")
        ref_data_url = "data:image/png;base64," + raw_b64
        secret = "sk-provider-secret-should-not-log"
        long_prompt = "draw " + ("very detailed " * 30) + "PROMPT_TAIL_SHOULD_NOT_LOG"

        cases = [
            (
                CustomEndpointProvider,
                "https://api.example.com/v1/images/generations",
                {"data": [{"url": "https://cdn.example.com/custom.png"}]},
                {"user_refs": [ref_data_url], "api_key": secret, "b64_json": raw_b64},
            ),
            (
                OpenAIProvider,
                "https://api.example.com/v1",
                {"data": [{"url": "https://cdn.example.com/openai.png"}]},
                {"api_key": secret, "b64_json": raw_b64},
            ),
            (
                OpenAIChatProvider,
                "https://api.example.com/v1",
                {"choices": [{"message": {"content": "https://cdn.example.com/chat.png"}}]},
                {"api_key": secret, "b64_json": raw_b64},
            ),
        ]

        for provider_cls, endpoint, response_payload, kwargs in cases:
            with self.subTest(provider_cls=provider_cls.__name__):
                fake_logger.messages.clear()
                provider, session = self._provider(endpoint, response_payload, provider_cls=provider_cls)

                await provider.generate_image(long_prompt, **kwargs)

                sent_payload = session.posts[0]["json"]
                if provider_cls is CustomEndpointProvider:
                    self.assertEqual(sent_payload["prompt"], long_prompt)
                    self.assertEqual(sent_payload["image"], ref_data_url)
                elif provider_cls is OpenAIProvider:
                    self.assertEqual(sent_payload["prompt"], long_prompt)
                else:
                    self.assertIn(long_prompt, sent_payload["messages"][0]["content"][0]["text"])
                self.assertEqual(sent_payload["api_key"], secret)
                self.assertEqual(sent_payload["b64_json"], raw_b64)

                logs = self._log_text()
                self.assertNotIn(secret, logs)
                self.assertNotIn(raw_b64[:40], logs)
                self.assertIn(long_prompt, self._prompt_log_text())
                self.assertIn("PROMPT_TAIL_SHOULD_NOT_LOG", self._prompt_log_text())
                self.assertIn("<redacted>", logs)
                self.assertIn("<image_base64", logs)
                summary_logs = self._request_summary_log_text()
                self.assertNotIn(long_prompt, summary_logs)
                self.assertNotIn("PROMPT_TAIL_SHOULD_NOT_LOG", summary_logs)
                if provider_cls is not OpenAIChatProvider:
                    self.assertIn("<prompt chars=", summary_logs)

    async def test_short_prompts_and_custom_endpoint_queries_do_not_leak_to_logs(self):
        short_prompt = "draw a cat"
        query_secret = "AIzaSyQuerySecret123456789"
        cases = [
            (
                CustomEndpointProvider,
                "https://api.example.com/v1/images/generations?api_key=" + query_secret + "&size=1024x1024",
                {"data": [{"url": "https://cdn.example.com/custom.png"}]},
                lambda payload: payload["prompt"],
            ),
            (
                CustomEndpointProvider,
                "https://api.example.com/v1/chat/completions",
                {"choices": [{"message": {"content": "https://cdn.example.com/custom-chat.png"}}]},
                lambda payload: payload["messages"][0]["content"][0]["text"],
            ),
            (
                CustomEndpointProvider,
                "https://api.example.com/v1/responses",
                {"output": [{"type": "image_generation_call", "result": _long_b64()}]},
                lambda payload: payload["input"],
            ),
            (
                OpenAIProvider,
                "https://api.example.com/v1",
                {"data": [{"url": "https://cdn.example.com/openai.png"}]},
                lambda payload: payload["prompt"],
            ),
            (
                OpenAIChatProvider,
                "https://api.example.com/v1",
                {"choices": [{"message": {"content": "https://cdn.example.com/chat.png"}}]},
                lambda payload: payload["messages"][0]["content"][0]["text"],
            ),
        ]

        for provider_cls, endpoint, response_payload, prompt_getter in cases:
            with self.subTest(provider_cls=provider_cls.__name__, endpoint=endpoint):
                fake_logger.messages.clear()
                provider, session = self._provider(endpoint, response_payload, provider_cls=provider_cls)

                await provider.generate_image(short_prompt)

                self.assertIn(short_prompt, prompt_getter(session.posts[0]["json"]))
                if provider_cls is CustomEndpointProvider:
                    self.assertEqual(session.posts[0]["url"], endpoint)
                logs = self._log_text()
                self.assertIn(short_prompt, self._prompt_log_text())
                self.assertNotIn(short_prompt, self._request_summary_log_text())
                self.assertNotIn(query_secret, logs)
                self.assertNotIn("1024x1024", logs)
                if provider_cls is not OpenAIChatProvider:
                    summary_logs = self._request_summary_log_text()
                    self.assertTrue(
                        "<prompt chars=" in summary_logs
                        or "<text chars=" in summary_logs
                        or "<input chars=" in summary_logs
                    )
                if query_secret in endpoint:
                    self.assertIn("api_key=<redacted>", logs)

    async def test_provider_error_logs_and_exceptions_are_sanitized(self):
        raw_b64 = base64.b64encode(b"provider-error-image" * 40).decode("ascii")
        secret = "sk-error-secret-should-not-log"
        long_detail = ("echoed error detail " * 40) + "ERROR_TAIL_SHOULD_NOT_LOG"
        error_payload = {
            "error": {
                "message": {
                    "api_key": secret,
                    "image": raw_b64,
                    "detail": long_detail,
                }
            }
        }

        cases = [
            (CustomEndpointProvider, "https://api.example.com/v1/images/generations"),
            (OpenAIProvider, "https://api.example.com/v1"),
            (OpenAIChatProvider, "https://api.example.com/v1"),
        ]

        for provider_cls, endpoint in cases:
            with self.subTest(provider_cls=provider_cls.__name__):
                fake_logger.messages.clear()
                provider, _ = self._provider(endpoint, error_payload, provider_cls=provider_cls, status=400)

                with self.assertRaises(RuntimeError) as raised:
                    await provider.generate_image("draw a cat")

                combined = str(raised.exception) + "\n" + self._log_text()
                self.assertNotIn(secret, combined)
                self.assertNotIn(raw_b64[:40], combined)
                self.assertNotIn("ERROR_TAIL_SHOULD_NOT_LOG", combined)
                self.assertIn("<redacted>", combined)
                self.assertIn("<image_base64", combined)

    async def test_short_error_text_does_not_echo_prompt_or_non_openai_key(self):
        query_secret = "AIzaSyErrorSecret123456789"
        error_payload = {"error": {"message": "Invalid API key: " + query_secret + " for prompt: draw a cat"}}
        cases = [
            (CustomEndpointProvider, "https://api.example.com/v1/images/generations"),
            (OpenAIProvider, "https://api.example.com/v1"),
            (OpenAIChatProvider, "https://api.example.com/v1"),
        ]

        for provider_cls, endpoint in cases:
            with self.subTest(provider_cls=provider_cls.__name__):
                fake_logger.messages.clear()
                provider, _ = self._provider(endpoint, error_payload, provider_cls=provider_cls, status=400)

                with self.assertRaises(RuntimeError) as raised:
                    await provider.generate_image("draw a cat")

                combined = str(raised.exception) + "\n" + self._non_prompt_log_text()
                self.assertNotIn(query_secret, combined)
                self.assertNotIn("draw a cat", combined)
                self.assertIn("API key=<redacted>", combined)
                self.assertIn("prompt=<redacted>", combined)
                self.assertIn("draw a cat", self._prompt_log_text())

    async def test_unexpected_success_response_exception_is_summarized(self):
        raw_b64 = base64.b64encode(b"unexpected-success-image" * 35).decode("ascii")
        payload = {
            "error": {
                "api_key": "sk-success-secret-should-not-log",
                "image": raw_b64,
                "detail": "x" * 700,
            }
        }
        provider, _ = self._provider("https://api.example.com/v1", payload, provider_cls=OpenAIProvider)

        with self.assertRaises(ValueError) as raised:
            await provider.generate_image("draw a cat")

        message = str(raised.exception)
        self.assertNotIn("sk-success-secret-should-not-log", message)
        self.assertNotIn(raw_b64[:40], message)
        self.assertIn("<redacted>", message)
        self.assertIn("<image_base64", message)


if __name__ == "__main__":
    unittest.main()
