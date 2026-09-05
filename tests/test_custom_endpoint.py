import ast
import asyncio
import base64
import importlib
import json
import sys
import tempfile
import threading
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
astrbot_event_components_module = types.ModuleType("astrbot.api.event.components")
astrbot_message_components_module = types.ModuleType("astrbot.api.message_components")
astrbot_star_module = types.ModuleType("astrbot.api.star")
quart_module = types.ModuleType("quart")


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


class _Plain:
    def __init__(self, text=""):
        self.text = text


class _At:
    def __init__(self, qq=""):
        self.qq = qq


class _Video:
    @classmethod
    def fromURL(cls, url):
        return {"type": "video", "url": url}


class _Image:
    @classmethod
    def fromFileSystem(cls, path):
        return {"type": "image_file", "path": path}

    @classmethod
    def fromURL(cls, url):
        return {"type": "image_url", "url": url}


class _Filter:
    class PermissionType:
        ADMIN = "admin"

    def command(self, *args, **kwargs):
        return lambda func: func

    def permission_type(self, *args, **kwargs):
        return lambda func: func

    def event_message_type(self, *args, **kwargs):
        return lambda func: func


class _Star:
    def __init__(self, context=None):
        self.context = context


def _identity_decorator(*args, **kwargs):
    return lambda item: item


def _jsonify(*args, **kwargs):
    return {"args": args, "kwargs": kwargs}


async def _send_file(*args, **kwargs):
    return {"args": args, "kwargs": kwargs}


astrbot_message_components_module.Plain = _Plain
astrbot_message_components_module.Image = _Image
astrbot_message_components_module.At = _At
astrbot_message_components_module.Video = _Video
astrbot_event_components_module.Plain = _Plain
astrbot_event_components_module.Image = _Image
astrbot_event_components_module.At = _At
astrbot_event_module.filter = _Filter()
astrbot_event_module.EventMessageType = types.SimpleNamespace(ALL="all")
astrbot_api_module.llm_tool = _identity_decorator
astrbot_star_module.Context = object
astrbot_star_module.Star = _Star
astrbot_star_module.register = _identity_decorator
quart_module.jsonify = _jsonify
quart_module.request = types.SimpleNamespace(get_json=lambda *args, **kwargs: {})
quart_module.send_file = _send_file
sys.modules.setdefault("astrbot", astrbot_module)
sys.modules.setdefault("astrbot.api", astrbot_api_module)
sys.modules.setdefault("astrbot.api.event", astrbot_event_module)
sys.modules.setdefault("astrbot.api.event.components", astrbot_event_components_module)
sys.modules.setdefault("astrbot.api.message_components", astrbot_message_components_module)
sys.modules.setdefault("astrbot.api.star", astrbot_star_module)
sys.modules.setdefault("quart", quart_module)

models_module = importlib.import_module(f"{PACKAGE_NAME}.models")
base_module = importlib.import_module(f"{PACKAGE_NAME}.providers.base")
custom_endpoint_module = importlib.import_module(f"{PACKAGE_NAME}.providers.custom_endpoint_impl")
gemini_official_module = importlib.import_module(f"{PACKAGE_NAME}.providers.gemini_official_impl")
openai_impl_module = importlib.import_module(f"{PACKAGE_NAME}.providers.openai_impl")
openai_chat_module = importlib.import_module(f"{PACKAGE_NAME}.providers.openai_chat_impl")
provider_factory_module = importlib.import_module(f"{PACKAGE_NAME}.providers")
chain_manager_module = importlib.import_module(f"{PACKAGE_NAME}.core.chain_manager")
prompt_optimizer_module = importlib.import_module(f"{PACKAGE_NAME}.core.prompt_optimizer")
video_manager_module = importlib.import_module(f"{PACKAGE_NAME}.core.video_manager")
main_module = importlib.import_module(f"{PACKAGE_NAME}.main")

ProviderConfig = models_module.ProviderConfig
PluginConfig = models_module.PluginConfig
_normalize_api_type = models_module._normalize_api_type
ChainRunResult = chain_manager_module.ChainRunResult
ChainManager = chain_manager_module.ChainManager
PromptOptimizer = prompt_optimizer_module.PromptOptimizer
OmniDrawPlugin = main_module.OmniDrawPlugin
VideoManager = video_manager_module.VideoManager
VideoTaskError = video_manager_module.VideoTaskError
extract_error_message = base_module.extract_error_message
extract_image_url_from_response = base_module.extract_image_url_from_response
is_complete_endpoint_url = base_module.is_complete_endpoint_url
summarize_payload_for_log = base_module.summarize_payload_for_log
summarize_text_for_log = base_module.summarize_text_for_log
summarize_url_for_log = base_module.summarize_url_for_log
CustomEndpointProvider = custom_endpoint_module.CustomEndpointProvider
GeminiOfficialProvider = gemini_official_module.GeminiOfficialProvider
OpenAIProvider = openai_impl_module.OpenAIProvider
OpenAIChatProvider = openai_chat_module.OpenAIChatProvider


def _long_b64() -> str:
    return base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"image-bytes" * 20).decode("ascii")


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


class PromptOptimizerRegressionTest(unittest.IsolatedAsyncioTestCase):
    class OptimizerResponse:
        def __init__(self, payload, headers=None):
            self.payload = payload
            self.headers = headers or {}
            self.charset = "utf-8"
            self.read_called = False

        def raise_for_status(self):
            return None

        async def read(self):
            self.read_called = True
            return json.dumps(self.payload).encode("utf-8")

    @staticmethod
    def _config(api_type="openai_chat", api_keys=None):
        provider = ProviderConfig(
            id="optimizer-node",
            api_type=api_type,
            base_url="https://api.example.com/v1",
            api_keys=api_keys or ["key-a", "key-b"],
            model="chat-model",
            timeout=30.0,
        )
        config = types.SimpleNamespace(
            enable_optimizer=True,
            chains={"optimizer": [provider.id]},
            providers=[provider],
            optimizer_model="chat-model",
            optimizer_timeout=15.0,
            optimizer_style="手机日常原生感",
            optimizer_custom_prompt="",
        )
        config.get_provider = lambda provider_id: provider if provider_id == provider.id else None
        return config

    async def test_extracts_legal_top_level_json_array(self):
        content = json.dumps([
            {"subject_appearance": "first distinct subject"},
            {"subject_appearance": "second distinct subject"},
        ])
        response = self.OptimizerResponse({
            "choices": [{"message": {"content": content}}],
        })

        results = await PromptOptimizer(self._config()).optimize(
            "raw action",
            count=2,
            session=FakeSession(response),
        )

        self.assertIn("first distinct subject", results[0])
        self.assertIn("second distinct subject", results[1])

    async def test_extracts_top_level_array_before_bracketed_trailing_note(self):
        content = json.dumps([
            {"subject_appearance": "first distinct subject"},
            {"subject_appearance": "second distinct subject"},
        ]) + "\nDone [ok]"
        response = self.OptimizerResponse({
            "choices": [{"message": {"content": content}}],
        })

        results = await PromptOptimizer(self._config()).optimize(
            "raw action",
            count=2,
            session=FakeSession(response),
        )

        self.assertIn("first distinct subject", results[0])
        self.assertIn("second distinct subject", results[1])

    async def test_gemini_official_node_degrades_without_chat_request(self):
        session = FakeSession(self.OptimizerResponse({}))

        results = await PromptOptimizer(self._config(api_type="gemini_official")).optimize(
            "raw action",
            count=2,
            session=session,
        )

        self.assertEqual(results, ["raw action", "raw action"])
        self.assertEqual(session.posts, [])

    async def test_response_body_limit_is_checked_before_read(self):
        response = self.OptimizerResponse(
            {"choices": []},
            headers={"Content-Length": str(prompt_optimizer_module.MAX_OPTIMIZER_RESPONSE_BYTES + 1)},
        )

        results = await PromptOptimizer(self._config()).optimize(
            "raw action",
            session=FakeSession(response),
        )

        self.assertEqual(results, ["raw action"])
        self.assertFalse(response.read_called)

    async def test_optimizer_key_rotation_isolated_from_image_scope(self):
        with base_module._KEY_ROTATION_LOCK:
            original_rotation = dict(base_module._KEY_ROTATION_INDEX)
            base_module._KEY_ROTATION_INDEX.clear()
        try:
            image_scope = "image:openai_chat:https://api.example.com/v1"
            self.assertEqual(
                base_module.next_api_key("optimizer-node", ["key-a", "key-b"], scope=image_scope),
                "key-a",
            )
            response = self.OptimizerResponse({
                "choices": [{"message": {"content": '{"subject_appearance": "optimized subject"}'}}],
            })
            session = FakeSession(response)

            await PromptOptimizer(self._config()).optimize("raw action", session=session)

            self.assertEqual(session.posts[0]["headers"]["Authorization"], "Bearer key-a")
        finally:
            with base_module._KEY_ROTATION_LOCK:
                base_module._KEY_ROTATION_INDEX.clear()
                base_module._KEY_ROTATION_INDEX.update(original_rotation)


class CustomEndpointHelpersTest(unittest.TestCase):
    def test_custom_api_type_is_preserved(self):
        self.assertEqual(_normalize_api_type("custom_endpoint", is_video=False), "custom_endpoint")
        self.assertEqual(_normalize_api_type("自定义", is_video=False), "custom_endpoint")

    def test_gemini_official_api_type_is_preserved(self):
        self.assertEqual(_normalize_api_type("gemini_official", is_video=False), "gemini_official")
        self.assertEqual(_normalize_api_type("Gemini", is_video=False), "gemini_official")
        self.assertEqual(_normalize_api_type("Gemini 官方", is_video=False), "gemini_official")

    def test_video_api_type_normalization_preserves_legacy_aliases(self):
        for value in ("async_task", "async-task", "async task", "异步任务"):
            with self.subTest(value=value):
                self.assertEqual(_normalize_api_type(value, is_video=True), "async_task")

        for value in ("openai_sync", "openai-sync", "OpenAI Sync", "同步模式"):
            with self.subTest(value=value):
                self.assertEqual(_normalize_api_type(value, is_video=True), "openai_sync")

        for value in ("openai_chat", "OpenAI Chat Completions", "chat/completions", "对话模式"):
            with self.subTest(value=value):
                self.assertEqual(_normalize_api_type(value, is_video=True), "openai_chat")

    def test_extracts_gemini_inline_data_response(self):
        endpoint = "https://generativelanguage.googleapis.com/v1beta/models/gemini:generateContent"
        first = base64.b64encode(b"first-image" * 20).decode("ascii")
        final = base64.b64encode(b"final-image" * 20).decode("ascii")
        payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "draft"},
                            {"inlineData": {"mimeType": "image/png", "data": first}},
                            {"inline_data": {"mime_type": "image/webp", "data": final}},
                        ]
                    },
                    "finishReason": "STOP",
                }
            ]
        }

        self.assertEqual(
            extract_image_url_from_response(payload, endpoint),
            "data:image/webp;base64," + final,
        )

    def test_rejects_non_image_or_invalid_gemini_inline_data(self):
        endpoint = "https://generativelanguage.googleapis.com/v1beta/models/gemini:generateContent"
        text_inline = {
            "candidates": [
                {"content": {"parts": [{"inlineData": {"mimeType": "text/plain", "data": _long_b64()}}]}}
            ]
        }
        invalid_image_inline = {
            "candidates": [
                {"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": "not base64!"}}]}}
            ]
        }

        self.assertEqual(extract_image_url_from_response(text_inline, endpoint), "")
        self.assertEqual(extract_image_url_from_response(invalid_image_inline, endpoint), "")

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

    def test_error_message_sanitizes_base64_in_result_fields(self):
        raw_image = base64.b64encode(b"result-image" * 40).decode("ascii")
        payload = {
            "error": {
                "message": {
                    "output": [
                        {"type": "image_generation_call", "result": raw_image},
                    ],
                    "data": raw_image,
                }
            }
        }

        summary = summarize_payload_for_log(payload)
        message = extract_error_message(json.dumps(payload))

        self.assertNotIn(raw_image[:40], str(summary))
        self.assertNotIn(raw_image[:40], message)
        self.assertIn("<image_base64", str(summary))
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


class GenerationMetadataConfigTest(unittest.TestCase):
    def test_generation_metadata_toggles_default_to_hidden(self):
        config = PluginConfig.from_dict({}, str(PLUGIN_DIR))

        self.assertFalse(config.show_generation_time)
        self.assertFalse(config.show_request_model)

    def test_generation_metadata_toggles_are_independent(self):
        config = PluginConfig.from_dict(
            {
                "show_generation_time": True,
                "show_request_model": False,
            },
            str(PLUGIN_DIR),
        )

        self.assertTrue(config.show_generation_time)
        self.assertFalse(config.show_request_model)

    def test_provider_default_sizes_are_normalized(self):
        config = PluginConfig.from_dict(
            {
                "providers": [{"id": "node_1", "default_size": " 1024x1024 "}],
                "video_providers": [{"id": "video_node_1", "default_size": "1280x720"}],
            },
            str(PLUGIN_DIR),
        )

        self.assertEqual(config.providers[0].default_size, "1024x1024")
        self.assertEqual(config.video_providers[0].default_size, "1280x720")


class RuntimeConfigKeyTest(unittest.TestCase):
    def test_generation_metadata_keys_are_preserved_by_runtime_config_cleaner(self):
        tree = ast.parse((PLUGIN_DIR / "main.py").read_text(encoding="utf-8"))
        config_keys = set()
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "CONFIG_KEYS"
                for target in node.targets
            ):
                config_keys = set(ast.literal_eval(node.value))
                break

        self.assertIn("show_generation_time", config_keys)
        self.assertIn("show_request_model", config_keys)

    def test_schema_and_pages_offer_gemini_before_custom(self):
        schema = json.loads((PLUGIN_DIR / "_conf_schema.json").read_text(encoding="utf-8"))
        options = schema["providers"]["templates"]["image_provider"]["items"]["api_type"]["options"]
        self.assertLess(options.index("gemini_official"), options.index("custom_endpoint"))

        app_js = (PLUGIN_DIR / "pages" / "插件配置" / "app.js").read_text(encoding="utf-8")
        self.assertLess(app_js.index('"gemini_official"'), app_js.index('"custom_endpoint"'))
        self.assertIn("GEMINI_OFFICIAL_BASE_URL", app_js)
        self.assertNotIn("return applyImageProviderDefaults({", app_js)

    def test_tests_directory_is_not_gitignored(self):
        gitignore = (PLUGIN_DIR / ".gitignore").read_text(encoding="utf-8")

        self.assertNotIn("tests/", gitignore.splitlines())

    def test_provider_factory_creates_gemini_provider(self):
        config = ProviderConfig(
            id="gemini_node",
            api_type="gemini_official",
            base_url="",
            api_keys=["test-key"],
            model="gemini-3.1-flash-image-preview",
            timeout=120.0,
        )

        self.assertIsInstance(provider_factory_module.create_provider(config, session=object()), GeminiOfficialProvider)


class ImageSuccessComponentsTest(unittest.TestCase):
    def _plugin(self, show_time=True, show_model=True):
        plugin = object.__new__(OmniDrawPlugin)
        plugin.plugin_config = types.SimpleNamespace(
            show_generation_time=show_time,
            show_request_model=show_model,
        )
        plugin._create_image_component = lambda url: {"type": "image", "url": url}
        return plugin

    def test_image_success_components_show_metadata_before_image(self):
        plugin = self._plugin(show_time=True, show_model=True)
        result = ChainRunResult(
            image_url="https://cdn.example.com/out.png",
            provider_id="node_1",
            model="override-model",
            elapsed_seconds=1.2,
        )

        components = plugin._build_image_success_components(result, elapsed_seconds=3.4)

        self.assertEqual(len(components), 2)
        self.assertIn("生图耗时：3.4s", components[0].text)
        self.assertIn("请求模型：override-model", components[0].text)
        self.assertEqual(components[1], {"type": "image", "url": "https://cdn.example.com/out.png"})

    def test_image_success_components_can_hide_metadata_for_llm_tools(self):
        plugin = self._plugin(show_time=True, show_model=True)
        result = ChainRunResult(
            image_url="https://cdn.example.com/out.png",
            provider_id="node_1",
            model="override-model",
            elapsed_seconds=1.2,
        )

        components = plugin._build_image_success_components(result, include_metadata=False)

        self.assertEqual(components, [{"type": "image", "url": "https://cdn.example.com/out.png"}])

    def test_image_success_components_allow_independent_toggles(self):
        result = ChainRunResult(
            image_url="https://cdn.example.com/out.png",
            provider_id="node_1",
            model="actual-model",
            elapsed_seconds=1.2,
        )

        time_only = self._plugin(show_time=True, show_model=False)._build_image_success_components(result)
        model_only = self._plugin(show_time=False, show_model=True)._build_image_success_components(result)
        hidden = self._plugin(show_time=False, show_model=False)._build_image_success_components(result)

        self.assertIn("生图耗时", time_only[0].text)
        self.assertNotIn("请求模型", time_only[0].text)
        self.assertNotIn("生图耗时", model_only[0].text)
        self.assertIn("请求模型：actual-model", model_only[0].text)
        self.assertEqual(hidden, [{"type": "image", "url": "https://cdn.example.com/out.png"}])


class FakeClientSession:
    def __init__(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class PluginImageReturnTest(unittest.IsolatedAsyncioTestCase):
    def _plugin(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin.data_dir = str(PLUGIN_DIR / ".pytest_cache" / "plugin_return")
        plugin.plugin_config = types.SimpleNamespace(max_batch_count=4)
        plugin.prompt_optimizer = types.SimpleNamespace(
            optimize=lambda prompt, count, session=None: self._optimize(prompt, count)
        )
        plugin.persona_manager = types.SimpleNamespace(
            build_persona_prompt=lambda action: (f"persona base, {action}", {"persona_ref": "persona-default.png"})
        )
        plugin._refresh_from_native_config_if_changed = lambda: None
        plugin._process_and_save_images = self._process_refs
        plugin._parse_extra_params = lambda extra: {"model": "override-model"} if extra else {}
        plugin._prune_cache_if_needed = lambda *args, **kwargs: None
        plugin._lease_cache_paths = lambda paths: list(paths or [])
        plugin._release_cache_paths = lambda paths: None
        plugin._recorded_count = 0
        plugin._record_generated_images = lambda event, count=1: setattr(plugin, "_recorded_count", count)
        plugin._permission_denied_message = lambda event: ""
        plugin._image_quota_error_message = lambda event, count=1: ""
        plugin._reserve_image_quota = lambda event, count=1: ("", 0)
        plugin._complete_image_quota = lambda event, reserved, count: setattr(plugin, "_recorded_count", count)
        plugin._release_image_quota = lambda event, reserved: None
        plugin._get_event_images = lambda event: []
        return plugin

    async def _optimize(self, prompt, count):
        return [f"{prompt} #{index}" for index in range(1, count + 1)]

    async def _process_refs(self, refs, session=None):
        return [f"safe:{ref}" for ref in refs]

    async def test_generate_images_for_plugin_returns_images_without_sending(self):
        plugin = self._plugin()
        calls = []
        original_client_session = main_module.aiohttp.ClientSession
        original_chain_manager = main_module.ChainManager

        class FakeChainManager:
            def __init__(self, config, session):
                self.config = config
                self.session = session

            async def run_chain_with_metadata(self, chain_name, prompt, **kwargs):
                calls.append((chain_name, prompt, kwargs))
                return ChainRunResult(
                    image_url=f"https://cdn.example.com/{len(calls)}.png",
                    provider_id="node_1",
                    model=kwargs.get("model", "model_a"),
                    elapsed_seconds=1.5,
                )

        main_module.aiohttp.ClientSession = FakeClientSession
        main_module.ChainManager = FakeChainManager
        try:
            result = await plugin.generate_images_for_plugin(
                prompt="draw a cat",
                count=2,
                size="1024x1024",
                extra_params="--model override-model",
                refs=["https://example.com/ref.png"],
            )
        finally:
            main_module.aiohttp.ClientSession = original_client_session
            main_module.ChainManager = original_chain_manager

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["ref_count"], 1)
        self.assertEqual(result["processed_ref_count"], 1)
        self.assertEqual([image["url"] for image in result["images"]], [
            "https://cdn.example.com/1.png",
            "https://cdn.example.com/2.png",
        ])
        self.assertEqual(result["images"][0]["provider_id"], "node_1")
        self.assertEqual(result["images"][0]["model"], "override-model")
        self.assertEqual(calls[0][2]["user_refs"], ["safe:https://example.com/ref.png"])
        self.assertEqual(calls[0][2]["size"], "1024x1024")
        self.assertEqual(calls[0][0], "text2img")

    async def test_generate_images_for_plugin_supports_selfie_mode(self):
        plugin = self._plugin()
        plugin.plugin_config.persona_ref_images = ["persona-ref.png"]
        plugin.plugin_config.chains = {"selfie": ["selfie_node_1"]}
        calls = []
        original_client_session = main_module.aiohttp.ClientSession
        original_chain_manager = main_module.ChainManager

        class FakeChainManager:
            def __init__(self, config, session):
                pass

            async def run_chain_with_metadata(self, chain_name, prompt, **kwargs):
                calls.append((chain_name, prompt, kwargs))
                return ChainRunResult(
                    image_url="https://cdn.example.com/selfie.png",
                    provider_id="selfie_node_1",
                    model="selfie-model",
                    elapsed_seconds=2.0,
                )

        main_module.aiohttp.ClientSession = FakeClientSession
        main_module.ChainManager = FakeChainManager
        try:
            result = await plugin.generate_images_for_plugin(
                prompt="wearing a red hoodie",
                count=1,
                refs=[],
                mode="selfie",
            )
        finally:
            main_module.aiohttp.ClientSession = original_client_session
            main_module.ChainManager = original_chain_manager

        self.assertTrue(result["success"])
        self.assertEqual(result["mode"], "selfie")
        self.assertEqual(result["chain"], "selfie")
        self.assertEqual(result["processed_ref_count"], 1)
        self.assertEqual(calls[0][0], "selfie")
        self.assertIn("persona base, wearing a red hoodie #1", calls[0][1])
        self.assertEqual(calls[0][2]["user_refs"], ["safe:persona-ref.png"])
        self.assertNotIn("persona_ref", calls[0][2])

    async def test_generate_image_tool_can_return_json_when_requested(self):
        plugin = self._plugin()
        plugin.generate_images_for_plugin = self._fake_generate_images_for_plugin

        payload = await plugin.tool_generate_image(
            event=object(),
            prompt="draw a dog",
            count=1,
            return_result=True,
            refs="https://example.com/ref.png",
        )

        data = json.loads(payload)
        self.assertTrue(data["success"])
        self.assertEqual(data["images"][0]["image_url"], "https://cdn.example.com/out.png")

    async def test_generate_image_tool_returns_json_error_when_return_result_fails(self):
        plugin = self._plugin()

        async def fail_generate_images_for_plugin(**kwargs):
            raise RuntimeError("api_key=sk-secret1234567890 data:image/png;base64," + _long_b64())

        plugin.generate_images_for_plugin = fail_generate_images_for_plugin

        payload = await plugin.tool_generate_image(
            event=object(),
            prompt="draw a dog",
            return_result=True,
        )

        data = json.loads(payload)
        self.assertFalse(data["success"])
        self.assertEqual(data["mode"], "text2img")
        self.assertIn("api_key=<redacted>", data["message"])
        self.assertNotIn("sk-secret", data["message"])
        self.assertNotIn("data:image/png;base64", data["message"])

    async def _fake_generate_images_for_plugin(self, **kwargs):
        self.assertEqual(kwargs["prompt"], "draw a dog")
        self.assertIs(kwargs["record_usage"], True)
        self.assertEqual(kwargs["refs"], "https://example.com/ref.png")
        self.assertEqual(kwargs.get("mode", ""), "")
        return {
            "success": True,
            "message": "ok",
            "images": [{"image_url": "https://cdn.example.com/out.png"}],
        }

    async def test_generate_selfie_tool_can_return_json_when_requested(self):
        plugin = self._plugin()
        plugin.generate_images_for_plugin = self._fake_generate_selfie_for_plugin

        payload = await plugin.tool_generate_selfie(
            event=object(),
            action="look at camera",
            count=1,
            return_result=True,
            refs="https://example.com/selfie-ref.png",
        )

        data = json.loads(payload)
        self.assertTrue(data["success"])
        self.assertEqual(data["mode"], "selfie")
        self.assertEqual(data["images"][0]["image_url"], "https://cdn.example.com/selfie-out.png")

    async def test_generate_selfie_tool_returns_json_error_when_return_result_fails(self):
        plugin = self._plugin()

        async def fail_generate_images_for_plugin(**kwargs):
            raise RuntimeError("Bearer secret-token-value-1234567890")

        plugin.generate_images_for_plugin = fail_generate_images_for_plugin

        payload = await plugin.tool_generate_selfie(
            event=object(),
            action="look at camera",
            return_result=True,
        )

        data = json.loads(payload)
        self.assertFalse(data["success"])
        self.assertEqual(data["mode"], "selfie")
        self.assertIn("Bearer <redacted>", data["message"])
        self.assertNotIn("secret-token", data["message"])

    async def _fake_generate_selfie_for_plugin(self, **kwargs):
        self.assertEqual(kwargs["prompt"], "look at camera")
        self.assertEqual(kwargs["mode"], "selfie")
        self.assertIs(kwargs["record_usage"], True)
        self.assertEqual(kwargs["refs"], "https://example.com/selfie-ref.png")
        return {
            "success": True,
            "message": "ok",
            "mode": "selfie",
            "images": [{"image_url": "https://cdn.example.com/selfie-out.png"}],
        }

    async def test_existing_generate_selfie_tool_still_sends_images_through_shared_generation(self):
        plugin = self._plugin()
        plugin.plugin_config.persona_ref_images = ["persona-ref.png"]
        plugin.plugin_config.chains = {"selfie": ["selfie_node_1"]}
        send_calls = []
        original_client_session = main_module.aiohttp.ClientSession
        original_chain_manager = main_module.ChainManager

        class FakeChainManager:
            def __init__(self, config, session):
                pass

            async def run_chain_with_metadata(self, chain_name, prompt, **kwargs):
                return ChainRunResult(
                    image_url="https://cdn.example.com/old-selfie.png",
                    provider_id="selfie_node_1",
                    model="selfie-model",
                    elapsed_seconds=1.0,
                )

        async def fake_send_generated_images(event, results, *args, **kwargs):
            send_calls.extend(results)
            return len(results)

        main_module.aiohttp.ClientSession = FakeClientSession
        main_module.ChainManager = FakeChainManager
        plugin._send_generated_images = fake_send_generated_images
        try:
            message = await plugin.tool_generate_selfie(object(), "look at camera", count=1)
        finally:
            main_module.aiohttp.ClientSession = original_client_session
            main_module.ChainManager = original_chain_manager

        self.assertIn("已成功生成并下发了 1 张图", message)
        self.assertEqual(len(send_calls), 1)
        self.assertEqual(send_calls[0].image_url, "https://cdn.example.com/old-selfie.png")
        self.assertEqual(plugin._recorded_count, 1)

    async def test_existing_generate_image_tool_still_sends_images(self):
        plugin = self._plugin()
        send_calls = []
        original_client_session = main_module.aiohttp.ClientSession
        original_chain_manager = main_module.ChainManager

        class FakeChainManager:
            def __init__(self, config, session):
                pass

            async def run_chain_with_metadata(self, chain_name, prompt, **kwargs):
                return ChainRunResult(
                    image_url="https://cdn.example.com/old-tool.png",
                    provider_id="node_1",
                    model="model_a",
                    elapsed_seconds=1.0,
                )

        async def fake_send_generated_images(event, results, *args, **kwargs):
            send_calls.extend(results)
            return len(results)

        main_module.aiohttp.ClientSession = FakeClientSession
        main_module.ChainManager = FakeChainManager
        plugin._send_generated_images = fake_send_generated_images
        try:
            message = await plugin.tool_generate_image(object(), "draw a cat", count=1)
        finally:
            main_module.aiohttp.ClientSession = original_client_session
            main_module.ChainManager = original_chain_manager

        self.assertIn("已成功下发 1 张图", message)
        self.assertEqual(len(send_calls), 1)
        self.assertEqual(send_calls[0].image_url, "https://cdn.example.com/old-tool.png")
        self.assertEqual(plugin._recorded_count, 1)

    def test_plugin_refs_accept_json_object_and_dedupe(self):
        plugin = self._plugin()
        refs = plugin._as_plugin_image_refs(json.dumps({
            "url": "https://example.com/ref.png",
        }))

        self.assertEqual(refs, ["https://example.com/ref.png"])
        self.assertEqual(
            plugin._as_plugin_image_refs([
                {"image_url": "https://example.com/ref.png"},
                "https://example.com/ref.png",
                {"path": "local.png"},
            ]),
            ["https://example.com/ref.png", "local.png"],
        )

    def test_plugin_prompt_normalization_preserves_requested_count(self):
        plugin = self._plugin()

        self.assertEqual(
            plugin._normalize_plugin_prompts(["optimized"], "fallback", 3),
            ["optimized", "fallback", "fallback"],
        )
        self.assertEqual(
            plugin._normalize_plugin_prompts(["one", "two", "three"], "fallback", 2),
            ["one", "two"],
        )

    def test_plugin_response_keeps_results_when_prompt_list_is_short_and_redacts_errors(self):
        plugin = self._plugin()
        response, valid_results = plugin._plugin_generation_response({
            "prompts": ["first prompt"],
            "results": [
                ChainRunResult(
                    image_url="https://cdn.example.com/one.png",
                    provider_id="node_1",
                    model="model-a",
                    elapsed_seconds=1.0,
                ),
                ChainRunResult(
                    image_url="https://cdn.example.com/two.png",
                    provider_id="node_1",
                    model="model-a",
                    elapsed_seconds=1.0,
                ),
                RuntimeError("authorization=Bearer-secret-token-1234567890"),
            ],
            "requested_count": 3,
            "raw_refs": [],
            "safe_refs": [],
            "mode": "text2img",
            "chain": "text2img",
        })

        self.assertTrue(response["success"])
        self.assertEqual(response["count"], 2)
        self.assertEqual(len(valid_results), 2)
        self.assertEqual(response["images"][0]["prompt"], "first prompt")
        self.assertEqual(response["images"][1]["prompt"], "")
        self.assertIn("authorization=<redacted>", response["errors"][0])
        self.assertNotIn("Bearer-secret", response["errors"][0])


class FastPresetListTest(unittest.TestCase):
    def _plugin(self, presets):
        plugin = object.__new__(OmniDrawPlugin)
        plugin.plugin_config = types.SimpleNamespace(presets=presets)
        return plugin

    def _event(self, text, is_at_or_wake=True):
        return types.SimpleNamespace(
            message_str=text,
            message_obj=types.SimpleNamespace(message_str=text, message=[]),
            is_at_or_wake_command=is_at_or_wake,
        )

    def test_fast_preset_list_only_contains_preset_names(self):
        plugin = self._plugin(
            {
                "胶片少女": "35mm film portrait, golden hour, detailed private prompt",
                "机甲猫": "mecha cat, cinematic lighting, detailed private prompt",
            }
        )

        message = plugin._build_fast_preset_list_message()

        self.assertIn("✨ 预设列表", message)
        self.assertIn("1. 胶片少女", message)
        self.assertIn("2. 机甲猫", message)
        self.assertNotIn("35mm film portrait", message)
        self.assertNotIn("cinematic lighting", message)
        self.assertNotIn("detailed private prompt", message)

    def test_view_preset_detail_contains_only_selected_prompt(self):
        plugin = self._plugin(
            {
                "胶片少女": "35mm film portrait, golden hour",
                "机甲猫": "mecha cat, cinematic lighting",
            }
        )

        message = plugin._build_preset_view_message("胶片少女")

        self.assertIn("名称：胶片少女", message)
        self.assertIn("提示词：35mm film portrait, golden hour", message)
        self.assertNotIn("mecha cat", message)

    def test_view_preset_detail_accepts_compact_and_bracket_selector(self):
        plugin = self._plugin({"胶片少女": "35mm film portrait"})

        self.assertEqual(plugin._extract_compact_command_payload("/查看预设胶片少女", "查看预设"), "胶片少女")
        self.assertEqual(plugin._extract_compact_command_payload("/查看预设 胶片少女", "查看预设"), "")
        message = plugin._build_preset_view_message("[胶片少女]")

        self.assertIn("名称：胶片少女", message)
        self.assertIn("提示词：35mm film portrait", message)

    def test_compact_view_accepts_configured_astrbot_command_prefix(self):
        plugin = self._plugin({"胶片少女": "35mm film portrait"})
        plugin._configured_astrbot_command_prefixes = lambda: ["#"]

        self.assertEqual(plugin._extract_compact_command_payload("#查看预设胶片少女", "查看预设"), "胶片少女")
        self.assertEqual(plugin._extract_compact_command_payload("#查看预设 胶片少女", "查看预设"), "")
        self.assertEqual(
            plugin._extract_compact_command_payload("查看预设胶片少女", "查看预设", allow_bare=True),
            "胶片少女",
        )

    def test_preset_trigger_accepts_configured_astrbot_command_prefix(self):
        plugin = self._plugin(
            {
                "胶片少女": "35mm film portrait",
                "胶片": "film photo",
                "MECHA": "mecha cat",
            }
        )
        plugin._configured_astrbot_command_prefixes = lambda: ["#", "!!"]

        self.assertEqual(plugin._match_preset_trigger("#胶片少女"), "胶片少女")
        self.assertEqual(plugin._match_preset_trigger("#胶片少女 参考这张图"), "胶片少女")
        self.assertEqual(plugin._match_preset_trigger("!!胶片少女"), "胶片少女")
        self.assertEqual(plugin._match_preset_trigger("#mecha"), "MECHA")
        self.assertEqual(plugin._match_preset_trigger("#胶片少女风格"), "")
        self.assertEqual(plugin._match_preset_trigger("胶片少女"), "")
        self.assertEqual(plugin._parse_preset_trigger("胶片少女 皮肤白一点", allow_bare=True), ("胶片少女", "皮肤白一点"))
        self.assertEqual(plugin._match_preset_trigger("胶片少女", allow_bare=True), "胶片少女")

    def test_preset_trigger_accepts_actual_local_fullwidth_comma_prefix(self):
        plugin = self._plugin({"胶片少女": "35mm film portrait"})
        plugin._configured_astrbot_command_prefixes = lambda: ["，"]

        self.assertEqual(plugin._match_preset_trigger("，胶片少女"), "胶片少女")
        self.assertEqual(plugin._parse_preset_trigger("胶片少女", allow_bare=True), ("胶片少女", ""))

    def test_preset_trigger_keeps_legacy_slash_prefix_compatibility(self):
        plugin = self._plugin({"胶片少女": "35mm film portrait"})
        plugin._configured_astrbot_command_prefixes = lambda: ["#"]

        self.assertEqual(plugin._match_preset_trigger("/胶片少女"), "胶片少女")

    def test_preset_commands_accept_colon_payload(self):
        plugin = self._plugin({})

        self.assertEqual(
            plugin._extract_command_message_any(self._event("添加预设 胶片少女:35mm film portrait"), ("添加预设",)),
            "胶片少女:35mm film portrait",
        )
        self.assertEqual(plugin._parse_preset_add_payload("胶片少女:35mm film portrait"), ("胶片少女", "35mm film portrait"))
        self.assertEqual(plugin._parse_preset_add_payload("胶片少女：35mm film portrait"), ("胶片少女", "35mm film portrait"))
        self.assertIn("不能包含冒号", plugin._validate_preset_name("坏：名字"))

    def test_preset_generation_prompt_appends_extra_rules(self):
        plugin = self._plugin({})

        self.assertEqual(
            plugin._build_preset_generation_prompt("35mm film portrait", "皮肤白一点"),
            "35mm film portrait\nAdditional requirements: 皮肤白一点",
        )

    def test_config_presets_accept_fullwidth_colon_separator(self):
        config = PluginConfig.from_dict({"presets": ["胶片少女：35mm film portrait"]}, str(PLUGIN_DIR))

        self.assertEqual(config.presets["胶片少女"], "35mm film portrait")

    def test_fast_preset_list_handles_empty_presets(self):
        message = self._plugin({})._build_fast_preset_list_message()

        self.assertIn("当前没有配置极速宏预设", message)

    def test_preset_add_payload_requires_name_and_prompt(self):
        plugin = self._plugin({})

        self.assertEqual(plugin._parse_preset_add_payload("胶片少女 35mm film portrait"), ("胶片少女", "35mm film portrait"))
        self.assertEqual(plugin._parse_preset_add_payload("胶片少女"), ("胶片少女", ""))
        self.assertIn("不能包含冒号", plugin._validate_preset_name("坏:名字"))

    def test_upsert_and_delete_preset_update_runtime_presets(self):
        plugin = self._plugin({"旧预设": "old prompt"})

        def replace_presets(presets):
            plugin.plugin_config = types.SimpleNamespace(presets=dict(presets))

        plugin._replace_presets = replace_presets

        self.assertFalse(plugin._upsert_preset("新预设", "new prompt"))
        self.assertEqual(plugin.plugin_config.presets["新预设"], "new prompt")
        self.assertTrue(plugin._upsert_preset("新预设", "updated prompt"))
        self.assertEqual(plugin.plugin_config.presets["新预设"], "updated prompt")
        self.assertEqual(plugin._delete_preset("新预设"), "新预设")
        self.assertNotIn("新预设", plugin.plugin_config.presets)


class PresetEventHandlerTest(unittest.IsolatedAsyncioTestCase):
    def _plugin(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin.plugin_config = types.SimpleNamespace(
            presets={"胶片少女": "35mm film portrait --size 1024x1024"},
            draw_pending_message="正在生成 {command}: {prompt} 参数{param_count}",
            persona_name="默认助理",
            verbose_report=False,
        )
        plugin.cmd_parser = main_module.CommandParser()
        plugin._permission_denied_message = lambda event: ""
        plugin._image_quota_error_message = lambda event, count=1: ""
        plugin._reserve_image_quota = lambda event, count=1: ("", 0)
        plugin._complete_image_quota = lambda event, reserved, count: setattr(plugin, "_recorded_count", count)
        plugin._release_image_quota = lambda event, reserved: None
        plugin._get_event_images = lambda *args, **kwargs: []
        plugin._process_and_save_images = self._process_refs
        plugin._lease_cache_paths = lambda paths: list(paths or [])
        plugin._release_cache_paths = lambda paths: None
        plugin._recorded_count = 0
        plugin._record_generated_images = lambda event, count=1: setattr(plugin, "_recorded_count", count)
        plugin._build_image_success_components = lambda result, elapsed: [{"result": result.image_url}]
        return plugin

    async def _process_refs(self, refs, session=None):
        return []

    async def test_wake_command_with_prefix_stripped_triggers_preset_generation(self):
        plugin = self._plugin()
        calls = []
        original_client_session = main_module.aiohttp.ClientSession
        original_chain_manager = main_module.ChainManager

        class FakeChainManager:
            def __init__(self, config, session):
                pass

            async def run_chain_with_metadata(self, chain_name, prompt, **kwargs):
                calls.append((chain_name, prompt, kwargs))
                return ChainRunResult(
                    image_url="https://cdn.example.com/preset.png",
                    provider_id="node_1",
                    model=kwargs.get("model", "model_a"),
                    elapsed_seconds=1.0,
                )

        class FakeEvent:
            is_at_or_wake_command = True

            def __init__(self):
                self.message_str = "胶片少女 皮肤白一点 --model test-model"
                self.message_obj = types.SimpleNamespace(message_str=self.message_str, message=[], message_id="msg-1")
                self.stopped = False

            def stop_event(self):
                self.stopped = True

            def plain_result(self, text):
                return ("plain", text)

            def chain_result(self, chain):
                return ("chain", chain)

            async def send(self, result):
                self.sent.append(result)

        event = FakeEvent()
        event.sent = []
        main_module.aiohttp.ClientSession = FakeClientSession
        main_module.ChainManager = FakeChainManager
        try:
            results = [item async for item in plugin.on_message_preset(event)]
        finally:
            main_module.aiohttp.ClientSession = original_client_session
            main_module.ChainManager = original_chain_manager

        self.assertTrue(event.stopped)
        self.assertEqual(plugin._recorded_count, 1)
        self.assertEqual(calls, [
            (
                "text2img",
                "35mm film portrait\nAdditional requirements: 皮肤白一点",
                {"size": "1024x1024", "model": "test-model"},
            )
        ])
        self.assertEqual(event.sent[0][0], "plain")
        self.assertIn("胶片少女", event.sent[0][1])
        self.assertEqual(results, [("chain", [{"result": "https://cdn.example.com/preset.png"}])])


class CommandPendingSendTest(unittest.IsolatedAsyncioTestCase):
    def _plugin(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin.plugin_config = types.SimpleNamespace(
            draw_pending_message="正在生成 {command}: {prompt} 参数{param_count}",
            selfie_pending_message="正在自拍 {command}: {prompt} 参数{param_count}",
            persona_name="默认助手",
            verbose_report=False,
            persona_ref_images=[],
            chains={"selfie": ["selfie_node"]},
        )
        plugin.cmd_parser = main_module.CommandParser()
        plugin.prompt_optimizer = types.SimpleNamespace(
            optimize=lambda prompt, count, session=None: self._optimize(prompt, count)
        )
        plugin.persona_manager = types.SimpleNamespace(
            build_persona_prompt=lambda action: (f"persona base, {action}", {"persona_ref": "persona-default.png"})
        )
        plugin.video_manager = types.SimpleNamespace(background_task_runner=self._video_runner)
        plugin._permission_denied_message = lambda event: ""
        plugin._image_quota_error_message = lambda event, count=1: ""
        plugin._reserve_image_quota = lambda event, count=1: ("", 0)
        plugin._complete_image_quota = lambda event, reserved, count: setattr(plugin, "_recorded_count", count)
        plugin._release_image_quota = lambda event, reserved: None
        plugin._extract_command_message = lambda event, command, fallback: fallback
        plugin._get_event_images = lambda *args, **kwargs: []
        plugin._process_and_save_images = self._process_refs
        plugin._lease_cache_paths = lambda paths: list(paths or [])
        plugin._release_cache_paths = lambda paths: None
        plugin._recorded_count = 0
        plugin._record_generated_images = lambda event, count=1: setattr(plugin, "_recorded_count", count)
        plugin._build_image_success_components = lambda result, elapsed: [{"result": result.image_url}]
        plugin._scheduled_tasks = []

        def create_background_task(coro, **kwargs):
            plugin._scheduled_tasks.append(coro)
            close = getattr(coro, "close", None)
            if callable(close):
                close()

        plugin._create_background_task = create_background_task
        return plugin

    async def _process_refs(self, refs, session=None):
        return []

    async def _optimize(self, prompt, count):
        return [f"optimized {prompt}"]

    async def _video_runner(self, event, prompt, refs, kwargs):
        return None

    class FakeEvent:
        def __init__(self):
            self.message_obj = types.SimpleNamespace(message_str="", message=[], message_id="msg-1")
            self.message_str = ""
            self.sent = []

        def plain_result(self, text):
            return ("plain", text)

        def chain_result(self, chain):
            return ("chain", chain)

        async def send(self, result):
            self.sent.append(result)

    async def test_draw_sends_pending_message_without_yielding_before_chain(self):
        plugin = self._plugin()
        calls = []
        original_client_session = main_module.aiohttp.ClientSession
        original_chain_manager = main_module.ChainManager

        class FakeChainManager:
            def __init__(self, config, session):
                pass

            async def run_chain_with_metadata(self, chain_name, prompt, **kwargs):
                calls.append((chain_name, prompt, kwargs))
                return ChainRunResult(
                    image_url="https://cdn.example.com/draw.png",
                    provider_id="node_1",
                    model=kwargs.get("model", "model_a"),
                    elapsed_seconds=1.0,
                )

        event = self.FakeEvent()
        main_module.aiohttp.ClientSession = FakeClientSession
        main_module.ChainManager = FakeChainManager
        try:
            results = [item async for item in plugin.cmd_draw(event, "海边日落", "--model", "test-model")]
        finally:
            main_module.aiohttp.ClientSession = original_client_session
            main_module.ChainManager = original_chain_manager

        self.assertEqual(event.sent[0][0], "plain")
        self.assertIn("正在生成 画", event.sent[0][1])
        self.assertEqual(calls, [("text2img", "海边日落", {"model": "test-model"})])
        self.assertEqual(results, [("chain", [{"result": "https://cdn.example.com/draw.png"}])])
        self.assertEqual(plugin._recorded_count, 1)

    async def test_selfie_sends_pending_message_without_yielding_before_chain(self):
        plugin = self._plugin()
        calls = []
        original_client_session = main_module.aiohttp.ClientSession
        original_chain_manager = main_module.ChainManager

        class FakeChainManager:
            def __init__(self, config, session):
                pass

            async def run_chain_with_metadata(self, chain_name, prompt, **kwargs):
                calls.append((chain_name, prompt, kwargs))
                return ChainRunResult(
                    image_url="https://cdn.example.com/selfie.png",
                    provider_id="selfie_node",
                    model=kwargs.get("model", "model_a"),
                    elapsed_seconds=1.0,
                )

        event = self.FakeEvent()
        main_module.aiohttp.ClientSession = FakeClientSession
        main_module.ChainManager = FakeChainManager
        try:
            results = [item async for item in plugin.cmd_selfie(event, "挥手", "--model", "test-model")]
        finally:
            main_module.aiohttp.ClientSession = original_client_session
            main_module.ChainManager = original_chain_manager

        self.assertEqual(event.sent[0][0], "plain")
        self.assertIn("正在自拍 自拍", event.sent[0][1])
        self.assertEqual(
            calls,
            [("selfie", "persona base, optimized 挥手", {"persona_ref": "persona-default.png", "model": "test-model"})],
        )
        self.assertEqual(results, [("chain", [{"result": "https://cdn.example.com/selfie.png"}])])
        self.assertEqual(plugin._recorded_count, 1)

    async def test_video_sends_pending_message_then_schedules_background_task(self):
        plugin = self._plugin()
        event = self.FakeEvent()

        results = [item async for item in plugin.cmd_video(event, "城市夜景", "--duration", "5")]

        self.assertEqual(event.sent[0][0], "plain")
        self.assertIn("视频任务已提交后台渲染", event.sent[0][1])
        self.assertEqual(results, [])
        self.assertEqual(len(plugin._scheduled_tasks), 1)

    async def test_pending_send_failure_does_not_abort_draw_generation(self):
        plugin = self._plugin()
        calls = []
        original_client_session = main_module.aiohttp.ClientSession
        original_chain_manager = main_module.ChainManager

        class FakeChainManager:
            def __init__(self, config, session):
                pass

            async def run_chain_with_metadata(self, chain_name, prompt, **kwargs):
                calls.append((chain_name, prompt, kwargs))
                return ChainRunResult(
                    image_url="https://cdn.example.com/draw.png",
                    provider_id="node_1",
                    model="model_a",
                    elapsed_seconds=1.0,
                )

        class FailingSendEvent(self.FakeEvent):
            async def send(self, result):
                raise RuntimeError("send failed")

        event = FailingSendEvent()
        main_module.aiohttp.ClientSession = FakeClientSession
        main_module.ChainManager = FakeChainManager
        try:
            results = [item async for item in plugin.cmd_draw(event, "海边日落")]
        finally:
            main_module.aiohttp.ClientSession = original_client_session
            main_module.ChainManager = original_chain_manager

        self.assertEqual(len(calls), 1)
        self.assertEqual(results, [("chain", [{"result": "https://cdn.example.com/draw.png"}])])


class ChainManagerMetadataTest(unittest.IsolatedAsyncioTestCase):
    async def test_chain_result_uses_actual_successful_provider_metadata(self):
        config = PluginConfig.from_dict(
            {
                "providers": [
                    {
                        "id": "primary",
                        "api_type": "openai_image",
                        "base_url": "https://api.example.com/v1",
                        "api_keys": "key-1",
                        "model": "primary-model",
                    },
                    {
                        "id": "backup",
                        "api_type": "openai_image",
                        "base_url": "https://api.example.com/v1",
                        "api_keys": "key-2",
                        "model": "backup-model",
                    },
                ],
                "router_config": {"chain_text2img": "primary,backup"},
            },
            str(PLUGIN_DIR),
        )
        calls = []

        class FakeProvider:
            def __init__(self, provider_config):
                self.provider_config = provider_config

            async def generate_image(self, prompt, **kwargs):
                calls.append((self.provider_config.id, prompt, kwargs))
                if self.provider_config.id == "primary":
                    raise RuntimeError("primary failed")
                return "https://cdn.example.com/out.png"

        original_create_provider = chain_manager_module.create_provider
        chain_manager_module.create_provider = lambda provider_config, session: FakeProvider(provider_config)
        try:
            manager = ChainManager(config, session=object())
            result = await manager.run_chain_with_metadata(
                "text2img",
                "draw a cat",
                size="1024x1024",
                model="override-model",
            )

            self.assertEqual(result.image_url, "https://cdn.example.com/out.png")
            self.assertEqual(result.provider_id, "backup")
            self.assertEqual(result.model, "override-model")
            self.assertGreaterEqual(result.elapsed_seconds, 0)
            self.assertEqual([call[0] for call in calls], ["primary", "backup"])
            self.assertEqual(calls[0][2]["size"], "1024x1024")
            self.assertEqual(calls[1][2]["size"], "1024x1024")
            self.assertEqual(await manager.run_chain("text2img", "draw a cat"), "https://cdn.example.com/out.png")
        finally:
            chain_manager_module.create_provider = original_create_provider

    async def test_provider_default_size_is_used_when_request_omits_size(self):
        config = PluginConfig.from_dict(
            {
                "providers": [
                    {
                        "id": "primary",
                        "api_type": "openai_image",
                        "base_url": "https://api.example.com/v1",
                        "api_keys": "key-1",
                        "model": "primary-model",
                        "default_size": "1536x1024",
                    }
                ],
                "router_config": {"chain_text2img": "primary"},
            },
            str(PLUGIN_DIR),
        )
        calls = []

        class FakeProvider:
            async def generate_image(self, prompt, **kwargs):
                calls.append(kwargs)
                return "https://cdn.example.com/out.png"

        original_create_provider = chain_manager_module.create_provider
        chain_manager_module.create_provider = lambda provider_config, session: FakeProvider()
        try:
            manager = ChainManager(config, session=object())
            await manager.run_chain_with_metadata("text2img", "draw a cat")
            await manager.run_chain_with_metadata("text2img", "draw a cat", size="1024x1024")
            await manager.run_chain_with_metadata("text2img", "draw a cat", resolution="2048x2048")

            self.assertEqual(calls[0]["size"], "1536x1024")
            self.assertEqual(calls[1]["size"], "1024x1024")
            self.assertNotIn("size", calls[2])
            self.assertEqual(calls[2]["resolution"], "2048x2048")
        finally:
            chain_manager_module.create_provider = original_create_provider

    async def test_backup_provider_uses_its_own_default_size(self):
        config = PluginConfig.from_dict(
            {
                "providers": [
                    {
                        "id": "primary",
                        "api_type": "openai_image",
                        "base_url": "https://api.example.com/v1",
                        "api_keys": "key-1",
                        "model": "primary-model",
                        "default_size": "1024x1024",
                    },
                    {
                        "id": "backup",
                        "api_type": "openai_image",
                        "base_url": "https://api.example.com/v1",
                        "api_keys": "key-2",
                        "model": "backup-model",
                        "default_size": "1536x1024",
                    },
                ],
                "router_config": {"chain_text2img": "primary,backup"},
            },
            str(PLUGIN_DIR),
        )
        calls = []

        class FakeProvider:
            def __init__(self, provider_config):
                self.provider_config = provider_config

            async def generate_image(self, prompt, **kwargs):
                calls.append((self.provider_config.id, kwargs))
                if self.provider_config.id == "primary":
                    raise RuntimeError("primary failed")
                return "https://cdn.example.com/out.png"

        original_create_provider = chain_manager_module.create_provider
        chain_manager_module.create_provider = lambda provider_config, session: FakeProvider(provider_config)
        try:
            manager = ChainManager(config, session=object())
            result = await manager.run_chain_with_metadata("text2img", "draw a cat")

            self.assertEqual(result.provider_id, "backup")
            self.assertEqual(calls[0], ("primary", {"size": "1024x1024"}))
            self.assertEqual(calls[1], ("backup", {"size": "1536x1024"}))
        finally:
            chain_manager_module.create_provider = original_create_provider

    async def test_gemini_chain_allows_default_base_url(self):
        config = PluginConfig.from_dict(
            {
                "providers": [
                    {
                        "id": "gemini",
                        "api_type": "gemini_official",
                        "base_url": "",
                        "api_keys": "key-1",
                        "model": "",
                    }
                ],
                "router_config": {"chain_text2img": "gemini"},
            },
            str(PLUGIN_DIR),
        )
        calls = []

        class FakeProvider:
            async def generate_image(self, prompt, **kwargs):
                calls.append((prompt, kwargs))
                return "data:image/png;base64," + _long_b64()

        original_create_provider = chain_manager_module.create_provider
        chain_manager_module.create_provider = lambda provider_config, session: FakeProvider()
        try:
            manager = ChainManager(config, session=object())
            result = await manager.run_chain_with_metadata("text2img", "draw a cat")

            self.assertTrue(result.image_url.startswith("data:image/png;base64,"))
            self.assertEqual(result.provider_id, "gemini")
            self.assertEqual(result.model, "gemini-3.1-flash-image")
            self.assertEqual(calls, [("draw a cat", {})])
        finally:
            chain_manager_module.create_provider = original_create_provider


class VideoSuccessMetadataTest(unittest.TestCase):
    def test_success_text_respects_metadata_toggles(self):
        config = PluginConfig.from_dict(
            {"show_generation_time": True, "show_request_model": False},
            str(PLUGIN_DIR),
        )
        text = VideoManager(config)._build_success_text(65.2, "veo-3")

        self.assertIn("生成耗时", text)
        self.assertIn("65.2s", text)
        self.assertNotIn("请求模型", text)
        self.assertNotIn("veo-3", text)

        config = PluginConfig.from_dict(
            {"show_generation_time": False, "show_request_model": True},
            str(PLUGIN_DIR),
        )
        manager = VideoManager(config)
        provider = ProviderConfig(
            id="video_node",
            api_type="async_task",
            base_url="https://api.example.com/v1",
            api_keys=["key"],
            model="veo-3",
            timeout=300.0,
        )
        text = manager._build_success_text(
            65.2,
            manager._effective_request_model(provider, {"model": "video-override"}),
        )

        self.assertNotIn("生成耗时", text)
        self.assertIn("请求模型：video-override", text)

    def test_success_text_can_hide_metadata_for_llm_tools(self):
        config = PluginConfig.from_dict(
            {"show_generation_time": True, "show_request_model": True},
            str(PLUGIN_DIR),
        )
        text = VideoManager(config)._build_success_text(65.2, "veo-3", include_metadata=False)

        self.assertNotIn("生成耗时", text)
        self.assertNotIn("请求模型", text)
        self.assertNotIn("veo-3", text)


    def test_video_provider_default_size_is_used_when_request_omits_size(self):
        config = PluginConfig.from_dict(
            {"video_providers": [{"id": "video_node", "default_size": "1280x720"}]},
            str(PLUGIN_DIR),
        )
        manager = VideoManager(config)
        provider = config.video_providers[0]

        self.assertEqual(manager._apply_provider_defaults(provider, {})["size"], "1280x720")
        self.assertEqual(manager._apply_provider_defaults(provider, {"size": "1920x1080"})["size"], "1920x1080")
        self.assertEqual(manager._apply_provider_defaults(provider, {"resolution": "720p"}), {"resolution": "720p"})


class GeminiOfficialProviderTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fake_logger.messages.clear()

    def _provider(self, response_payload, base_url="", status=200):
        config = ProviderConfig(
            id="gemini_node",
            api_type="gemini_official",
            base_url=base_url,
            api_keys=["gemini-key"],
            model="gemini-3.1-flash-image-preview",
            timeout=120.0,
        )
        session = FakeSession(FakeResponse(response_payload, status=status))
        return GeminiOfficialProvider(config, session), session

    def _gemini_response(self, mime_type="image/png"):
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "created"},
                            {"inlineData": {"mimeType": mime_type, "data": _long_b64()}},
                        ]
                    },
                    "finishReason": "STOP",
                }
            ]
        }

    async def test_posts_generate_content_to_default_google_endpoint(self):
        provider, session = self._provider(self._gemini_response("image/webp"))

        result = await provider.generate_image("draw a cat", size="1024x1024")

        self.assertTrue(result.startswith("data:image/webp;base64,"))
        self.assertEqual(
            session.posts[0]["url"],
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image-preview:generateContent",
        )
        headers = session.posts[0]["headers"]
        self.assertEqual(headers["x-goog-api-key"], "gemini-key")
        self.assertNotIn("Authorization", headers)
        payload = session.posts[0]["json"]
        self.assertEqual(payload["contents"][0]["role"], "user")
        self.assertEqual(payload["contents"][0]["parts"][0]["text"], "draw a cat")
        self.assertEqual(payload["generationConfig"]["responseModalities"], ["TEXT", "IMAGE"])
        self.assertEqual(payload["generationConfig"]["imageConfig"]["aspectRatio"], "1:1")
        self.assertNotIn("size", payload)

    async def test_size_mapping_supports_wide_official_aspect_ratios(self):
        provider, session = self._provider(self._gemini_response())

        await provider.generate_image("wide scene", size="2560x1080")

        payload = session.posts[0]["json"]
        self.assertEqual(payload["generationConfig"]["imageConfig"]["aspectRatio"], "21:9")

    async def test_reference_image_uses_official_inline_data_part(self):
        provider, session = self._provider(self._gemini_response())
        jpeg_b64 = base64.b64encode(b"\xff\xd8\xff\xe0" + b"jpeg-bytes" * 20).decode("ascii")
        reference = "data:image/jpeg;base64," + jpeg_b64

        await provider.generate_image("edit a cat", user_refs=[reference])

        parts = session.posts[0]["json"]["contents"][0]["parts"]
        self.assertEqual(parts[0]["text"], "edit a cat")
        self.assertEqual(parts[1]["inlineData"]["mimeType"], "image/jpeg")
        self.assertEqual(parts[1]["inlineData"]["data"], jpeg_b64)

    async def test_preserves_full_generate_content_endpoint(self):
        endpoint = "https://generativelanguage.googleapis.com/v1beta/models/custom-image:generateContent"
        provider, session = self._provider(self._gemini_response(), base_url=endpoint)

        await provider.generate_image("draw a cat")

        self.assertEqual(session.posts[0]["url"], endpoint)

    async def test_text_only_gemini_response_is_reported_as_missing_image(self):
        provider, _ = self._provider(
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "I cannot create that image."}]},
                        "finishReason": "SAFETY",
                    }
                ]
            }
        )

        with self.assertRaisesRegex(ValueError, "未返回图片数据"):
            await provider.generate_image("draw a cat")


class CustomEndpointProviderTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fake_logger.messages.clear()

    def _provider(self, endpoint, response_payload, provider_cls=CustomEndpointProvider, status=200):
        if provider_cls is CustomEndpointProvider:
            api_type = "custom_endpoint"
        elif provider_cls is GeminiOfficialProvider:
            api_type = "gemini_official"
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
        ref2 = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"ref-2" * 30).decode("ascii")
        ref3 = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"ref-3" * 30).decode("ascii")

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
        ref2 = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"ref-2" * 30).decode("ascii")

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
        raw_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"provider-raw-image" * 35).decode("ascii")
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


class SecurityAndLimitRegressionTest(unittest.IsolatedAsyncioTestCase):
    def test_cache_page_stats_do_not_expose_filesystem_paths(self):
        plugin = object.__new__(OmniDrawPlugin)
        with tempfile.TemporaryDirectory() as temp_dir:
            plugin.data_dir = temp_dir
            cache_dir = Path(temp_dir) / "temp_images"
            cache_dir.mkdir(parents=True)
            (cache_dir / "sample.png").write_bytes(b"\x89PNG\r\n\x1a\n")

            stats = plugin._cache_stats_for_page()

        self.assertNotIn("path", stats["dirs"]["temp_images"])
        self.assertEqual(stats["dirs"]["temp_images"]["count"], 1)

    def test_main_image_magic_rejects_mp4_ftyp_and_accepts_avif(self):
        plugin = object.__new__(OmniDrawPlugin)

        self.assertFalse(plugin._looks_like_image_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 20))
        self.assertTrue(plugin._looks_like_image_bytes(b"\x00\x00\x00\x18ftypavif" + b"\x00" * 20))

    def test_legacy_provider_api_keys_are_migrated_masked_and_restored(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin._page_image_tokens = {}
        legacy_config = {
            "providers": [{"id": "image-node", "API密钥": "legacy-image-secret"}],
            "video_providers": [{"id": "video-node", "API密钥": ["legacy-video-secret"]}],
        }

        plugin.raw_config = plugin._clean_runtime_config(legacy_config)
        self.assertEqual(plugin.raw_config["providers"][0]["api_keys"], "legacy-image-secret")
        self.assertEqual(plugin.raw_config["video_providers"][0]["api_keys"], ["legacy-video-secret"])
        self.assertNotIn("API密钥", plugin.raw_config["providers"][0])
        self.assertNotIn("API密钥", plugin.raw_config["video_providers"][0])

        page_config = plugin._config_for_page()
        serialized_page = json.dumps(page_config, ensure_ascii=False)
        self.assertNotIn("legacy-image-secret", serialized_page)
        self.assertNotIn("legacy-video-secret", serialized_page)
        self.assertNotIn("API密钥", serialized_page)

        plugin._restore_masked_api_keys(page_config)
        self.assertEqual(page_config["providers"][0]["api_keys"], ["legacy-image-secret"])
        self.assertEqual(page_config["video_providers"][0]["api_keys"], ["legacy-video-secret"])

    def test_canonical_empty_api_keys_do_not_resurrect_legacy_secret(self):
        plugin = object.__new__(OmniDrawPlugin)

        cleaned = plugin._clean_runtime_config({
            "providers": [{"id": "image-node", "api_keys": [], "API密钥": "stale-secret"}],
        })

        self.assertEqual(cleaned["providers"][0]["api_keys"], [])
        self.assertNotIn("API密钥", cleaned["providers"][0])

    def test_command_error_message_redacts_sensitive_exception_text(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin.plugin_config = types.SimpleNamespace(
            draw_error_message="绘制失败: {error}",
            selfie_error_message="自拍失败: {error}",
            persona_name="默认助理",
        )
        secret = "AIza-command-secret-123456789"

        message = plugin._build_command_error_message(
            "cmd_draw",
            RuntimeError(f"request failed: https://api.example.com/run?key={secret}&size=1"),
        )

        self.assertNotIn(secret, message)
        self.assertIn("key=<redacted>", message)

        timeout_message = plugin._build_command_error_message(
            "cmd_draw",
            asyncio.TimeoutError(),
            error_kind="timeout",
        )
        self.assertIn("操作超时", timeout_message)

    async def test_llm_image_tools_redact_sensitive_errors_in_non_result_mode(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin._permission_denied_message = lambda event: ""
        plugin._normalize_count = lambda count: 1
        plugin._reserve_image_quota = lambda event, count: ("", 1)
        plugin._release_image_quota = lambda event, count: None
        secret = "sk-tool-secret-123456789"

        async def fail_generation(*args, **kwargs):
            raise RuntimeError(f"Authorization: Bearer {secret}")

        plugin._run_text2img_generation = fail_generation
        plugin._run_selfie_generation = fail_generation

        image_message = await plugin.tool_generate_image(object(), "draw a cat")
        selfie_message = await plugin.tool_generate_selfie(object(), "look at camera")

        self.assertNotIn(secret, image_message)
        self.assertNotIn(secret, selfie_message)
        self.assertIn("<redacted>", image_message)
        self.assertIn("<redacted>", selfie_message)

    def test_page_config_masks_and_restores_api_keys(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin.raw_config = {
            "providers": [{"id": "node_1", "api_keys": ["secret-key-one", "secret-key-two"]}],
            "video_providers": [],
        }
        page_config = json.loads(json.dumps(plugin.raw_config))

        plugin._mask_config_api_keys(page_config)

        masked = page_config["providers"][0]["api_keys"]
        self.assertNotIn("secret-key-one", masked)
        self.assertNotIn("secret-key-two", masked)
        self.assertTrue(page_config["providers"][0]["api_keys_configured"])

        payload = {"providers": [{"id": "node_1", "api_keys": masked}]}
        plugin._restore_masked_api_keys(payload)
        self.assertEqual(payload["providers"][0]["api_keys"], ["secret-key-one", "secret-key-two"])

    def test_page_config_restores_reordered_and_deleted_masked_api_keys_by_suffix(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin.raw_config = {
            "providers": [{
                "id": "node_1",
                "api_keys": ["secret-key-1111", "secret-key-2222", "secret-key-3333"],
            }],
            "video_providers": [],
        }

        payload = {"providers": [{
            "id": "node_1",
            "api_keys": "\n".join([
                plugin._mask_api_key("secret-key-3333"),
                plugin._mask_api_key("secret-key-1111"),
            ]),
        }]}
        plugin._restore_masked_api_keys(payload)

        self.assertEqual(
            payload["providers"][0]["api_keys"],
            ["secret-key-3333", "secret-key-1111"],
        )

    def test_page_config_restores_duplicate_mask_suffixes_without_reusing_old_key(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin.raw_config = {
            "providers": [{
                "id": "node_1",
                "api_keys": ["first-secret-same", "second-secret-same"],
            }],
            "video_providers": [],
        }

        payload = {"providers": [{
            "id": "node_1",
            "api_keys": "\n".join([
                plugin._mask_api_key("first-secret-same"),
                plugin._mask_api_key("second-secret-same"),
            ]),
        }]}
        plugin._restore_masked_api_keys(payload)

        self.assertEqual(
            payload["providers"][0]["api_keys"],
            ["first-secret-same", "second-secret-same"],
        )

    def test_native_config_refresh_persists_previous_config_when_runtime_apply_fails(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin._config_lock = threading.RLock()
        plugin._native_config_path = "native-config.json"
        plugin._native_config_signature = "old-signature"
        plugin._native_config_mtime = 1.0
        plugin._native_config = None
        plugin.raw_config = {"verbose_report": False}
        plugin.plugin_config = object()
        plugin.persona_manager = object()
        plugin.video_manager = object()
        plugin.prompt_optimizer = object()
        persisted = []

        plugin._get_mtime = lambda path: 2.0
        plugin._file_signature = lambda path: "new-signature"
        plugin._load_json_file = lambda path: {"verbose_report": True}
        plugin._clean_runtime_config = lambda config: dict(config)
        plugin._prepare_runtime_config = lambda config: dict(config)
        plugin._persist_config = lambda: persisted.append(dict(plugin.raw_config))

        def fail_apply(config):
            raise RuntimeError("apply failed")

        plugin._apply_runtime_config = fail_apply

        with self.assertRaisesRegex(RuntimeError, "apply failed"):
            plugin._refresh_from_native_config_if_changed()

        self.assertEqual(plugin.raw_config, {"verbose_report": False})
        self.assertEqual(
            persisted,
            [{"verbose_report": True}, {"verbose_report": False}],
        )
        self.assertEqual(plugin._native_config_signature, "old-signature")
        self.assertEqual(plugin._native_config_mtime, 1.0)

    def test_empty_newer_native_config_does_not_replace_persisted_payload_at_startup(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin._sync_native_active_persona_upload = lambda config: None

        with tempfile.TemporaryDirectory() as temp_dir:
            native_path = Path(temp_dir) / "native.json"
            persisted_path = Path(temp_dir) / "persisted.json"
            native_path.write_text("{}", encoding="utf-8")
            persisted_config = {
                "providers": [{"id": "node_1", "api_keys": ["secret-key"]}],
            }
            persisted_path.write_text(json.dumps(persisted_config), encoding="utf-8")
            plugin._native_config_path = str(native_path)
            plugin.config_path = str(persisted_path)
            plugin._native_config_mtime = 2.0
            plugin._persist_config_mtime = 1.0

            loaded = plugin._load_initial_config({})

        self.assertEqual(loaded, persisted_config)

    def test_newer_native_config_with_payload_replaces_persisted_payload_at_startup(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin._sync_native_active_persona_upload = lambda config: None
        native_config = {
            "providers": [{"id": "native-node", "api_keys": ["native-secret"]}],
        }
        persisted_config = {
            "providers": [{"id": "persisted-node", "api_keys": ["persisted-secret"]}],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            native_path = Path(temp_dir) / "native.json"
            persisted_path = Path(temp_dir) / "persisted.json"
            native_path.write_text(json.dumps(native_config), encoding="utf-8")
            persisted_path.write_text(json.dumps(persisted_config), encoding="utf-8")
            plugin._native_config_path = str(native_path)
            plugin.config_path = str(persisted_path)
            plugin._native_config_mtime = 2.0
            plugin._persist_config_mtime = 1.0

            loaded = plugin._load_initial_config(native_config)

        self.assertEqual(loaded, native_config)

    def test_page_preview_rejects_local_files_outside_plugin_data_dir(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin.data_dir = str(PLUGIN_DIR / ".pytest_cache" / "page_security" / "plugin_data")
        plugin._page_image_tokens = {}
        inside = Path(plugin.data_dir) / "persona_refs" / "inside.png"
        outside = PLUGIN_DIR / ".pytest_cache" / "page_security" / "outside.png"
        inside.parent.mkdir(parents=True, exist_ok=True)
        outside.parent.mkdir(parents=True, exist_ok=True)
        image_bytes = b"\x89PNG\r\n\x1a\n" + b"test-image"
        inside.write_bytes(image_bytes)
        outside.write_bytes(image_bytes)

        self.assertTrue(plugin._image_ref_for_page(str(inside)).startswith("data:image/png;base64,"))
        self.assertEqual(plugin._image_ref_for_page(str(outside)), "")

    def test_quota_reservation_blocks_concurrent_overcommit(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin.plugin_config = types.SimpleNamespace(enable_daily_limit=True, daily_image_limit=2)
        plugin._usage_stats = {"date": plugin._today_key(), "total": 0, "users": {}}
        plugin._quota_reservations = {}
        plugin._usage_lock = threading.RLock()
        plugin._access_status = lambda event, refresh=True: {
            "user_id": "user-1",
            "group_id": "",
            "allowed": True,
            "unlimited": False,
            "level": "limited",
            "reason": "",
        }
        plugin._get_event_user_id = lambda event: "user-1"
        plugin._permission_denied_message = lambda event: ""

        error, reserved = plugin._reserve_image_quota(object(), 2)
        self.assertEqual(error, "")
        self.assertEqual(reserved, 2)
        error, reserved = plugin._reserve_image_quota(object(), 1)
        self.assertIn("额度不足", error)
        self.assertEqual(reserved, 0)
        plugin._release_image_quota(object(), 2)
        self.assertEqual(plugin._reserve_image_quota(object(), 1), ("", 1))

    async def test_provider_rejects_loopback_reference_before_request(self):
        config = ProviderConfig(
            id="node_1",
            api_type="openai_image",
            base_url="https://api.example.com/v1",
            api_keys=["key-1"],
            model="image-model",
            timeout=30.0,
        )
        session = FakeSession(FakeResponse({"data": [{"url": "https://cdn.example.com/out.png"}]}))
        provider = OpenAIProvider(config, session)

        with self.assertRaisesRegex(RuntimeError, "不允许访问"):
            await provider.generate_image("draw a cat", user_refs=["http://127.0.0.1/ref.png"])
        self.assertEqual(session.gets, [])

    async def test_provider_rejects_plain_text_mislabeled_as_image(self):
        config = ProviderConfig(
            id="node_1",
            api_type="openai_image",
            base_url="https://api.example.com/v1",
            api_keys=["key-1"],
            model="image-model",
            timeout=30.0,
        )
        session = FakeSession(FakeResponse({"data": [{"url": "https://cdn.example.com/out.png"}]}))
        provider = OpenAIProvider(config, session)
        reference = "data:image/png;base64," + base64.b64encode(b"plain text").decode("ascii")

        with self.assertRaisesRegex(RuntimeError, "不是支持的图片格式"):
            await provider.generate_image("draw a cat", user_refs=[reference])
        self.assertEqual(session.posts, [])

    async def test_openai_chat_non_success_response_honors_body_limit(self):
        config = ProviderConfig(
            id="chat-node",
            api_type="openai_chat",
            base_url="https://api.example.com/v1",
            api_keys=["key-1"],
            model="chat-image-model",
            timeout=30.0,
        )
        response = FakeResponse({"error": {"message": "too large"}}, status=400)
        response.headers = {"Content-Length": str(base_module.MAX_PROVIDER_RESPONSE_BYTES + 1)}
        provider = OpenAIChatProvider(config, FakeSession(response))

        with self.assertRaisesRegex(RuntimeError, "响应体超过"):
            await provider.generate_image("draw a cat")

    async def test_custom_image_json_endpoint_rejects_more_than_three_refs(self):
        endpoint = "https://api.example.com/v1/images/generations"
        config = ProviderConfig(
            id="custom_node",
            api_type="custom_endpoint",
            base_url=endpoint,
            api_keys=["key-1"],
            model="image-model",
            timeout=30.0,
        )
        session = FakeSession(FakeResponse({"data": [{"url": "https://cdn.example.com/out.png"}]}))
        provider = CustomEndpointProvider(config, session)
        refs = [
            "data:image/png;base64," + base64.b64encode(f"image-{index}".encode() * 20).decode("ascii")
            for index in range(4)
        ]

        with self.assertRaisesRegex(ValueError, "最多支持 3 张"):
            await provider.generate_image("edit a cat", user_refs=refs)
        self.assertEqual(session.posts, [])

    def test_provider_filter_blocks_underscore_image_fields(self):
        filtered = base_module.filter_provider_api_kwargs(
            {"image_1": "secret", "image2": "secret", "size": "1024x1024"},
            "node_1",
        )
        self.assertEqual(filtered, {"size": "1024x1024"})

    def test_api_key_rotation_scope_is_isolated_by_provider_id(self):
        scope = "image:openai_image:https://api.example.com/v1"

        self.assertEqual(base_module.next_api_key("node-a", ["a1", "a2"], scope=scope), "a1")
        self.assertEqual(base_module.next_api_key("node-b", ["b1", "b2"], scope=scope), "b1")
        self.assertEqual(base_module.next_api_key("node-a", ["a1", "a2"], scope=scope), "a2")
        self.assertEqual(base_module.next_api_key("node-b", ["b1", "b2"], scope=scope), "b2")

    def test_cache_cleanup_skips_leased_reference_file(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin.data_dir = str(PLUGIN_DIR / ".pytest_cache" / "lease_security")
        plugin._cache_lease_lock = threading.RLock()
        plugin._cache_leases = {}
        image_path = Path(plugin.data_dir) / "user_refs" / "leased.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"\x89PNG\r\n\x1a\nleased")
        item = {
            "cache_name": "user_refs",
            "path": str(image_path),
            "bytes": image_path.stat().st_size,
            "mtime": image_path.stat().st_mtime,
        }

        lease = plugin._lease_cache_paths([str(image_path)])
        result = plugin._delete_cache_files([item], reason="test")
        self.assertEqual(result["deleted_count"], 0)
        self.assertTrue(image_path.exists())

        plugin._release_cache_paths(lease)
        result = plugin._delete_cache_files([item], reason="test")
        self.assertEqual(result["deleted_count"], 1)
        self.assertFalse(image_path.exists())

    def test_cache_cleanup_rechecks_lease_acquired_after_initial_snapshot(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin.data_dir = str(PLUGIN_DIR / ".pytest_cache" / "lease_race_security")
        plugin._cache_lease_lock = threading.RLock()
        plugin._cache_leases = {}
        image_path = Path(plugin.data_dir) / "user_refs" / "leased-late.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"\x89PNG\r\n\x1a\nleased-late")
        item = {
            "cache_name": "user_refs",
            "path": str(image_path),
            "bytes": image_path.stat().st_size,
            "mtime": image_path.stat().st_mtime,
        }
        acquired_lease = []

        def delayed_items():
            acquired_lease.extend(plugin._lease_cache_paths([str(image_path)]))
            yield item

        try:
            result = plugin._delete_cache_files(delayed_items(), reason="test")
            self.assertEqual(result["deleted_count"], 0)
            self.assertEqual(result["skipped_count"], 1)
            self.assertTrue(image_path.exists())
        finally:
            plugin._release_cache_paths(acquired_lease)
            image_path.unlink(missing_ok=True)

    async def test_video_submit_and_poll_reuse_same_api_key(self):
        provider = ProviderConfig(
            id="video-key-lifecycle",
            api_type="async_task",
            base_url="https://api.example.com/v1",
            api_keys=["key-a", "key-b"],
            model="video-model",
            timeout=30.0,
        )

        class SequencedSession:
            def __init__(self):
                self.posts = []
                self.gets = []

            def post(self, url, **kwargs):
                self.posts.append({"url": url, **kwargs})
                return FakePost(FakeResponse({"id": "task-1"}))

            def get(self, url, **kwargs):
                self.gets.append({"url": url, **kwargs})
                return FakePost(FakeResponse({"status": "SUCCESS", "url": "https://cdn.example.com/out.mp4"}))

        session = SequencedSession()
        manager = VideoManager(types.SimpleNamespace())

        result = await manager._fetch_video_from_api(provider, "make a video", session)

        self.assertEqual(result, "https://cdn.example.com/out.mp4")
        self.assertEqual(session.posts[0]["headers"]["Authorization"], "Bearer key-a")
        self.assertEqual(session.gets[0]["headers"]["Authorization"], "Bearer key-a")


class ReliabilityBoundaryRegressionTest(unittest.IsolatedAsyncioTestCase):
    def _quota_plugin(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin.plugin_config = types.SimpleNamespace(enable_daily_limit=True, daily_image_limit=2)
        plugin._usage_stats = {"date": plugin._today_key(), "total": 0, "users": {}}
        plugin._quota_reservations = {}
        plugin._usage_lock = threading.RLock()
        plugin._access_status = lambda event, refresh=True: {
            "user_id": "user-1",
            "group_id": "",
            "allowed": True,
            "unlimited": False,
            "level": "limited",
            "reason": "",
        }
        plugin._get_event_user_id = lambda event: "user-1"
        plugin._permission_denied_message = lambda event: ""
        return plugin

    def test_quota_reservation_is_atomic_under_real_thread_contention(self):
        plugin = self._quota_plugin()
        start = threading.Barrier(3)
        results = []
        failures = []
        result_lock = threading.Lock()

        def reserve():
            try:
                start.wait(timeout=5)
                result = plugin._reserve_image_quota(object(), 2)
                with result_lock:
                    results.append(result)
            except BaseException as exc:
                with result_lock:
                    failures.append(exc)

        workers = [threading.Thread(target=reserve) for _ in range(2)]
        for worker in workers:
            worker.start()
        start.wait(timeout=5)
        for worker in workers:
            worker.join(timeout=5)

        self.assertFalse(failures)
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(sorted(reserved for _, reserved in results), [0, 2])
        self.assertEqual(sum(1 for message, _ in results if not message), 1)
        self.assertEqual(sum(1 for message, _ in results if "额度不足" in message), 1)

    async def test_plugin_generation_releases_quota_reservation_when_cancelled(self):
        plugin = self._quota_plugin()
        plugin.plugin_config.max_batch_count = 2
        plugin._refresh_from_native_config_if_changed = lambda: None
        plugin._validated_plugin_image_refs = lambda refs, allow_local_refs=False: []

        async def cancel_generation(*args, **kwargs):
            raise asyncio.CancelledError()

        plugin._run_text2img_generation = cancel_generation

        with self.assertRaises(asyncio.CancelledError):
            await plugin.generate_images_for_plugin(
                prompt="draw a cat",
                event=object(),
                record_usage=True,
            )

        self.assertEqual(plugin._quota_reservations, {})

    async def test_chat_generation_handlers_release_reservation_when_cancelled(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin.plugin_config = types.SimpleNamespace(
            presets={"胶片少女": "35mm film portrait"},
            draw_pending_message="pending",
            selfie_pending_message="pending",
            persona_name="默认助理",
            persona_ref_images=[],
            chains={"selfie": ["selfie-node"]},
            verbose_report=False,
        )
        plugin.cmd_parser = main_module.CommandParser()
        plugin._permission_denied_message = lambda event: ""
        plugin._reserve_image_quota = lambda event, count: ("", 1)
        released = []
        plugin._release_image_quota = lambda event, count: released.append(count)
        plugin._get_event_text = lambda event: "胶片少女"
        plugin._event_is_at_or_wake_command = lambda event: True
        plugin._get_event_images = lambda *args, **kwargs: ["reference"]
        plugin._extract_command_message = lambda event, command, fallback="": fallback or "prompt"
        plugin.prompt_optimizer = types.SimpleNamespace(
            optimize=lambda prompt, count, session=None: self._return_prompts(prompt)
        )
        plugin.persona_manager = types.SimpleNamespace(
            build_persona_prompt=lambda prompt: (prompt, {})
        )

        async def cancel_reference_processing(*args, **kwargs):
            raise asyncio.CancelledError()

        plugin._process_and_save_images = cancel_reference_processing

        async def consume(generator):
            async for _ in generator:
                pass

        handlers = (
            plugin.on_message_preset(object()),
            plugin.cmd_draw(object(), "prompt"),
            plugin.cmd_selfie(object(), "prompt"),
        )
        for handler in handlers:
            with self.assertRaises(asyncio.CancelledError):
                await consume(handler)

        self.assertEqual(released, [1, 1, 1])

    async def _return_prompts(self, prompt):
        return [prompt]

    async def test_llm_image_tools_release_reservation_when_cancelled(self):
        plugin = self._quota_plugin()
        plugin.plugin_config.max_batch_count = 2

        async def cancel_generation(*args, **kwargs):
            raise asyncio.CancelledError()

        plugin._run_text2img_generation = cancel_generation
        plugin._run_selfie_generation = cancel_generation

        with self.assertRaises(asyncio.CancelledError):
            await plugin.tool_generate_image(object(), "draw a cat")
        self.assertEqual(plugin._quota_reservations, {})

        with self.assertRaises(asyncio.CancelledError):
            await plugin.tool_generate_selfie(object(), "look at camera")
        self.assertEqual(plugin._quota_reservations, {})

    async def test_config_apply_failure_restores_memory_and_persisted_file(self):
        plugin = object.__new__(OmniDrawPlugin)
        old_config = {"verbose_report": False, "providers": []}
        old_runtime = tuple(object() for _ in range(4))

        with tempfile.TemporaryDirectory() as temp_dir:
            plugin.data_dir = temp_dir
            plugin.config_path = str(Path(temp_dir) / "omnidraw_persist_config.json")
            plugin._config_lock = threading.RLock()
            plugin._persist_config_mtime = 0.0
            plugin.raw_config = json.loads(json.dumps(old_config))
            (
                plugin.plugin_config,
                plugin.persona_manager,
                plugin.video_manager,
                plugin.prompt_optimizer,
            ) = old_runtime
            plugin._persist_config()

            plugin._normalize_saved_page_images = lambda config: None
            plugin._prepare_runtime_config = lambda config: config
            plugin._safe_update_context_config = lambda: None

            def fail_apply(candidate):
                plugin.plugin_config = object()
                plugin.persona_manager = object()
                raise RuntimeError("apply failed")

            plugin._apply_runtime_config = fail_apply

            async def get_json(*args, **kwargs):
                return {"verbose_report": True}

            original_request = main_module.request
            main_module.request = types.SimpleNamespace(content_length=None, get_json=get_json)
            try:
                response, status = await plugin.save_config_handler()
            finally:
                main_module.request = original_request

            self.assertEqual(status, 500)
            self.assertFalse(response["args"][0]["success"])
            self.assertEqual(plugin.raw_config, old_config)
            self.assertIs(plugin.plugin_config, old_runtime[0])
            self.assertIs(plugin.persona_manager, old_runtime[1])
            self.assertIs(plugin.video_manager, old_runtime[2])
            self.assertIs(plugin.prompt_optimizer, old_runtime[3])
            self.assertEqual(json.loads(Path(plugin.config_path).read_text(encoding="utf-8")), old_config)

    async def test_reference_redirect_is_revalidated_before_following(self):
        config = ProviderConfig(
            id="redirect-node",
            api_type="openai_image",
            base_url="https://api.example.com/v1",
            api_keys=["key-1"],
            model="image-model",
            timeout=30.0,
        )

        class RedirectSession:
            def __init__(self):
                self.gets = []

            def get(self, url, **kwargs):
                self.gets.append({"url": url, **kwargs})
                response = FakeResponse({}, status=302)
                response.headers = {"Location": "http://127.0.0.1/private.png"}
                return FakePost(response)

        session = RedirectSession()
        provider = OpenAIProvider(config, session)
        checked_urls = []
        original_validate = base_module._validate_remote_reference_url

        def validate_each_hop(url):
            checked_urls.append(url)
            if "127.0.0.1" in url:
                raise RuntimeError("private redirect blocked")

        base_module._validate_remote_reference_url = validate_each_hop
        try:
            with self.assertRaisesRegex(RuntimeError, "private redirect blocked"):
                await provider.read_reference_image("https://public.example/ref.png")
        finally:
            base_module._validate_remote_reference_url = original_validate

        self.assertEqual(
            checked_urls,
            ["https://public.example/ref.png", "http://127.0.0.1/private.png"],
        )
        self.assertEqual(len(session.gets), 1)

    async def test_video_async_submission_rejects_non_object_json(self):
        provider = ProviderConfig(
            id="video-invalid-submit",
            api_type="async_task",
            base_url="https://invalid-submit.example.com/v1",
            api_keys=["key-a"],
            model="video-model",
            timeout=30.0,
        )
        session = FakeSession(FakeResponse(["task-1"]))
        manager = VideoManager(types.SimpleNamespace())

        with self.assertRaisesRegex(VideoTaskError, "提交接口返回的 JSON 不是对象"):
            await manager._fetch_video_from_api(provider, "make a video", session)
        self.assertEqual(len(session.posts), 1)
        self.assertEqual(session.gets, [])

    async def test_video_polling_honors_zero_second_absolute_deadline(self):
        provider = ProviderConfig(
            id="video-zero-deadline",
            api_type="async_task",
            base_url="https://zero-deadline.example.com/v1",
            api_keys=["key-a"],
            model="video-model",
            timeout=0.0,
        )

        class SubmitOnlySession:
            def __init__(self):
                self.posts = []
                self.gets = []

            def post(self, url, **kwargs):
                self.posts.append({"url": url, **kwargs})
                return FakePost(FakeResponse({"id": "task-1"}))

            def get(self, url, **kwargs):
                self.gets.append({"url": url, **kwargs})
                return FakePost(FakeResponse({"status": "SUCCESS", "url": "https://cdn.example.com/out.mp4"}))

        session = SubmitOnlySession()
        manager = VideoManager(types.SimpleNamespace())

        with self.assertRaisesRegex(VideoTaskError, "轮询超时"):
            await manager._fetch_video_from_api(provider, "make a video", session)
        self.assertEqual(len(session.posts), 1)
        self.assertEqual(session.gets, [])

    async def test_video_polling_propagates_cancellation(self):
        provider = ProviderConfig(
            id="video-cancel",
            api_type="async_task",
            base_url="https://cancel.example.com/v1",
            api_keys=["key-a"],
            model="video-model",
            timeout=30.0,
        )

        class CancelledRequest:
            async def __aenter__(self):
                raise asyncio.CancelledError()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class CancelledSession:
            def get(self, url, **kwargs):
                return CancelledRequest()

        manager = VideoManager(types.SimpleNamespace())
        with self.assertRaises(asyncio.CancelledError):
            await manager._poll_task_result(provider, "task-1", CancelledSession(), api_key="key-a")

    async def test_draw_failure_after_pending_message_returns_final_error_and_releases_quota(self):
        helper = CommandPendingSendTest(methodName="test_draw_sends_pending_message_without_yielding_before_chain")
        plugin = helper._plugin()
        plugin.plugin_config.draw_error_message = "绘制失败: {error}"
        plugin.plugin_config.selfie_error_message = "自拍失败: {error}"
        plugin._reserve_image_quota = lambda event, count=1: ("", 1)
        released = []
        plugin._release_image_quota = lambda event, count: released.append(count)
        sequence = []

        class FailingChainManager:
            def __init__(self, config, session):
                pass

            async def run_chain_with_metadata(self, chain_name, prompt, **kwargs):
                sequence.append("generate")
                raise RuntimeError("provider failed")

        class OrderedEvent(helper.FakeEvent):
            async def send(self, result):
                sequence.append("pending")
                await super().send(result)

        event = OrderedEvent()
        original_client_session = main_module.aiohttp.ClientSession
        original_chain_manager = main_module.ChainManager
        main_module.aiohttp.ClientSession = FakeClientSession
        main_module.ChainManager = FailingChainManager
        try:
            results = [item async for item in plugin.cmd_draw(event, "海边日落")]
        finally:
            main_module.aiohttp.ClientSession = original_client_session
            main_module.ChainManager = original_chain_manager

        self.assertEqual(sequence, ["pending", "generate"])
        self.assertEqual(results, [("plain", "绘制失败: provider failed")])
        self.assertEqual(released, [1])
        self.assertEqual(plugin._recorded_count, 0)

    def test_command_and_provider_filters_block_all_reserved_generation_fields(self):
        plugin = object.__new__(OmniDrawPlugin)
        command_payload = {
            "PROMPT": "override",
            "Messages": [],
            "TOOLS": [],
            "Input": "override",
            "N": 99,
            "Stream": True,
            "USER_REF": "secret",
            "user_refs": ["secret"],
            "Persona_Ref": "secret",
            "persona_refs": ["secret"],
            "size": "1024x1024",
        }
        self.assertEqual(plugin._sanitize_generation_kwargs(command_payload), {"size": "1024x1024"})

        provider_payload = {
            **command_payload,
            "MODEL": "override",
            "Contents": [],
            "Image": "secret",
            "images": ["secret"],
            "IMAGE_URL": "secret",
        }
        self.assertEqual(
            base_module.filter_provider_api_kwargs(provider_payload, "node-1"),
            {"size": "1024x1024"},
        )

    def test_admin_decorators_and_reserved_preset_names_are_source_protected(self):
        tree = ast.parse(Path(main_module.__file__).read_text(encoding="utf-8"))
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for function_name in (
            "cmd_switch_persona",
            "cmd_switch_chain",
            "cmd_switch_model",
            "cmd_add_preset",
            "cmd_delete_preset",
        ):
            with self.subTest(function=function_name):
                decorators = [ast.unparse(item) for item in functions[function_name].decorator_list]
                self.assertIn("filter.permission_type(filter.PermissionType.ADMIN)", decorators)

        expected_reserved = {
            "万象帮助",
            "查看预设",
            "极速宏",
            "添加预设",
            "删除预设",
            "清理缓存",
            "签到",
            "人设",
            "切换人设",
            "切换链路",
            "切换模型",
            "画",
            "自拍",
            "视频",
        }
        self.assertTrue(expected_reserved.issubset(main_module.RESERVED_PRESET_NAMES))
        plugin = object.__new__(OmniDrawPlugin)
        plugin._command_prefixes = lambda: ["/"]
        for name in expected_reserved:
            with self.subTest(preset=name):
                self.assertIn("内置指令同名", plugin._validate_preset_name(name))

        cleaned = plugin._clean_runtime_config({
            "presets": [
                "画:不应覆盖内置命令",
                {"name": "切换模型", "prompt": "不应覆盖内置命令"},
                "普通预设:保留",
            ]
        })
        self.assertEqual(cleaned["presets"], ["普通预设:保留"])

    def test_numeric_and_boolean_config_values_are_safely_normalized(self):
        raw_config = {
            "providers": [{
                "id": "image-node",
                "api_type": "openai_image",
                "base_url": "https://api.example.com/v1",
                "api_keys": ["key"],
                "model": "image-model",
                "timeout": "nan",
            }],
            "video_providers": [{
                "id": "video-node",
                "api_type": "async_task",
                "base_url": "https://video.example.com/v1",
                "api_keys": ["key"],
                "model": "video-model",
                "timeout": "inf",
            }],
            "optimizer_config": {
                "enable_optimizer": "false",
                "optimizer_timeout": "nan",
                "max_batch_count": 999,
            },
            "cache_config": {
                "enable_scheduled_cleanup": "0",
                "scheduled_cleanup_interval_hours": 0,
                "enable_size_limit_cleanup": "yes",
                "max_cache_size_mb": "inf",
            },
            "verbose_report": "false",
            "show_generation_time": "1",
            "show_request_model": "no",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            config = PluginConfig.from_dict(raw_config, temp_dir, cleanup_persona_refs=False)

        self.assertFalse(config.enable_optimizer)
        self.assertEqual(config.optimizer_timeout, 15.0)
        self.assertEqual(config.max_batch_count, 10)
        self.assertEqual(config.providers[0].timeout, 60.0)
        self.assertEqual(config.video_providers[0].timeout, 300.0)
        self.assertFalse(config.enable_scheduled_cleanup)
        self.assertEqual(config.scheduled_cleanup_interval_hours, 1)
        self.assertTrue(config.enable_size_limit_cleanup)
        self.assertEqual(config.max_cache_size_mb, 512)
        self.assertFalse(config.verbose_report)
        self.assertTrue(config.show_generation_time)
        self.assertFalse(config.show_request_model)

    def test_background_queue_rejects_over_capacity_and_closes_coroutine(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin._background_tasks = set(range(main_module.MAX_BACKGROUND_TASKS))
        released = []
        plugin._lease_cache_paths = lambda paths: list(paths)
        plugin._release_cache_paths = lambda paths: released.append(list(paths))

        async def never_started():
            await asyncio.sleep(0)

        coro = never_started()
        with self.assertRaisesRegex(RuntimeError, "队列已满"):
            plugin._create_background_task(coro, leased_paths=["leased.png"])

        self.assertEqual(released, [["leased.png"]])
        self.assertIsNone(coro.cr_frame)

    async def test_background_task_releases_lease_after_failure(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin._background_tasks = set()
        plugin._background_task_kinds = {}
        plugin._background_semaphore = None
        plugin._background_semaphore_loop = None
        plugin._lease_cache_paths = lambda paths: list(paths)
        released = []
        plugin._release_cache_paths = lambda paths: released.append(list(paths))

        async def fail():
            raise RuntimeError("background failed")

        task = plugin._create_background_task(fail(), kind="video", leased_paths=["leased.png"])
        result = (await asyncio.gather(task, return_exceptions=True))[0]
        await asyncio.sleep(0)

        self.assertIsInstance(result, RuntimeError)
        self.assertEqual(released, [["leased.png"]])
        self.assertNotIn(task, plugin._background_tasks)
        self.assertNotIn(task, plugin._background_task_kinds)

    async def test_background_semaphore_limits_simultaneous_tasks(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin._background_tasks = set()
        plugin._background_task_kinds = {}
        plugin._background_semaphore = None
        plugin._background_semaphore_loop = None
        plugin._lease_cache_paths = lambda paths: []
        plugin._release_cache_paths = lambda paths: None
        gate = asyncio.Event()
        saturated = asyncio.Event()
        started = 0
        active = 0
        peak = 0

        async def worker():
            nonlocal started, active, peak
            started += 1
            active += 1
            peak = max(peak, active)
            if started == main_module.MAX_ACTIVE_BACKGROUND_TASKS:
                saturated.set()
            try:
                await gate.wait()
            finally:
                active -= 1

        tasks = [
            plugin._create_background_task(worker(), kind="video")
            for _ in range(main_module.MAX_ACTIVE_BACKGROUND_TASKS + 1)
        ]
        await asyncio.wait_for(saturated.wait(), timeout=2)
        await asyncio.sleep(0)

        self.assertEqual(started, main_module.MAX_ACTIVE_BACKGROUND_TASKS)
        self.assertEqual(peak, main_module.MAX_ACTIVE_BACKGROUND_TASKS)

        gate.set()
        await asyncio.gather(*tasks)
        await asyncio.sleep(0)
        self.assertEqual(started, main_module.MAX_ACTIVE_BACKGROUND_TASKS + 1)
        self.assertEqual(peak, main_module.MAX_ACTIVE_BACKGROUND_TASKS)

    async def test_background_task_closes_coroutine_when_cancelled_before_semaphore(self):
        plugin = object.__new__(OmniDrawPlugin)
        plugin._background_tasks = set()
        plugin._background_task_kinds = {}
        plugin._background_semaphore = asyncio.Semaphore(0)
        plugin._background_semaphore_loop = asyncio.get_running_loop()
        plugin._lease_cache_paths = lambda paths: list(paths)
        released = []
        plugin._release_cache_paths = lambda paths: released.append(list(paths))

        async def never_started():
            await asyncio.sleep(0)

        coro = never_started()
        task = plugin._create_background_task(coro, kind="video", leased_paths=["queued.png"])
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        self.assertIsNone(coro.cr_frame)
        self.assertEqual(released, [["queued.png"]])

    async def test_video_error_text_redacts_provider_secrets(self):
        manager = object.__new__(VideoManager)
        response = FakeResponse({"error": {"message": "api_key=video-secret"}}, status=401)

        message = await manager._read_error(response)

        self.assertNotIn("video-secret", message)
        self.assertIn("<redacted>", message)

    async def test_main_reference_redirect_is_revalidated_before_following(self):
        plugin = object.__new__(OmniDrawPlugin)
        checked_urls = []

        def validate_each_hop(url):
            checked_urls.append(url)
            if "127.0.0.1" in url:
                raise ValueError("private redirect blocked")

        plugin._validate_remote_image_url = validate_each_hop

        class RedirectSession:
            def __init__(self):
                self.gets = []

            def get(self, url, **kwargs):
                self.gets.append({"url": url, **kwargs})
                response = FakeResponse({}, status=302)
                response.headers = {"Location": "http://127.0.0.1/private.png"}
                return FakePost(response)

        session = RedirectSession()
        with self.assertRaisesRegex(ValueError, "private redirect blocked"):
            await plugin._download_remote_image(session, "https://public.example/ref.png", {})

        self.assertEqual(
            checked_urls,
            ["https://public.example/ref.png", "http://127.0.0.1/private.png"],
        )
        self.assertEqual(len(session.gets), 1)

    async def test_video_reference_redirect_is_revalidated_before_following(self):
        manager = VideoManager(types.SimpleNamespace())
        checked_urls = []
        original_validate = video_manager_module._validate_remote_reference_url

        def validate_each_hop(url):
            checked_urls.append(url)
            if "127.0.0.1" in url:
                raise VideoTaskError("private redirect blocked")

        class RedirectSession:
            def __init__(self):
                self.gets = []

            def get(self, url, **kwargs):
                self.gets.append({"url": url, **kwargs})
                response = FakeResponse({}, status=302)
                response.headers = {"Location": "http://127.0.0.1/private.png"}
                return FakePost(response)

        session = RedirectSession()
        video_manager_module._validate_remote_reference_url = validate_each_hop
        try:
            with self.assertRaisesRegex(VideoTaskError, "private redirect blocked"):
                await manager._encode_image_to_base64("https://public.example/ref.png", session)
        finally:
            video_manager_module._validate_remote_reference_url = original_validate

        self.assertEqual(
            checked_urls,
            ["https://public.example/ref.png", "http://127.0.0.1/private.png"],
        )
        self.assertEqual(len(session.gets), 1)


if __name__ == "__main__":
    unittest.main()
