"""Exercise real chat commands competing with threaded configuration commits."""

import asyncio
import copy
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import test_page_backend as backend


class CommandEvent:
    is_at_or_wake_command = True
    message_str = ""
    message_obj = types.SimpleNamespace(message_str="", message=[], message_id="config-command")

    def plain_result(self, text):
        return text


class ObservedLock:
    """Keep the real RLock semantics while exposing a competing acquisition."""

    def __init__(self, lock, prepared, owner):
        self.lock = lock
        self.prepared = prepared
        self.owner = owner
        self.contended = threading.Event()
        self.contender_threads = set()

    def __enter__(self):
        thread_id = threading.get_ident()
        if self.prepared.is_set() and thread_id != self.owner[0]:
            self.contender_threads.add(thread_id)
            self.contended.set()
        return self.lock.__enter__()

    def __exit__(self, *args):
        return self.lock.__exit__(*args)


class ConfigConcurrencyTest(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = backend.PageBackendTest.asyncTearDown
    save = backend.PageBackendTest.save
    persisted = backend.PageBackendTest.persisted

    async def asyncSetUp(self):
        await backend.PageBackendTest.asyncSetUp(self)
        for name, value in (("_permission_denied_message", ""), ("_command_prefixes", ["/"])):
            boundary = patch.object(self.plugin, name, return_value=value)
            boundary.start()
            self.addCleanup(boundary.stop)
        self.event = CommandEvent()

    @staticmethod
    async def collect(command):
        return [message async for message in command]

    async def compete(self, operation, command_factory):
        prepared = threading.Event()
        release = threading.Event()
        owner = [None]
        original_prepare = self.plugin._prepare_runtime_config
        observed = ObservedLock(self.plugin._config_lock, prepared, owner)
        loop_thread = threading.get_ident()

        def prepare(candidate):
            result = original_prepare(candidate)
            if not prepared.is_set():
                owner[0] = threading.get_ident()
                prepared.set()
                if not release.wait(5):
                    raise AssertionError("Configuration transaction was not released")
            return result

        def release_on_contention():
            # A pre-fix command blocks the event loop at _persist_config; release
            # from an independent thread so the regression fails, never deadlocks.
            observed.contended.wait(3)
            release.set()

        tasks = []
        releaser = None
        with (
            patch.object(self.plugin, "_prepare_runtime_config", side_effect=prepare),
            patch.object(self.plugin, "_config_lock", observed),
        ):
            try:
                tasks.append(asyncio.create_task(operation()))
                self.assertTrue(await asyncio.to_thread(prepared.wait, 3), "Transaction never prepared its snapshot")
                releaser = threading.Thread(target=release_on_contention, daemon=True)
                releaser.start()
                tasks.append(asyncio.create_task(self.collect(command_factory())))
                result, messages = await asyncio.wait_for(asyncio.gather(*tasks), 10)
            finally:
                release.set()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                if releaser is not None:
                    await asyncio.to_thread(releaser.join, 4)

        self.assertTrue(observed.contended.is_set(), "Command did not serialize with the active transaction")
        self.assertNotIn(loop_thread, observed.contender_threads, "Command waited for the lock on the event loop")
        self.assertTrue(messages)
        self.assertFalse(any(backend.main.MessageEmoji.ERROR in message for message in messages), messages)
        return result, messages

    async def compete_page(self, payload, command_factory):
        response, messages = await self.compete(lambda: self.save(payload), command_factory)
        result, status = response
        self.assertEqual(status, 200, result)
        self.assertTrue(result["success"], result)
        return messages

    def configurations(self):
        return self.plugin.raw_config, self.persisted(), dict(self.native)

    async def add_second_provider(self):
        providers = copy.deepcopy(self.plugin.raw_config["providers"])
        second = copy.deepcopy(providers[0])
        second["id"] = "second-node"
        providers.append(second)
        result, status = await self.save({"providers": providers})
        self.assertEqual(status, 200, result)

    async def test_chain_command_and_unrelated_page_change_both_commit(self):
        await self.add_second_provider()
        messages = await self.compete_page(
            {"reply_config": {"draw_pending_message": "page-chain-message"}},
            lambda: self.plugin.cmd_switch_chain(self.event, "\u753b\u56fe", "second-node"),
        )
        self.assertIn("second-node", messages[0])
        for config in self.configurations():
            self.assertEqual(config["router_config"]["chain_text2img"], "second-node")
            self.assertEqual(config["reply_config"]["draw_pending_message"], "page-chain-message")
        self.assertEqual(self.plugin.plugin_config.chains["text2img"], ["second-node"])

    async def test_model_command_reads_the_committed_page_model_list(self):
        providers = copy.deepcopy(self.plugin.raw_config["providers"])
        providers[0]["available_models"] = ["gemini-image", "page-model"]
        providers[0]["base_url"] = "https://page-relay.example/v1beta"
        messages = await self.compete_page(
            {"providers": providers},
            lambda: self.plugin.cmd_switch_model(self.event, "\u753b\u56fe", "1"),
        )
        self.assertIn("page-model", messages[0])
        for config in self.configurations():
            self.assertEqual(config["providers"][0]["model"], "page-model")
            self.assertEqual(config["providers"][0]["base_url"], "https://page-relay.example/v1beta")
        self.assertEqual(self.plugin._get_active_provider("text2img").model, "page-model")

    async def test_model_listing_waits_for_the_committed_page_configuration(self):
        providers = copy.deepcopy(self.plugin.raw_config["providers"])
        providers[0]["available_models"] = ["gemini-image", "page-only-choice"]
        messages = await self.compete_page(
            {"providers": providers},
            lambda: self.plugin.cmd_switch_model(self.event, "\u753b\u56fe"),
        )
        self.assertIn("page-only-choice", messages[0])
        self.assertNotIn("alternate-model", messages[0])

    async def test_persona_command_preserves_page_profile_edits_and_reference_images(self):
        persona = copy.deepcopy(self.plugin.raw_config["persona_config"])
        persona["profiles"][1]["persona_name"] = "Beta from Page"
        persona["profiles"][1]["persona_base_prompt"] = "page beta prompt"
        messages = await self.compete_page(
            {"persona_config": persona},
            lambda: self.plugin.cmd_switch_persona(self.event, "beta"),
        )
        self.assertIn("Beta from Page", messages[0])
        for config in self.configurations():
            self.assertEqual(config["persona_config"]["active_persona_id"], "beta")
            self.assertEqual(config["persona_config"]["profiles"][1]["persona_name"], "Beta from Page")
            self.assertEqual(config["persona_config"]["profiles"][1]["persona_base_prompt"], "page beta prompt")
        self.assertEqual(self.plugin.plugin_config.active_persona_id, "beta")
        self.assertEqual(self.plugin.plugin_config.persona_ref_images, [str(self.second_ref)])
        self.assertTrue(self.first_ref.is_file())
        self.assertTrue(self.second_ref.is_file())

    async def test_preset_add_does_not_overwrite_a_concurrent_page_preset_edit(self):
        messages = await self.compete_page(
            {"presets": ["gif:legacy preset --size 1024x1024", "portrait:page portrait prompt"]},
            lambda: self.plugin.cmd_add_preset(self.event, "orbit", "command orbit prompt"),
        )
        self.assertIn("orbit", messages[0])
        expected = ["gif:legacy preset --size 1024x1024", "portrait:page portrait prompt", "orbit:command orbit prompt"]
        for config in self.configurations():
            self.assertEqual(config["presets"], expected)
        self.assertEqual(self.plugin.plugin_config.presets["portrait"], "page portrait prompt")
        self.assertEqual(self.plugin.plugin_config.presets["orbit"], "command orbit prompt")

    async def test_preset_delete_does_not_overwrite_a_concurrent_page_preset_edit(self):
        messages = await self.compete_page(
            {"presets": ["gif:legacy preset --size 1024x1024", "portrait:page portrait prompt"]},
            lambda: self.plugin.cmd_delete_preset(self.event, "gif"),
        )
        self.assertIn("gif", messages[0])
        for config in self.configurations():
            self.assertEqual(config["presets"], ["portrait:page portrait prompt"])
        self.assertEqual(self.plugin.plugin_config.presets, {"portrait": "page portrait prompt"})

    async def test_model_command_waits_for_a_concurrent_native_reload(self):
        self.native["providers"][0]["available_models"] = ["gemini-image", "native-model"]
        self.native["reply_config"]["draw_pending_message"] = "native-message"
        self.native.save_config()
        _, messages = await self.compete(
            lambda: asyncio.to_thread(self.plugin._refresh_from_native_config_if_changed),
            lambda: self.plugin.cmd_switch_model(self.event, "\u753b\u56fe", "1"),
        )
        self.assertIn("native-model", messages[0])
        for config in self.configurations():
            self.assertEqual(config["providers"][0]["model"], "native-model")
            self.assertEqual(config["reply_config"]["draw_pending_message"], "native-message")
        self.assertEqual(self.plugin._get_active_provider("text2img").model, "native-model")

    async def test_chat_persist_failures_report_error_without_publishing_changes(self):
        await self.add_second_provider()
        commands = {
            "chain": lambda: self.plugin.cmd_switch_chain(self.event, "\u753b\u56fe", "second-node"),
            "model": lambda: self.plugin.cmd_switch_model(self.event, "\u753b\u56fe", "1"),
            "persona": lambda: self.plugin.cmd_switch_persona(self.event, "beta"),
            "preset-add": lambda: self.plugin.cmd_add_preset(self.event, "orbit", "new prompt"),
            "preset-delete": lambda: self.plugin.cmd_delete_preset(self.event, "portrait"),
        }
        for name, command in commands.items():
            with self.subTest(command=name):
                previous_raw = copy.deepcopy(self.plugin.raw_config)
                previous_runtime = self.plugin.plugin_config
                previous_native = copy.deepcopy(dict(self.native))
                previous_disk = Path(self.plugin.config_path).read_bytes()
                with patch.object(self.plugin, "_persist_config", side_effect=OSError("injected disk failure")):
                    messages = await self.collect(command())
                self.assertTrue(messages)
                self.assertTrue(any(backend.main.MessageEmoji.ERROR in message for message in messages), messages)
                self.assertFalse(any(backend.main.MessageEmoji.SUCCESS in message for message in messages), messages)
                self.assertEqual(self.plugin.raw_config, previous_raw)
                self.assertIs(self.plugin.plugin_config, previous_runtime)
                self.assertEqual(dict(self.native), previous_native)
                self.assertEqual(Path(self.plugin.config_path).read_bytes(), previous_disk)


if __name__ == "__main__":
    unittest.main()
