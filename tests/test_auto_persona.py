import asyncio
import copy
import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / "core" / "auto_persona.py"
spec = importlib.util.spec_from_file_location("auto_persona_under_test", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
select = module.select_selfie_persona

PROFILES = [
    {"id": "chibi", "persona_name": "Q版", "persona_ref_image": ["chibi.png"]},
    {"id": "mature", "persona_name": "成熟女仆", "persona_ref_image": ["maid.png"]},
    {"id": "work", "persona_name": "工装", "persona_ref_image": ["work.png"]},
    {"id": "sailor", "persona_name": "水手服", "persona_ref_image": ["sailor.png"]},
    {"id": "sleep", "persona_name": "睡衣", "persona_ref_image": ["sleep.png"]},
]
SETTINGS = {
    "enabled": True,
    "mature_persona_id": "mature",
    "chibi_persona_id": "chibi",
    "maid_persona_id": "mature",
    "workwear_persona_id": "work",
    "sailor_persona_id": "sailor",
    "sleepwear_persona_id": "sleep",
}
WARDROBE = [
    {"description": "整体风格：女仆；服装：蓝白女仆服。"},
    {"description": "整体风格：工装；服装：深蓝连帽卫衣与工装裤。"},
    {"description": "整体风格：水手服；服装：白色水手上衣与蓝裙。"},
    {"description": "整体风格：睡衣；服装：鲸鱼连体睡衣。"},
]


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("穿水手服去咖啡店", "sailor"),
        ("穿女仆服写代码", "mature"),
        ("写代码", "work"),
        ("睡前自拍", "sleep"),
        ("Q版写代码", "chibi"),
        ("chibi wearing a hoodie", "chibi"),
        ("不要Q版，成熟版穿工装", "work"),
        ("不是Q版，成熟版穿女仆服", "mature"),
        ("不要改成Q版，穿水手服", "sailor"),
        ("不要睡衣，穿水手服", "sailor"),
        ("mature, not chibi, wearing a maid outfit", "mature"),
    ],
)
def test_explicit_request_wins_over_schedule(action, expected):
    result = select(
        SETTINGS,
        PROFILES,
        "mature",
        action,
        {"current_activity": "22:30 睡觉", "outfit": "女仆服"},
        WARDROBE,
    )
    assert result["persona_id"] == expected


@pytest.mark.parametrize(
    ("activity", "outfit", "expected"),
    [
        ("09:00 写代码", "女仆服", "work"),
        ("22:30 睡觉", "工装", "sleep"),
        ("15:00 喝咖啡", "水手服", "sailor"),
    ],
)
def test_current_activity_then_daily_outfit(activity, outfit, expected):
    result = select(
        SETTINGS,
        PROFILES,
        "mature",
        "",
        {"current_activity": activity, "outfit": outfit},
        WARDROBE,
    )
    assert result["persona_id"] == expected
    assert result["life_context"]["outfit"] in [p["description"] for p in WARDROBE]


def test_future_sleep_entry_does_not_select_sleepwear():
    context = {
        "current_activity": "14:00 在咖啡店看书",
        "outfit": "女仆服",
        "schedule": "09:00 写代码\n14:00 看书\n22:30 睡觉",
    }
    assert (
        select(SETTINGS, PROFILES, "mature", "", context, WARDROBE)["persona_id"]
        == "mature"
    )


def test_explicit_profile_overrides_automatic_activity():
    result = select(
        SETTINGS,
        PROFILES,
        "mature",
        "写代码",
        {"current_activity": "睡觉"},
        WARDROBE,
        persona_id="水手服",
    )
    assert result["persona_id"] == "sailor"
    with pytest.raises(ValueError, match="Unknown selfie persona"):
        select(SETTINGS, PROFILES, "mature", "", persona_id="nonexistent")


def test_disabled_mode_keeps_manual_default():
    settings = {**SETTINGS, "enabled": False}
    assert (
        select(settings, PROFILES, "sailor", "写代码", {"current_activity": "睡觉"})[
            "persona_id"
        ]
        == "sailor"
    )


def test_manual_chibi_default_and_explicit_mature():
    assert select(SETTINGS, PROFILES, "chibi", "写代码")["persona_id"] == "chibi"
    assert select(SETTINGS, PROFILES, "chibi", "成熟版写代码")["persona_id"] == "work"


def test_unconfigured_route_falls_back_to_manual_default():
    settings = {**SETTINGS, "workwear_persona_id": "missing"}
    assert select(settings, PROFILES, "mature", "写代码")["persona_id"] == "mature"


def test_partial_page_save_preserves_automatic_settings_and_config_identity():
    from test_custom_endpoint import OmniDrawPlugin

    plugin = object.__new__(OmniDrawPlugin)
    plugin.raw_config = {
        "auto_persona_config": copy.deepcopy(SETTINGS),
        "persona_config": {"active_persona_id": "mature"},
        "providers": [{"id": "node_1", "model": "fixture"}],
    }
    previous = copy.deepcopy(plugin.raw_config)
    merged = plugin._merge_config_payload(
        {"reply_config": {"selfie_pending_message": "wait"}}
    )
    assert merged["auto_persona_config"] == SETTINGS
    assert merged["persona_config"]["active_persona_id"] == "mature"
    merged["auto_persona_config"]["enabled"] = False
    assert plugin.raw_config == previous
    assert plugin._has_config_payload({"auto_persona_config": SETTINGS})
    assert not plugin._has_config_payload(None)


def test_life_integration_reads_only_cache_and_uses_current_activity(tmp_path):
    import types

    from test_custom_endpoint import OmniDrawPlugin, PluginConfig

    calls = []

    class Life:
        wardrobe_mgr = types.SimpleNamespace(all=lambda: copy.deepcopy(WARDROBE))

        async def get_life_context(self, *, allow_generate):
            calls.append(allow_generate)
            return {"current_activity": "09:00 写代码", "outfit": "女仆服"}

    plugin = object.__new__(OmniDrawPlugin)
    plugin.raw_config = {"auto_persona_config": SETTINGS}
    plugin.plugin_config = PluginConfig.from_dict(
        {"persona_config": {"profiles": PROFILES, "active_persona_id": "mature"}},
        str(tmp_path),
        cleanup_persona_refs=False,
    )
    plugin._refresh_from_native_config_if_changed = lambda: None
    plugin.context = types.SimpleNamespace(
        get_registered_star=lambda name: types.SimpleNamespace(star_cls=Life())
    )
    result = asyncio.run(plugin.resolve_selfie_context())
    assert calls == [False]
    assert result["persona_id"] == "work"
    assert result["life_context"]["outfit"] == WARDROBE[1]["description"]
    assert plugin.plugin_config.active_persona_id == "mature"


@pytest.mark.parametrize(
    "payload", [None, [], {"life_context": []}, {"action": "a" * 20001}]
)
def test_preview_rejects_invalid_payload_without_generating(monkeypatch, payload):
    from test_custom_endpoint import OmniDrawPlugin, main_module

    class Request:
        async def get_json(self, **kwargs):
            return payload

    plugin = object.__new__(OmniDrawPlugin)
    monkeypatch.setattr(main_module, "request", Request())
    monkeypatch.setattr(main_module, "jsonify", lambda value: value)
    result, status = asyncio.run(plugin.resolve_selfie_context_handler())
    assert status == 400
    assert result["success"] is False


def test_concurrent_selection_does_not_mutate_inputs():
    settings = copy.deepcopy(SETTINGS)
    profiles = copy.deepcopy(PROFILES)
    context = {
        "current_activity": "14:00 看书",
        "outfit": "女仆服",
        "meta": {"style": "女仆"},
    }
    previous = copy.deepcopy((settings, profiles, context, WARDROBE))

    async def run(action):
        await asyncio.sleep(0)
        return select(settings, profiles, "mature", action, context, WARDROBE)

    async def gather():
        return await asyncio.gather(run("写代码"), run("睡前自拍"), run("Q版穿水手服"))

    results = asyncio.run(gather())
    assert [item["persona_id"] for item in results] == ["work", "sleep", "chibi"]
    assert (settings, profiles, context, WARDROBE) == previous
    assert results[0]["life_context"]["outfit"] != results[1]["life_context"]["outfit"]


def test_shared_generation_keeps_concurrent_personas_and_references_separate(
    monkeypatch, tmp_path
):
    import types

    from test_custom_endpoint import (
        ChainRunResult,
        OmniDrawPlugin,
        PluginConfig,
        main_module,
    )

    raw = {
        "auto_persona_config": SETTINGS,
        "persona_config": {
            "active_persona_id": "mature",
            "profiles": [
                {
                    **p,
                    "persona_base_prompt": "PROFILE=" + p["id"],
                    "persona_ref_image": ["https://example.test/" + p["id"] + ".png"],
                }
                for p in PROFILES
            ],
        },
        "optimizer_config": {"enable_optimizer": False},
        "router_config": {"chain_selfie": "node_1"},
    }
    plugin = object.__new__(OmniDrawPlugin)
    plugin.raw_config = copy.deepcopy(raw)
    plugin.plugin_config = PluginConfig.from_dict(
        plugin.raw_config, str(tmp_path), cleanup_persona_refs=False
    )
    plugin.persona_manager = main_module.PersonaManager(plugin.plugin_config)
    plugin._refresh_from_native_config_if_changed = lambda: None
    plugin.context = types.SimpleNamespace(get_registered_star=lambda name: None)
    plugin._lease_cache_paths = lambda paths: []
    plugin._release_cache_paths = lambda paths: None
    calls = []

    class Optimizer:
        async def optimize(self, action, count, **kwargs):
            await asyncio.sleep(0)
            return [action] * count

    class Chain:
        def __init__(self, config, session):
            self.config = config

        async def run_chain_with_metadata(self, chain_name, prompt, **kwargs):
            await asyncio.sleep(0)
            calls.append(
                (self.config.active_persona_id, prompt, kwargs.get("user_refs"))
            )
            return ChainRunResult(
                image_url="https://example.test/output.png",
                provider_id="node_1",
                model="fixture",
                elapsed_seconds=0.1,
            )

    async def images(refs, **kwargs):
        return refs

    plugin.prompt_optimizer = Optimizer()
    plugin._process_and_save_images = images
    monkeypatch.setattr(main_module, "ChainManager", Chain)

    async def gather():
        return await asyncio.gather(
            plugin._run_selfie_generation(None, "写代码", 1),
            plugin._run_selfie_generation(None, "睡前自拍", 1),
            plugin._run_selfie_generation(None, "Q版穿水手服", 1),
        )

    results = asyncio.run(gather())
    assert [result["persona_id"] for result in results] == ["work", "sleep", "chibi"]
    for persona, prompt, refs in calls:
        assert "PROFILE=" + persona in prompt
        assert refs == ["https://example.test/" + persona + ".png"]
    assert plugin.plugin_config.active_persona_id == "mature"
    assert plugin.raw_config["persona_config"]["active_persona_id"] == "mature"
