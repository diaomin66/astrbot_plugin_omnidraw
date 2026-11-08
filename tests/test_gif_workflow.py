"""Command, tool, cache and byte-preserving GIF delivery regressions."""

import asyncio
import base64
import importlib
import json
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import test_custom_endpoint as fixtures


main = fixtures.main_module
utils = importlib.import_module(f"{fixtures.PACKAGE_NAME}.utils")
GIF_BYTES = base64.b64decode(
    "R0lGODlhAgACAIEAAAAAAAAAAAAAAAAAACH/C05FVFNDQVBFMi4wAwEAAAAh+QQACgAAACwA"
    "AAAAAgACAAAIBgABCAQQEAAh+QQBFAABACwAAAAAAgACAIH///8AAAAAAAAAAAAIBgABCAQQEAA7"
)
GIF_URL = "data:image/gif;base64," + base64.b64encode(GIF_BYTES).decode("ascii")


class GifWorkflowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.plugin = fixtures.PluginImageReturnTest()._plugin()
        self.plugin.data_dir = self.temp.name
        self.plugin.plugin_config.presets = {}
        self.plugin.plugin_config.persona_ref_images = []
        self.plugin.plugin_config.chains = {"selfie": ["node"]}
        self.plugin.plugin_config.persona_name = "test persona"
        self.plugin.plugin_config.draw_pending_message = "Preparing {command}"
        self.plugin.plugin_config.draw_error_message = "Failed: {error}"
        self.plugin.plugin_config.selfie_pending_message = "Preparing {command}"
        self.plugin.plugin_config.selfie_error_message = "Failed: {error}"
        self.plugin.plugin_config.verbose_report = False
        self.plugin._cache_lease_lock = threading.RLock()
        self.plugin._cache_leases = {}
        for method in ("_lease_cache_paths", "_release_cache_paths"):
            setattr(self.plugin, method, getattr(fixtures.OmniDrawPlugin, method).__get__(self.plugin))
        self.plugin._reserve_image_quota = lambda event, count=1: ("", count)
        self.plugin._released = []
        self.plugin._release_image_quota = lambda event, count: self.plugin._released.append(count)
        self.plugin._finalize_image_quota = lambda event, reserved, count: setattr(self.plugin, "_recorded_count", count)
        self.plugin._extract_command_message = lambda event, command, fallback: fallback
        self.plugin._get_event_images = lambda *args, **kwargs: []
        self.event = fixtures.CommandPendingSendTest.FakeEvent()
        self.calls = []
        calls = self.calls

        class FakeChain:
            def __init__(self, config, session):
                pass

            async def run_chain_with_metadata(self, chain_name, prompt, **kwargs):
                calls.append((chain_name, prompt, kwargs))
                return fixtures.ChainRunResult(
                    GIF_URL, "node", "gpt-image-2.6-flare", 1.2, "gif",
                )

        self.enterContext(patch.object(main, "ChainManager", FakeChain))
        self.enterContext(patch.object(main.aiohttp, "ClientSession", fixtures.FakeClientSession))

    def test_signed_urls_and_mislabelled_bytes_keep_gif_extension(self):
        self.assertEqual(utils.guess_image_content_type("https://cdn.example/a.gif?token=abc"), "image/gif")
        path = utils.save_image_bytes(GIF_BYTES, self.temp.name, "https://cdn.example/no-ext", content_type="image/png")
        self.assertEqual(Path(path).suffix, ".gif")
        self.assertEqual(Path(path).read_bytes(), GIF_BYTES)

    def test_gif_parameters_are_typed_and_dedicated_arguments_win(self):
        options = self.plugin._image_request_options("--frame_count 4 --complexity low", "", "512x512", True, 8, 120)
        self.assertEqual(options, {
            "output_format": "gif", "size": "512x512", "frame_count": 8,
            "frame_duration_ms": 120, "complexity": "low",
        })
        advanced = self.plugin._image_request_options("--output_format gif --frame_count 4", "", "512x512")
        self.assertEqual(advanced["frame_count"], 4)
        self.assertEqual(advanced["size"], "512x512")
        self.assertEqual(self.plugin._image_request_options("--vendor unchanged", "16:9", "1K"), {
            "vendor": "unchanged", "aspect_ratio": "16:9", "size": "1K",
        })

    def test_stream_is_not_silently_dropped_before_gif_validation(self):
        with self.assertRaisesRegex(ValueError, "stream"):
            self.plugin._image_request_options("--stream true", "", "", True)

    async def test_gif_command_uses_image_chain_and_sends_original_bytes(self):
        optimizer = AsyncMock(side_effect=AssertionError("GIF must bypass still-image optimization"))
        self.plugin.prompt_optimizer.optimize = optimizer
        yielded = [item async for item in self.plugin.cmd_gif(self.event, "waving cat --frame_count 4")]
        self.assertEqual(yielded, [])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0:2], ("text2img", "waving cat"))
        self.assertEqual(self.calls[0][2]["frame_count"], 4)
        self.assertEqual(self.event.sent[0][0], "plain")
        path = self.event.sent[-1][1][-1]["path"]
        self.assertEqual(Path(path).read_bytes(), GIF_BYTES)
        self.assertTrue(path.endswith(".gif"))
        self.assertEqual(self.plugin._recorded_count, 1)
        self.assertEqual(self.plugin._cache_leases, {})
        optimizer.assert_not_called()

    async def test_gif_command_invalid_frames_releases_quota_without_generation(self):
        yielded = [item async for item in self.plugin.cmd_gif(self.event, "cat --frame_count 17")]
        self.assertIn("frame_count", yielded[0][1])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.plugin._released, [1])

    async def test_old_gif_preset_remains_valid_and_command_does_not_duplicate_it(self):
        self.plugin.plugin_config.presets = {"gif": "legacy still image prompt"}
        self.assertEqual(self.plugin._validate_preset_name("gif"), "")
        self.assertEqual(self.plugin._parse_preset_trigger("/gif more"), ("gif", "more"))
        self.assertEqual([item async for item in self.plugin.cmd_gif(self.event, "more")], [])
        self.assertEqual(self.calls, [])

    async def test_gif_preset_defaults_are_applied_after_extra_parameters_merge(self):
        self.plugin.plugin_config.presets = {
            "loop": "waving cat --output_format gif --frame_count 4 --size 512x512",
        }
        self.event.message_str = "/loop --output_format gif --frame_duration_ms 100 --user_refs blocked --n 7"
        self.assertEqual([item async for item in self.plugin.on_message_preset(self.event)], [])
        options = self.calls[0][2]
        self.assertEqual(options["frame_count"], 4)
        self.assertEqual(options["size"], "512x512")
        self.assertEqual(options["frame_duration_ms"], 100)
        self.assertNotIn("user_refs", options)
        self.assertNotIn("n", options)
        self.assertEqual(self.plugin._cache_leases, {})

    async def test_static_preset_merge_keeps_override_priority_and_reserved_filtering(self):
        self.plugin.plugin_config.presets = {
            "still": "cat --size 1024x1024 --quality medium --user_refs blocked",
        }
        self.event.message_str = "/still --quality high --n 3"
        self.assertEqual([item async for item in self.plugin.on_message_preset(self.event)], [])
        self.assertEqual(self.calls[0][2], {"size": "1024x1024", "quality": "high"})

    async def test_gif_tool_unwraps_event_and_bypasses_optimizer(self):
        self.plugin.prompt_optimizer.optimize = AsyncMock(side_effect=AssertionError("not a still"))
        wrapper = types.SimpleNamespace(context=types.SimpleNamespace(event=self.event))
        message = await self.plugin.tool_generate_image(wrapper, "cat jumps then lands", use_gif=True, frame_count=6)
        self.assertIn("1", message)
        self.assertEqual(self.calls[0][1], "cat jumps then lands")
        self.assertEqual(self.calls[0][2]["frame_count"], 6)
        self.assertEqual(self.plugin._recorded_count, 1)
        self.assertEqual(self.plugin._cache_leases, {})

    async def test_selfie_gif_tool_keeps_persona_prompt_and_parameters(self):
        self.plugin.prompt_optimizer.optimize = AsyncMock(side_effect=AssertionError("not a still"))
        message = await self.plugin.tool_generate_selfie(self.event, "blink then smile", use_gif=True)
        self.assertIn("1", message)
        self.assertEqual(self.calls[0][0], "selfie")
        self.assertIn("persona base, blink then smile", self.calls[0][1])
        self.assertEqual(self.calls[0][2]["output_format"], "gif")
        self.assertEqual(self.plugin._cache_leases, {})

    async def test_return_mode_has_gif_mime_bytes_and_does_not_send(self):
        text = await self.plugin.tool_generate_image(self.event, "waving cat", use_gif=True, return_result=True)
        result = json.loads(text)
        self.assertTrue(result["success"], result)
        image = result["images"][0]
        self.assertEqual(image["content_type"], "image/gif")
        self.assertEqual(image["output_format"], "gif")
        self.assertEqual(utils.split_data_url(image["data_url"])[0], GIF_BYTES)
        self.assertEqual(Path(image["file_path"]).read_bytes(), GIF_BYTES)
        self.assertEqual(self.event.sent, [])
        self.assertEqual(self.plugin._cache_leases, {})

    async def test_return_permission_errors_remain_json(self):
        self.plugin._permission_denied_message = lambda event: "denied"
        for tool, kwargs in (
            (self.plugin.tool_generate_image, {"prompt": "cat"}),
            (self.plugin.tool_generate_selfie, {"action": "smile"}),
        ):
            result = json.loads(await tool(self.event, **kwargs, use_gif=True, return_result=True))
            self.assertFalse(result["success"])
            self.assertEqual(result["message"], "denied")

    async def test_image_send_failure_retries_only_original_file(self):
        class FakeFile:
            def __init__(self, name, file):
                self.name, self.file = name, file

        async def send(chain):
            if chain[0] == "chain" and isinstance(chain[1][0], dict):
                raise RuntimeError("image upload unsupported")
            self.event.sent.append(chain)

        self.event.send = send
        with patch.object(main, "File", FakeFile):
            message = await self.plugin.tool_generate_image(self.event, "waving", use_gif=True)
        self.assertIn("1", message)
        self.assertEqual(len(self.calls), 1)
        delivered = self.event.sent[0][1][0]
        self.assertTrue(delivered.name.endswith(".gif"))
        self.assertEqual(Path(delivered.file).read_bytes(), GIF_BYTES)
        self.assertEqual(self.plugin._recorded_count, 1)
        self.assertEqual(self.plugin._cache_leases, {})

    async def test_failed_delivery_does_not_generate_again_or_charge_quota(self):
        self.event.send = AsyncMock(side_effect=RuntimeError("adapter offline"))
        with patch.object(main, "File", lambda **kwargs: kwargs):
            message = await self.plugin.tool_generate_image(self.event, "waving", use_gif=True)
        self.assertIn("adapter offline", message)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.plugin._released, [1])
        self.assertEqual(self.plugin._recorded_count, 0)
        self.assertEqual(self.plugin._cache_leases, {})

    async def test_extensionless_remote_gif_is_downloaded_and_validated(self):
        downloader = AsyncMock(return_value=(GIF_BYTES, "application/octet-stream", "https://cdn.example/signed"))
        self.plugin._download_remote_image = downloader
        result = fixtures.ChainRunResult("https://cdn.example/signed?token=x", "node", "gpt-image-2.6-flare", 1, "gif")
        materialized = await self.plugin._materialize_gif_result(result)
        self.assertEqual(Path(materialized.image_url).read_bytes(), GIF_BYTES)
        self.assertTrue(materialized.image_url.endswith(".gif"))
        downloader.assert_awaited_once()

    async def test_static_remote_content_is_not_sent_as_gif(self):
        self.plugin._download_remote_image = AsyncMock(return_value=(b"\x89PNG\r\n\x1a\nother", "image/gif", "https://cdn.example/x"))
        with self.assertRaisesRegex(ValueError, "GIF"):
            await self.plugin._materialize_gif_result("https://cdn.example/x.gif")
        self.assertEqual(self.event.sent, [])

    async def test_private_result_urls_are_blocked_before_http(self):
        with patch.object(main.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaisesRegex(ValueError, "URL"):
                await self.plugin._materialize_gif_result("https://private.invalid/x.gif")

    async def test_batch_gifs_are_leased_before_pruning_and_until_all_sent(self):
        def prune(*args, **kwargs):
            protected = set(kwargs.get("protected_paths", [])) | self.plugin._leased_cache_paths()
            for path in Path(self.temp.name).rglob("*.gif"):
                if str(path) not in protected:
                    path.unlink()

        self.plugin._prune_cache_if_needed = prune
        original_send = self.event.send

        async def send(chain):
            prune()
            self.assertTrue(Path(chain[1][-1]["path"]).exists())
            await original_send(chain)

        self.event.send = send
        message = await self.plugin.tool_generate_image(self.event, "waving", count=2, use_gif=True)
        self.assertIn("2", message)
        self.assertEqual(len(self.event.sent), 2)
        self.assertEqual(self.plugin._recorded_count, 2)
        self.assertEqual(self.plugin._cache_leases, {})

    async def test_cancelled_delivery_releases_result_leases_and_quota(self):
        self.event.send = AsyncMock(side_effect=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            await self.plugin.tool_generate_image(self.event, "waving", use_gif=True)
        self.assertEqual(self.plugin._released, [1])
        self.assertEqual(self.plugin._cache_leases, {})

    async def test_session_exit_failure_or_cancellation_releases_both_runner_leases(self):
        for mode in ("text2img", "selfie"):
            for failure_type in (RuntimeError, asyncio.CancelledError):
                with self.subTest(mode=mode, failure=failure_type.__name__):
                    class FailingExitSession(fixtures.FakeClientSession):
                        async def __aexit__(self, *args):
                            raise failure_type("session exit failed")

                    before_releases = len(self.plugin._released)
                    with patch.object(main.aiohttp, "ClientSession", FailingExitSession):
                        with self.assertRaises(failure_type):
                            await self.plugin.generate_images_for_plugin(
                                "waving", mode=mode, use_gif=True, event=self.event, record_usage=True,
                            )
                    self.assertEqual(self.plugin._cache_leases, {})
                    self.assertEqual(len(self.plugin._released), before_releases + 1)
                    self.assertEqual(self.plugin._recorded_count, 0)

    async def test_cache_clear_cannot_delete_worker_output_before_await_returns(self):
        written = threading.Event()
        finish = threading.Event()
        original_write = self.plugin._write_gif_file
        paths = []
        leased = []

        def delayed_return(path, image_bytes):
            original_write(path, image_bytes)
            paths.append(path)
            written.set()
            if not finish.wait(5):
                raise RuntimeError("test worker timed out")

        with patch.object(self.plugin, "_write_gif_file", delayed_return):
            task = asyncio.create_task(self.plugin._materialize_gif_result(GIF_URL, leased_paths=leased))
            try:
                self.assertTrue(await asyncio.to_thread(written.wait, 5))
                self.assertEqual(self.plugin._cache_leases.get(paths[0]), 1)
                cleared = self.plugin._clear_cache_images("test_inflight_write")
                self.assertEqual(cleared["deleted_count"], 0)
                self.assertTrue(Path(paths[0]).exists())
                finish.set()
                result = await task
                self.assertEqual(Path(result).read_bytes(), GIF_BYTES)
            finally:
                finish.set()
                await asyncio.gather(task, return_exceptions=True)
                self.plugin._release_cache_paths(leased)
        self.assertEqual(self.plugin._cache_leases, {})

    async def test_cancelled_worker_cannot_register_a_late_lease(self):
        started = threading.Event()
        finish = threading.Event()
        completed = threading.Event()
        original_write = self.plugin._write_gif_file
        leased = []

        def delayed_write(path, image_bytes):
            started.set()
            try:
                if not finish.wait(5):
                    raise RuntimeError("test worker timed out")
                original_write(path, image_bytes)
            finally:
                completed.set()

        with patch.object(self.plugin, "_write_gif_file", delayed_write):
            task = asyncio.create_task(self.plugin._materialize_gif_result(GIF_URL, leased_paths=leased))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 5))
                self.assertEqual(sum(self.plugin._cache_leases.values()), 1)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertEqual(self.plugin._cache_leases, {})
                finish.set()
                self.assertTrue(await asyncio.to_thread(completed.wait, 5))
                self.assertEqual(self.plugin._cache_leases, {})
                self.assertEqual(leased, [])
                cleared = self.plugin._clear_cache_images("test_cancelled_worker")
                self.assertEqual(cleared["deleted_count"], 1)
            finally:
                finish.set()
                await asyncio.gather(task, return_exceptions=True)
                await asyncio.to_thread(completed.wait, 5)


if __name__ == "__main__":
    unittest.main()
