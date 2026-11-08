"""Page API compatibility, transaction and event-loop regressions without a host."""

import asyncio
import base64
import contextvars
import copy
import hashlib
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import test_custom_endpoint as fixtures


main = fixtures.main_module
IMAGE_BYTES = b"\x89PNG\r\n\x1a\n" + b"original-reference" * 30
IMAGE_DATA = "data:image/png;base64," + base64.b64encode(IMAGE_BYTES).decode("ascii")
REMOTE_IMAGE = "https://images.example/reference.png?version=1"
REQUEST_BODY = contextvars.ContextVar("page_test_request_body", default=None)


class PageRequest:
    content_length = None
    args = {}

    async def get_json(self, **kwargs):
        return copy.deepcopy(REQUEST_BODY.get())


class NativeConfig(dict):
    def __init__(self, path, values):
        super().__init__(copy.deepcopy(values))
        self.config_path = str(path)
        self.save_count = 0
        self.save_config()

    def save_config(self):
        self.save_count += 1
        Path(self.config_path).write_text(json.dumps(self, ensure_ascii=False, indent=2), encoding="utf-8")


class PageContext:
    def __init__(self):
        self.routes = {}
        self.updates = []

    def register_web_api(self, path, handler, methods, description):
        self.routes[path] = (handler, methods)

    def update_config(self, config):
        self.updates.append(copy.deepcopy(config))


def unpack_response(response):
    if isinstance(response, tuple):
        return response
    return response, 200


class PageBackendTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="omnidraw-page-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data_dir = self.root / "plugin_data"
        refs = self.data_dir / "persona_refs"
        refs.mkdir(parents=True)
        self.first_ref = refs / "ref_first.png"
        self.second_ref = refs / "ref_second.png"
        self.first_ref.write_bytes(IMAGE_BYTES)
        self.second_ref.write_bytes(IMAGE_BYTES + b"second")
        seed = {
            "providers": [{
                "id": "image-node", "api_type": "gemini_official", "base_url": "https://relay.example/v1beta",
                "model": "gemini-image", "api_keys": ["private-image-1111", "private-image-2222"],
                "available_models": ["gemini-image", "alternate-model"], "timeout": 180,
                "extension": {"preserve": "node-value"},
            }],
            "video_providers": [{
                "id": "video-node", "api_type": "async_task", "base_url": "https://video.example/v1",
                "model": "video-model", "api_keys": ["private-video-3333"], "timeout": 300,
            }],
            "persona_config": {
                "active_persona_id": "alpha", "extension": "persona-value",
                "profiles": [
                    {"id": "alpha", "persona_name": "Alpha", "persona_base_prompt": "alpha prompt",
                     "persona_ref_image": [str(self.first_ref), REMOTE_IMAGE]},
                    {"id": "beta", "persona_name": "Beta", "persona_base_prompt": "beta prompt",
                     "persona_ref_image": [str(self.second_ref)]},
                ],
            },
            "presets": ["gif:legacy preset --size 1024x1024", "portrait:portrait prompt"],
            "router_config": {"chain_text2img": "image-node", "chain_selfie": "image-node", "chain_video": "video-node"},
            "optimizer_config": {"enable_optimizer": False, "extension": "optimizer-value"},
            "reply_config": {"draw_pending_message": "initial-message", "extension": "reply-value"},
            "cache_config": {"enable_scheduled_cleanup": False, "enable_size_limit_cleanup": False},
            "permission_config": {"usable_users": "user-a\nuser-b", "extension": "permission-value"},
            "usage_config": {"enable_daily_limit": True, "daily_image_limit": 7},
            "verbose_report": False,
        }
        self.native = NativeConfig(self.root / "native-config.json", seed)
        self.context = PageContext()
        with patch.object(fixtures.OmniDrawPlugin, "_resolve_data_dir", return_value=str(self.data_dir)):
            self.plugin = fixtures.OmniDrawPlugin(self.context, self.native)
        request_patch = patch.object(main, "request", PageRequest())
        jsonify_patch = patch.object(main, "jsonify", lambda payload: payload)
        request_patch.start()
        jsonify_patch.start()
        self.addCleanup(request_patch.stop)
        self.addCleanup(jsonify_patch.stop)

    async def asyncTearDown(self):
        await self.plugin.terminate()

    async def save(self, payload):
        token = REQUEST_BODY.set(payload)
        try:
            return unpack_response(await self.plugin.save_config_handler())
        finally:
            REQUEST_BODY.reset(token)

    def image_inventory(self):
        return {
            path.relative_to(self.data_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((self.data_dir / "persona_refs").glob("*")) if path.is_file()
        }

    def persisted(self):
        return json.loads(Path(self.plugin.config_path).read_text(encoding="utf-8"))

    def without_image_refs(self, config):
        result = copy.deepcopy(config)
        persona = result["persona_config"]
        persona.pop("persona_ref_image", None)
        for profile in persona["profiles"]:
            profile.pop("persona_ref_image", None)
        return result

    def merge_returned_refs(self, payload, returned):
        profiles = {item["id"]: item["persona_ref_image"] for item in returned["profiles"]}
        for profile in payload["persona_config"]["profiles"]:
            profile["persona_ref_image"] = list(profiles[profile["id"]])
        payload["persona_config"]["persona_ref_image"] = list(returned["persona_ref_image"])

    async def test_compact_route_and_legacy_route_have_the_same_configuration_structure(self):
        compact = await self.plugin.get_page_config_handler()
        legacy = await self.plugin.get_config_handler()
        self.assertIn(f"/{main.PLUGIN_NAME}/get_page_config", self.context.routes)
        self.assertIn(f"/{main.PLUGIN_NAME}/get_config", self.context.routes)
        self.assertEqual(self.without_image_refs(compact), self.without_image_refs(legacy))
        first_compact = compact["persona_config"]["profiles"][0]["persona_ref_image"]
        first_legacy = legacy["persona_config"]["profiles"][0]["persona_ref_image"]
        self.assertTrue(first_compact[0].startswith(f"/{main.PLUGIN_NAME}/get_image?token="))
        self.assertEqual(first_legacy[0], IMAGE_DATA)
        self.assertEqual(first_compact[1], REMOTE_IMAGE)
        self.assertEqual(first_legacy[1], REMOTE_IMAGE)
        self.assertEqual(first_compact, compact["persona_config"]["persona_ref_image"])
        self.assertNotIn(str(self.data_dir), json.dumps(compact))
        self.assertNotIn("private-image-1111", json.dumps(compact))
        self.assertNotIn("private-video-3333", json.dumps(legacy))
        self.assertEqual(self.plugin._config_for_page(), legacy)

    async def test_compact_reads_do_not_encode_whole_reference_images(self):
        with patch.object(main.base64, "b64encode", side_effect=AssertionError("compact mode encoded image bytes")):
            config = await self.plugin.get_page_config_handler()
        self.assertEqual(len(config["persona_config"]["profiles"]), 2)

    async def test_other_tabs_and_legacy_reads_do_not_expire_existing_tokens(self):
        first_tab = await self.plugin.get_page_config_handler()
        first_url = first_tab["persona_config"]["profiles"][0]["persona_ref_image"][0]
        second_tab = await self.plugin.get_page_config_handler()
        await self.plugin.get_config_handler()
        self.assertEqual(first_tab, second_tab)
        self.assertEqual(self.plugin._resolve_page_image_ref(first_url), str(self.first_ref))
        first_tab["verbose_report"] = True
        result, status = await self.save(first_tab)
        self.assertEqual(status, 200)
        self.assertTrue(result["success"])
        self.assertEqual(result["persona_refs"]["profiles"][0]["persona_ref_image"][0], first_url)

    async def test_tokens_are_opaque_stable_per_instance_and_not_derived_from_path_alone(self):
        first = self.plugin._local_image_preview_url(str(self.first_ref))
        self.assertEqual(first, self.plugin._local_image_preview_url(str(self.first_ref)))
        other_root = self.root / "other-plugin"
        with patch.object(fixtures.OmniDrawPlugin, "_resolve_data_dir", return_value=str(other_root)):
            other = fixtures.OmniDrawPlugin(PageContext(), {})
        try:
            other_token = other._local_image_preview_url(str(self.first_ref))
            self.assertNotEqual(first, other_token)
        finally:
            await other.terminate()
        token = parse_qs(urlparse(first).query)["token"][0]
        self.assertGreaterEqual(len(token), 32)
        self.assertNotIn(self.first_ref.name, first)
        self.assertNotEqual(token, hashlib.sha256(str(self.first_ref).encode()).hexdigest())

    async def test_save_result_contains_only_compact_persona_reference_metadata(self):
        result, status = await self.save({"verbose_report": True})
        self.assertEqual(status, 200)
        self.assertEqual(set(result), {"success", "message", "persona_refs"})
        self.assertEqual(set(result["persona_refs"]), {"profiles", "persona_ref_image"})
        self.assertEqual([item["id"] for item in result["persona_refs"]["profiles"]], ["alpha", "beta"])
        for profile in result["persona_refs"]["profiles"]:
            self.assertEqual(set(profile), {"id", "persona_ref_image"})
        self.assertNotIn("alpha prompt", json.dumps(result))
        self.assertNotIn(str(self.data_dir), json.dumps(result))
        self.assertEqual(result["persona_refs"], self.plugin._page_persona_refs())

    async def test_compact_save_roundtrip_preserves_all_existing_configuration_and_images(self):
        before = copy.deepcopy(self.plugin.raw_config)
        inventory = self.image_inventory()
        payload = await self.plugin.get_page_config_handler()
        result, status = await self.save(payload)
        self.assertEqual(status, 200)
        self.assertTrue(result["success"])
        self.assertEqual(self.plugin.raw_config, before)
        self.assertEqual(self.persisted(), before)
        self.assertEqual(self.image_inventory(), inventory)

    async def test_uploaded_image_is_not_rematerialized_after_using_save_response(self):
        payload = await self.plugin.get_page_config_handler()
        upload = "data:image/png;base64," + base64.b64encode(IMAGE_BYTES + b"uploaded").decode("ascii")
        payload["persona_config"]["profiles"][0]["persona_ref_image"] = [upload, REMOTE_IMAGE]
        payload["persona_config"]["persona_ref_image"] = [upload, REMOTE_IMAGE]
        first, status = await self.save(payload)
        self.assertEqual(status, 200)
        self.merge_returned_refs(payload, first["persona_refs"])
        inventory = self.image_inventory()
        references = copy.deepcopy(self.plugin.raw_config["persona_config"])
        for _ in range(3):
            response, status = await self.save(payload)
            self.assertEqual(status, 200)
            self.merge_returned_refs(payload, response["persona_refs"])
            self.assertEqual(self.image_inventory(), inventory)
            self.assertEqual(self.plugin.raw_config["persona_config"], references)

    async def test_noop_save_does_not_persist_reapply_or_resynchronize_native_config(self):
        payload = await self.plugin.get_page_config_handler()
        with patch.object(self.plugin, "_persist_config", wraps=self.plugin._persist_config) as persist, \
                patch.object(self.plugin, "_apply_runtime_config", wraps=self.plugin._apply_runtime_config) as apply, \
                patch.object(self.plugin, "_safe_update_context_config", wraps=self.plugin._safe_update_context_config) as sync:
            response, status = await self.save(payload)
        self.assertEqual(status, 200)
        self.assertTrue(response["success"])
        persist.assert_not_called()
        apply.assert_not_called()
        sync.assert_not_called()

    async def test_unknown_and_expired_preview_tokens_fail_without_losing_saved_references(self):
        for expired in (False, True):
            with self.subTest(expired=expired):
                payload = await self.plugin.get_page_config_handler()
                before = copy.deepcopy(self.plugin.raw_config)
                before_file = Path(self.plugin.config_path).read_bytes()
                before_native = Path(self.native.config_path).read_bytes()
                inventory = self.image_inventory()
                if expired:
                    self.plugin._page_image_tokens.clear()
                else:
                    payload["persona_config"]["profiles"][0]["persona_ref_image"][0] = (
                        f"/{main.PLUGIN_NAME}/get_image?token=unknown-token"
                    )
                payload["verbose_report"] = not before["verbose_report"]
                response, status = await self.save(payload)
                self.assertEqual(status, 400)
                self.assertFalse(response["success"])
                self.assertEqual(self.plugin.raw_config, before)
                self.assertEqual(Path(self.plugin.config_path).read_bytes(), before_file)
                self.assertEqual(Path(self.native.config_path).read_bytes(), before_native)
                self.assertEqual(self.image_inventory(), inventory)

    def test_normalizing_unknown_tokens_raises_instead_of_silently_dropping_them(self):
        payload = {"persona_config": {"persona_ref_image": [f"/{main.PLUGIN_NAME}/get_image?token=missing"]}}
        with self.assertRaises(ValueError):
            self.plugin._normalize_saved_page_images(payload)

    async def test_token_cache_bound_eviction_fails_safely_on_save(self):
        payload = await self.plugin.get_page_config_handler()
        with patch.object(main, "MAX_PAGE_IMAGE_TOKENS", 2):
            self.plugin._page_image_tokens.clear()
            first = self.plugin._local_image_preview_url(str(self.first_ref))
            self.plugin._local_image_preview_url(str(self.second_ref))
            self.plugin._local_image_preview_url(str(self.data_dir / "third.png"))
            self.assertLessEqual(len(self.plugin._page_image_tokens), 2)
            self.assertEqual(self.plugin._resolve_page_image_ref(first), "")
        payload["persona_config"]["profiles"][0]["persona_ref_image"] = [first]
        result, status = await self.save(payload)
        self.assertEqual(status, 400)
        self.assertFalse(result["success"])
        self.assertEqual(self.first_ref.read_bytes(), IMAGE_BYTES)

    async def test_failed_runtime_apply_restores_all_runtime_objects_and_persisted_configuration(self):
        before = copy.deepcopy(self.plugin.raw_config)
        old_runtime = tuple(getattr(self.plugin, name) for name in ("plugin_config", "persona_manager", "video_manager", "prompt_optimizer"))
        inventory = self.image_inventory()

        def fail_apply(candidate):
            self.plugin.plugin_config = object()
            self.plugin.persona_manager = object()
            raise RuntimeError("injected apply failure")

        with patch.object(self.plugin, "_apply_runtime_config", side_effect=fail_apply):
            result, status = await self.save({"verbose_report": True})
        self.assertEqual(status, 500)
        self.assertFalse(result["success"])
        self.assertEqual(self.plugin.raw_config, before)
        self.assertEqual(self.persisted(), before)
        self.assertEqual(self.image_inventory(), inventory)
        for name, expected in zip(("plugin_config", "persona_manager", "video_manager", "prompt_optimizer"), old_runtime):
            self.assertIs(getattr(self.plugin, name), expected)

    async def test_manager_initialization_failure_does_not_delete_previous_persona_images(self):
        before = copy.deepcopy(self.plugin.raw_config)
        payload = await self.plugin.get_page_config_handler()
        payload["persona_config"]["profiles"][0]["persona_ref_image"] = []
        payload["persona_config"]["persona_ref_image"] = []
        with patch.object(main, "VideoManager", side_effect=RuntimeError("injected manager failure")):
            result, status = await self.save(payload)
        self.assertEqual(status, 500)
        self.assertFalse(result["success"])
        self.assertEqual(self.plugin.raw_config, before)
        self.assertEqual(self.persisted(), before)
        self.assertTrue(self.first_ref.is_file(), "rollback restored a reference to a deleted file")
        self.assertEqual(self.first_ref.read_bytes(), IMAGE_BYTES)

    async def test_concurrent_save_rollback_never_releases_lock_with_failed_candidate_visible(self):
        failed_apply_started = threading.Event()
        allow_failure = threading.Event()
        winner_committed = threading.Event()
        unsafe_release = threading.Event()
        plugin = self.plugin

        class TransactionLock:
            def __init__(self):
                self.lock = threading.RLock()
                self.depth = threading.local()

            def __enter__(self):
                self.lock.acquire()
                self.depth.value = getattr(self.depth, "value", 0) + 1
                return self

            def __exit__(self, exc_type, exc, tb):
                outer = self.depth.value == 1
                self.depth.value -= 1
                exposed = outer and exc_type and plugin.raw_config["reply_config"]["draw_pending_message"] == "losing-save"
                self.lock.release()
                if exposed:
                    unsafe_release.set()
                    winner_committed.wait(2)

        original_apply = plugin._apply_runtime_config
        original_sync = plugin._safe_update_context_config

        def controlled_apply(candidate):
            if candidate["reply_config"]["draw_pending_message"] == "losing-save":
                failed_apply_started.set()
                if not allow_failure.wait(2):
                    raise RuntimeError("test failed to release transaction gate")
                raise RuntimeError("first save failed")
            return original_apply(candidate)

        def observe_commit():
            original_sync()
            if plugin.raw_config["reply_config"]["draw_pending_message"] == "winning-save":
                winner_committed.set()

        with patch.object(plugin, "_config_lock", TransactionLock()), \
                patch.object(plugin, "_apply_runtime_config", side_effect=controlled_apply), \
                patch.object(plugin, "_safe_update_context_config", side_effect=observe_commit):
            losing = asyncio.create_task(self.save({"reply_config": {"draw_pending_message": "losing-save"}}))
            winning = None
            try:
                self.assertTrue(await asyncio.to_thread(failed_apply_started.wait, 2))
                winning = asyncio.create_task(self.save({"reply_config": {"draw_pending_message": "winning-save"}}))
                await asyncio.sleep(0.02)
                allow_failure.set()
                failed, succeeded = await asyncio.wait_for(asyncio.gather(losing, winning), timeout=5)
            finally:
                allow_failure.set()
                await asyncio.gather(*[task for task in (losing, winning) if task is not None], return_exceptions=True)
        self.assertEqual(failed[1], 500)
        self.assertEqual(succeeded[1], 200)
        self.assertTrue(winner_committed.is_set())
        self.assertFalse(unsafe_release.is_set(), "rollback must finish before releasing the transaction lock")
        self.assertEqual(plugin.raw_config["reply_config"]["draw_pending_message"], "winning-save")
        self.assertEqual(self.persisted()["reply_config"]["draw_pending_message"], "winning-save")
        self.assertEqual(json.loads(Path(self.native.config_path).read_text(encoding="utf-8"))["reply_config"]["draw_pending_message"], "winning-save")

    async def test_parallel_successful_partial_saves_preserve_both_updates(self):
        original_prepare = self.plugin._prepare_runtime_config
        active = 0
        overlapping = []
        observer_lock = threading.Lock()

        def prepare(candidate):
            nonlocal active
            with observer_lock:
                active += 1
                overlapping.append(active)
            try:
                threading.Event().wait(0.03)
                return original_prepare(candidate)
            finally:
                with observer_lock:
                    active -= 1

        with patch.object(self.plugin, "_prepare_runtime_config", side_effect=prepare):
            results = await asyncio.gather(
                self.save({"reply_config": {"draw_pending_message": "parallel-message"}}),
                self.save({"usage_config": {"daily_image_limit": 19}}),
            )
        self.assertTrue(all(status == 200 and response["success"] for response, status in results))
        self.assertEqual(max(overlapping), 1)
        self.assertEqual(self.plugin.raw_config["reply_config"]["draw_pending_message"], "parallel-message")
        self.assertEqual(self.plugin.raw_config["usage_config"]["daily_image_limit"], 19)
        self.assertEqual(self.persisted(), self.plugin.raw_config)

    async def test_cancelled_save_finishes_commit_or_rollback_before_returning_cancellation(self):
        for fail, cancellations in ((False, 1), (True, 1), (False, 2), (True, 2)):
            with self.subTest(fail=fail, cancellations=cancellations):
                before = copy.deepcopy(self.plugin.raw_config)
                entered = threading.Event()
                release = threading.Event()
                finished = threading.Event()
                original_apply = self.plugin._apply_runtime_config
                original_save = self.plugin._save_page_config
                message = f"cancelled-save-{fail}-{cancellations}"

                def gated_apply(candidate):
                    entered.set()
                    if not release.wait(2):
                        raise RuntimeError("test did not release the apply gate")
                    if fail:
                        raise RuntimeError("cancelled save failed")
                    return original_apply(candidate)

                def observed_save(payload):
                    try:
                        return original_save(payload)
                    finally:
                        finished.set()

                with patch.object(self.plugin, "_apply_runtime_config", side_effect=gated_apply), \
                        patch.object(self.plugin, "_save_page_config", side_effect=observed_save):
                    task = asyncio.create_task(self.save({"reply_config": {"draw_pending_message": message}}))
                    try:
                        self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                        for _ in range(cancellations):
                            task.cancel()
                            await asyncio.sleep(0.02)
                            self.assertFalse(task.done(), "cancellation abandoned a running configuration transaction")
                        release.set()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                    finally:
                        release.set()
                        await asyncio.gather(task, return_exceptions=True)
                        self.assertTrue(await asyncio.to_thread(finished.wait, 2))
                self.assertTrue(finished.is_set())
                if fail:
                    self.assertEqual(self.plugin.raw_config, before)
                    self.assertEqual(self.persisted(), before)
                else:
                    self.assertEqual(self.plugin.raw_config["reply_config"]["draw_pending_message"], message)
                    self.assertEqual(self.persisted(), self.plugin.raw_config)
                    self.assertEqual(self.native["reply_config"]["draw_pending_message"], message)

    async def test_failed_persist_keeps_previous_memory_native_file_and_images(self):
        before = copy.deepcopy(self.plugin.raw_config)
        native = Path(self.native.config_path).read_bytes()
        inventory = self.image_inventory()
        with patch.object(self.plugin, "_persist_config", side_effect=OSError("simulated disk failure")):
            response, status = await self.save({"verbose_report": True})
        self.assertEqual(status, 500)
        self.assertFalse(response["success"])
        self.assertEqual(self.plugin.raw_config, before)
        self.assertEqual(self.persisted(), before)
        self.assertEqual(Path(self.native.config_path).read_bytes(), native)
        self.assertEqual(self.image_inventory(), inventory)

    async def test_get_image_data_url_branch_is_json_and_encodes_on_a_worker_thread(self):
        image_url = self.plugin._local_image_preview_url(str(self.first_ref))
        token = parse_qs(urlparse(image_url).query)["token"][0]
        original = self.plugin._image_ref_for_page
        threads = []

        def encode(*args, **kwargs):
            threads.append(threading.get_ident())
            return original(*args, **kwargs)

        with patch.object(main.request, "args", {"token": token, "format": "data_url"}), \
                patch.object(self.plugin, "_image_ref_for_page", side_effect=encode), \
                patch.object(main, "send_file", side_effect=AssertionError("JSON preview must not send binary")):
            response, status = unpack_response(await self.plugin.get_image_handler())
        self.assertEqual(status, 200)
        self.assertEqual(response, {"success": True, "data_url": IMAGE_DATA})
        self.assertTrue(threads)
        self.assertTrue(all(thread != threading.get_ident() for thread in threads))

    async def test_get_image_legacy_binary_branch_preserves_send_file_behavior(self):
        image_url = self.plugin._local_image_preview_url(str(self.first_ref))
        token = parse_qs(urlparse(image_url).query)["token"][0]
        calls = []

        async def send_file(path, **kwargs):
            calls.append((path, kwargs))
            return {"binary": True}

        with patch.object(main.request, "args", {"token": token}), patch.object(main, "send_file", side_effect=send_file):
            response = await self.plugin.get_image_handler()
        self.assertEqual(response, {"binary": True})
        self.assertEqual(calls, [(str(self.first_ref), {"mimetype": "image/png"})])

    async def test_get_image_unknown_token_and_unsafe_files_return_404_without_paths(self):
        outside = self.root / "outside.png"
        outside.write_bytes(IMAGE_BYTES)
        invalid = self.data_dir / "not-an-image.png"
        invalid.write_text("not image data", encoding="utf-8")
        missing = self.data_dir / "missing.png"
        candidates = [outside, invalid, missing, self.data_dir]
        args_values = [{"token": "not-a-valid-token", "format": "data_url"}]
        for path in candidates:
            url = self.plugin._local_image_preview_url(str(path))
            args_values.append({"token": parse_qs(urlparse(url).query)["token"][0], "format": "data_url"})
        for args in args_values:
            with self.subTest(args=args), patch.object(main.request, "args", args), \
                    patch.object(main, "send_file", side_effect=AssertionError("unsafe preview was sent")):
                response, status = unpack_response(await self.plugin.get_image_handler())
                self.assertEqual(status, 404)
                self.assertFalse(response["success"])
                self.assertNotIn(str(self.root), json.dumps(response))
                self.assertNotIn("data_url", response)

    async def test_get_image_json_preview_limit_returns_413_not_a_nested_token(self):
        image_url = self.plugin._local_image_preview_url(str(self.first_ref))
        token = parse_qs(urlparse(image_url).query)["token"][0]
        with patch.object(main.request, "args", {"token": token, "format": "data_url"}), \
                patch.object(main, "PAGE_PREVIEW_IMAGE_BYTES", 1):
            response, status = unpack_response(await self.plugin.get_image_handler())
        self.assertEqual(status, 413)
        self.assertFalse(response["success"])
        self.assertNotIn("data_url", response)

    async def test_read_usage_and_cache_handlers_run_synchronous_io_off_the_event_loop(self):
        loop = asyncio.get_running_loop()
        event_thread = threading.get_ident()
        combinations = (
            ("get_config_handler", "_refresh_from_native_config_if_changed"),
            ("get_config_handler", "_config_for_page"),
            ("get_page_config_handler", "_refresh_from_native_config_if_changed"),
            ("get_page_config_handler", "_config_for_page"),
            ("get_usage_stats_handler", "_refresh_from_native_config_if_changed"),
            ("get_usage_stats_handler", "_usage_stats_for_page"),
            ("get_cache_stats_handler", "_refresh_from_native_config_if_changed"),
            ("get_cache_stats_handler", "_cache_stats_for_page"),
            ("clear_cache_handler", "_refresh_from_native_config_if_changed"),
            ("clear_cache_handler", "_clear_cache_images"),
            ("clear_cache_handler", "_cache_stats_for_page"),
        )
        for handler_name, io_name in combinations:
            with self.subTest(handler=handler_name, io=io_name):
                original = getattr(self.plugin, io_name)
                observations = []

                def checked_io(*args, **kwargs):
                    released = threading.Event()
                    loop.call_soon_threadsafe(released.set)
                    observations.append((threading.get_ident(), released.wait(0.5)))
                    return original(*args, **kwargs)

                with patch.object(self.plugin, io_name, side_effect=checked_io):
                    await getattr(self.plugin, handler_name)()
                self.assertTrue(observations)
                self.assertTrue(all(thread != event_thread and ticked for thread, ticked in observations))

    async def test_save_transaction_io_runs_off_the_event_loop(self):
        loop = asyncio.get_running_loop()
        event_thread = threading.get_ident()
        for index, name in enumerate(("_prepare_runtime_config", "_persist_config", "_apply_runtime_config", "_safe_update_context_config")):
            with self.subTest(io=name):
                original = getattr(self.plugin, name)
                observations = []

                def checked_io(*args, **kwargs):
                    released = threading.Event()
                    loop.call_soon_threadsafe(released.set)
                    observations.append((threading.get_ident(), released.wait(0.5)))
                    return original(*args, **kwargs)

                with patch.object(self.plugin, name, side_effect=checked_io):
                    result, status = await self.save({"reply_config": {"draw_pending_message": f"thread-test-{index}"}})
                self.assertEqual(status, 200)
                self.assertTrue(result["success"])
                self.assertTrue(observations)
                self.assertTrue(all(thread != event_thread and ticked for thread, ticked in observations))

    def test_native_file_stamp_includes_inode_nanosecond_times_and_size(self):
        stat = os.stat(self.native.config_path)
        self.assertEqual(self.plugin._file_stamp(self.native.config_path), (stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size))
        self.assertIsNone(self.plugin._file_stamp(str(self.root / "missing.json")))

    async def test_unchanged_native_stamp_avoids_hashing_and_json_reads(self):
        with patch.object(self.plugin, "_file_signature", side_effect=AssertionError("unchanged config was hashed")), \
                patch.object(self.plugin, "_load_json_file", side_effect=AssertionError("unchanged config was read")):
            for _ in range(3):
                await self.plugin.get_page_config_handler()
                await self.plugin.get_usage_stats_handler()
                await self.plugin.get_cache_stats_handler()

    async def test_same_size_same_mtime_atomic_native_replacement_is_hot_reloaded(self):
        native_path = Path(self.native.config_path)
        previous = native_path.stat()
        original_stamp = self.plugin._file_stamp(str(native_path))
        original_text = native_path.read_text(encoding="utf-8")
        updated_text = original_text.replace("initial-message", "changed-message")
        self.assertNotEqual(original_text, updated_text)
        replacement = self.root / "replacement.json"
        replacement.write_text(updated_text, encoding="utf-8")
        os.utime(replacement, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        os.replace(replacement, native_path)
        self.assertEqual(native_path.stat().st_size, previous.st_size)
        self.assertEqual(native_path.stat().st_mtime_ns, previous.st_mtime_ns)
        self.assertNotEqual(self.plugin._file_stamp(str(native_path)), original_stamp)
        with patch.object(self.plugin, "_file_signature", wraps=self.plugin._file_signature) as signature:
            config = await self.plugin.get_page_config_handler()
            self.assertEqual(config["reply_config"]["draw_pending_message"], "changed-message")
            self.assertEqual(self.plugin.plugin_config.draw_pending_message, "changed-message")
            count = signature.call_count
            self.assertGreater(count, 0)
            await self.plugin.get_page_config_handler()
            self.assertEqual(signature.call_count, count)
        self.assertEqual(self.persisted()["reply_config"]["draw_pending_message"], "changed-message")

    async def test_metadata_only_native_change_hashes_once_without_reapplying(self):
        path = Path(self.native.config_path)
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))
        with patch.object(self.plugin, "_file_signature", wraps=self.plugin._file_signature) as signature, \
                patch.object(self.plugin, "_apply_runtime_config", wraps=self.plugin._apply_runtime_config) as apply:
            await self.plugin.get_page_config_handler()
            await self.plugin.get_page_config_handler()
        self.assertEqual(signature.call_count, 1)
        apply.assert_not_called()

    async def test_native_reload_failure_restores_runtime_and_stamp_then_allows_retry(self):
        before = copy.deepcopy(self.plugin.raw_config)
        stamp = self.plugin._native_config_stamp
        signature = self.plugin._native_config_signature
        native_path = Path(self.native.config_path)
        native = json.loads(native_path.read_text(encoding="utf-8"))
        native["reply_config"]["draw_pending_message"] = "native-retry-message"
        native_path.write_text(json.dumps(native), encoding="utf-8")
        with patch.object(self.plugin, "_apply_runtime_config", side_effect=RuntimeError("native reload failed")):
            with self.assertRaisesRegex(RuntimeError, "native reload failed"):
                await self.plugin.get_page_config_handler()
        self.assertEqual(self.plugin.raw_config, before)
        self.assertEqual(self.persisted(), before)
        self.assertEqual(self.plugin._native_config_stamp, stamp)
        self.assertEqual(self.plugin._native_config_signature, signature)
        config = await self.plugin.get_page_config_handler()
        self.assertEqual(config["reply_config"]["draw_pending_message"], "native-retry-message")
        self.assertEqual(self.persisted()["reply_config"]["draw_pending_message"], "native-retry-message")

    async def test_unrelated_settings_do_not_restart_scheduler_or_rescan_cache(self):
        with patch.object(self.plugin, "_restart_cache_cleanup_task", wraps=self.plugin._restart_cache_cleanup_task) as restart, \
                patch.object(self.plugin, "_prune_cache_if_needed", wraps=self.plugin._prune_cache_if_needed) as prune:
            result, status = await self.save({"reply_config": {"draw_pending_message": "unrelated change"}})
        self.assertEqual(status, 200)
        self.assertTrue(result["success"])
        restart.assert_not_called()
        prune.assert_not_called()

    async def test_scheduler_created_on_event_loop_stays_identical_after_unrelated_save(self):
        result, status = await self.save({"cache_config": {"enable_scheduled_cleanup": True, "scheduled_cleanup_interval_hours": 1}})
        self.assertEqual(status, 200)
        self.assertTrue(result["success"])
        await asyncio.sleep(0.01)
        scheduler = self.plugin._cache_cleanup_task
        self.assertIsNotNone(scheduler)
        self.assertFalse(scheduler.done())
        self.assertIs(scheduler.get_loop(), asyncio.get_running_loop())
        _, status = await self.save({"verbose_report": True})
        self.assertEqual(status, 200)
        await asyncio.sleep(0.01)
        self.assertIs(self.plugin._cache_cleanup_task, scheduler)
        self.assertFalse(scheduler.done())
        _, status = await self.save({"cache_config": {"enable_scheduled_cleanup": False}})
        self.assertEqual(status, 200)
        await asyncio.sleep(0.01)
        self.assertTrue(scheduler.done())
        self.assertIsNone(self.plugin._cache_cleanup_task)


if __name__ == "__main__":
    unittest.main()
