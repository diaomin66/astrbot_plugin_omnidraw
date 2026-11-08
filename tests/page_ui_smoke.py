"""Optional browser regression checks; run directly with Python + Playwright.

python tests/page_ui_smoke.py --channel chrome --output /path/to/screenshots
No live AstrBot server, API key, or generation endpoint is used.
"""

import argparse
import hashlib
import json
import re
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread


PAGE_DIR = Path(__file__).resolve().parents[1] / "pages" / "插件配置"


def fixture_config():
    marker = {"preserve": [1, "extension", False]}
    return {
        "future_top_level": marker,
        "permission_config": {
            "usable_users": "10001\n10002",
            "allowed_users": "10001",
            "blocked_users": "20001",
            "unlimited_groups": "30001",
            "extension": marker,
        },
        "usage_config": {
            "enable_daily_limit": True,
            "daily_image_limit": 0,
            "enable_checkin": True,
            "checkin_bonus_min": 0,
            "checkin_bonus_max": 3,
            "extension": marker,
        },
        "cache_config": {
            "enable_scheduled_cleanup": True,
            "scheduled_cleanup_interval_hours": 12,
            "enable_size_limit_cleanup": True,
            "max_cache_size_mb": 256,
            "extension": marker,
        },
        "reply_config": {
            "draw_pending_message": "Drawing {prompt}",
            "selfie_pending_message": "Selfie {persona_name}",
            "draw_error_message": "Draw failed: {error}",
            "selfie_error_message": "Selfie failed: {error}",
            "extension": marker,
        },
        "persona_config": {
            "active_persona_id": "hero",
            "profiles": [
                {"id": "hero", "persona_name": "Hero", "persona_base_prompt": "portrait", "persona_ref_image": [], "extension": marker},
                {"id": "other", "persona_name": "Other", "persona_base_prompt": "sketch", "persona_ref_image": []},
            ],
            "extension": marker,
        },
        "optimizer_config": {
            "enable_optimizer": "false",
            "use_astrbot_provider": True,
            "optimizer_style": "future-style",
            "chain_optimizer": "image",
            "optimizer_model": "optimizer-model",
            "optimizer_timeout": 42,
            "max_batch_count": 4,
            "optimizer_custom_prompt": "keep this",
            "extension": marker,
        },
        "router_config": {"chain_text2img": "image,backup", "chain_selfie": "backup,image", "chain_video": "video", "extension": marker},
        "providers": [
            {"id": "image", "api_type": "openai_image", "base_url": "https://example.invalid/v1", "model": "gpt-image-2.6-flare", "available_models": ["gpt-image-2.6-flare", "gpt-image-1.5"], "timeout": 180, "default_size": "auto", "api_keys": "\u2022\u2022\u2022\u20221234", "extension": marker},
            {"id": "backup", "api_type": "custom_endpoint", "base_url": "https://example.invalid/create", "model": "custom", "available_models": ["custom"], "timeout": 60, "default_size": "", "api_keys": "\u2022\u2022\u2022\u20225678", "extension": marker},
        ],
        "video_providers": [
            {"id": "video", "api_type": "async_task", "base_url": "https://example.invalid/v1", "model": "video-model", "available_models": ["video-model"], "timeout": 300, "default_size": "1280x720", "api_keys": "\u2022\u2022\u2022\u20229012", "extension": marker}
        ],
        "presets": ["portrait:original prompt --size 1024x1024"],
        "verbose_report": "false",
        "show_generation_time": True,
        "show_request_model": True,
    }


BRIDGE_SCRIPT = """
window.testCalls = [];
window.testGets = [];
window.testGetParams = [];
window.testConfig = CONFIG;
window.AstrBotPluginPage = {
    ready: async () => ({}),
    apiGet: async (name, params) => {
        window.testGets.push(name);
        window.testGetParams.push({name, params});
        if (name === 'get_config' || name === 'get_page_config') return structuredClone(window.testConfig);
        if (name === 'get_image') {
            if (window.testPreviewError) return {success: false, message: 'Preview temporarily unavailable'};
            return {success: true, data_url: 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAAAAAAALAAAAAABAAEAAAICRAEAOw=='};
        }
        if (name === 'get_usage_stats') return {success: true, stats: {date: '2026-11-08', total: 0, users: []}};
        return {success: true, stats: {total: {count: 0, bytes: 0, human_size: '0 B'}, dirs: {}}};
    },
    apiPost: async (name, payload) => {
        window.testCalls.push({name, payload: structuredClone(payload)});
        if (window.testHoldSave) await new Promise(resolve => {window.releaseSave = resolve});
        if (window.testSaveDelay) await new Promise(resolve => setTimeout(resolve, window.testSaveDelay));
        return {success: true, persona_refs: window.testSavedRefs, cleanup: {deleted_count: 0}, stats: {total: {count: 0, bytes: 0, human_size: '0 B'}, dirs: {}}};
    }
};
"""


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def check_static_contract():
    html = (PAGE_DIR / "index.html").read_text(encoding="utf-8")
    js = (PAGE_DIR / "app.js").read_text(encoding="utf-8")
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids)), "Duplicate HTML IDs"
    required = set(re.findall(r'byId\("([^"$]+)"\)', js))
    assert required.issubset(set(ids)), f"Missing bound controls: {required - set(ids)}"
    assert len(re.findall(r'class="nav-item', html)) == 7
    assert "sidebar-credit" not in html
    upstream = PAGE_DIR / "src" / "upstream"
    manifest = json.loads((upstream / "SOURCES.json").read_text(encoding="utf-8"))
    assert manifest["repository"] == "https://github.com/CookSleep/gpt_image_playground"
    for name, expected in manifest["files"].items():
        assert hashlib.sha256((upstream / name).read_bytes()).hexdigest() == expected, name
    for name in ("ui.css", "ui.js"):
        assert (PAGE_DIR / "assets" / name).stat().st_size > 10000
    layout = (PAGE_DIR / "src" / "integration.css").read_text(encoding="utf-8")
    assert not re.search(r"\b(?:color|background|border-radius|animation|transition)\s*:", layout), "Host CSS must not restyle source components"


def check_payload(payload, source):
    assert payload["future_top_level"] == source["future_top_level"]
    for key in ("permission_config", "usage_config", "cache_config", "reply_config", "persona_config", "optimizer_config", "router_config"):
        assert payload[key]["extension"] == source[key]["extension"], key
    for key in ("providers", "video_providers"):
        assert payload[key] == source[key], key
    assert payload["persona_config"]["profiles"] == source["persona_config"]["profiles"]
    assert payload["presets"] == source["presets"]
    assert payload["router_config"] == source["router_config"]
    assert payload["usage_config"]["daily_image_limit"] == 0
    assert payload["optimizer_config"]["optimizer_style"] == "future-style"
    assert payload["optimizer_config"]["enable_optimizer"] is False
    assert payload["optimizer_config"]["use_astrbot_provider"] is True
    assert payload["verbose_report"] is False


def run_browser(channel, output):
    from playwright.sync_api import expect, sync_playwright

    def ready(page):
        page.wait_for_selector('main[aria-busy="false"]')
        page.wait_for_selector('html[data-playground-ready="true"]')

    def navigate(page, target):
        tab = page.locator(f'.nav-item[data-target="{target}"]')
        if page.viewport_size["width"] <= 760:
            page.get_by_role("button", name="打开配置导航").click()
            drawer = page.get_by_role("dialog", name="插件配置", exact=True)
            drawer.get_by_role("button", name=tab.inner_text().strip(), exact=True).click()
            expect(drawer).to_have_count(0)
        else:
            tab.click()
        expect(tab).to_have_attribute("aria-current", "page")

    def confirm(page, label="确认移除"):
        overlay = page.locator("#playground-overlay-root")
        overlay.get_by_role("button", name=label, exact=True).click()
        expect(overlay.get_by_role("button", name=label, exact=True)).to_have_count(0)

    def choose(select, value):
        select.click()
        select.locator(f'[data-option-value="{value}"]').click()

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(PAGE_DIR)))
    Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    source = fixture_config()
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=channel or None, headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script(BRIDGE_SCRIPT.replace("CONFIG", json.dumps(source)))
            page.goto(url)
            ready(page)
            assert page.locator('[data-action="save-config"]').is_enabled(), errors
            assert not errors, errors
            assert page.locator('.ios-switch:not([aria-label])').count() == 0
            assert "playground" not in page.locator("body").inner_text().lower()
            page.wait_for_function("""() => Array.from(document.querySelectorAll(
                '.card, .node-card, .route-row, .usage-summary > div, .cache-summary > div, .cache-breakdown > div, .usage-user-row, .section-note, .cache-setting-row'
            )).filter(card => card.getClientRects().length).every(card => getComputedStyle(card).backgroundColor === 'rgb(255, 255, 255)')""")
            assert page.evaluate("window.testGets") == ["get_page_config"]
            assert page.locator("#providers-container .node-card, .image-preview").count() == 0
            page.locator('[data-action="save-config"]').click()
            page.wait_for_function("window.testCalls.some(call => call.name === 'save_config')")
            payload = page.evaluate("window.testCalls.find(call => call.name === 'save_config').payload")
            check_payload(payload, source)
            expect(page.locator(".toast-enter")).to_contain_text("配置已保存")

            targets = page.locator(".nav-item").evaluate_all("items => items.map(item => item.dataset.target)")
            for width, height in ((1440, 1000), (900, 900), (390, 844), (320, 740)):
                page.set_viewport_size({"width": width, "height": height})
                for target in targets:
                    navigate(page, target)
                    assert page.locator(".tab-pane.active").count() == 1
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, target)
                    if output and width in (1440, 390):
                        page.screenshot(path=str(output / f"{width}-{target}.png"), full_page=True)

            page.get_by_role("button", name="打开配置导航").click()
            expect(page.get_by_role("dialog", name="插件配置", exact=True)).to_be_visible()
            page.keyboard.press("Escape")
            expect(page.get_by_role("dialog", name="插件配置", exact=True)).to_have_count(0)

            page.set_viewport_size({"width": 1440, "height": 1000})
            navigate(page, "tab-nodes")
            page.locator('[data-action="show-gif-help"]').click()
            gif_help = page.get_by_role("dialog", name="GPT Image 2.6 · GIF", exact=True)
            expect(gif_help).to_contain_text("gpt-image-2.6-sunburst")
            if output:
                page.screenshot(path=str(output / "upstream-gif-help.png"))
            page.keyboard.press("Escape")
            expect(gif_help).to_have_count(0)

            model_select = page.locator("#providers-container .node-card").first.get_by_role("combobox").nth(1)
            choose(model_select, "gpt-image-1.5")
            expect(model_select).to_have_text("gpt-image-1.5")
            model_select.focus()
            page.keyboard.press("Enter")
            expect(model_select).to_have_attribute("aria-expanded", "true")
            page.keyboard.press("ArrowUp")
            page.keyboard.press("Enter")
            expect(model_select).to_have_text("gpt-image-1.5")
            model_select.focus()
            page.keyboard.press("Enter")
            expect(model_select).to_have_attribute("aria-expanded", "true")
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")
            expect(model_select).to_have_text("gpt-image-2.6-flare")
            page.locator("#new-model-img-0").fill('<svg onload="window.injected=true">')
            page.locator("#new-model-img-0").press("Enter")
            assert page.evaluate("window.injected === undefined")
            model_select.click()
            if output:
                page.screenshot(path=str(output / "upstream-model-select.png"))
            model_select.locator('button[title="删除"]').last.focus()
            page.keyboard.press("Enter")
            confirm(page)
            expect(page.locator('[data-action="del-prov-model"][data-index="0"]')).to_have_count(2)
            page.locator('[data-action="add-provider"]').click()
            expect(page.locator("#providers-container .node-card")).to_have_count(3)
            page.locator('[data-action="del-provider"]').last.click()
            page.locator("#playground-overlay-root").get_by_role("button", name="取消", exact=True).click()
            expect(page.locator("#providers-container .node-card")).to_have_count(3)
            page.locator('[data-action="del-provider"]').last.click()
            confirm(page)
            expect(page.locator("#providers-container .node-card")).to_have_count(2)

            navigate(page, "tab-persona")
            page.locator('[data-action="add-persona"]').click()
            page.locator("#persona_name").fill("New profile")
            page.locator('[data-action="del-persona"]').last.focus()
            page.keyboard.press("Enter")
            confirm(page)
            expect(page.locator(".persona-profile-chip")).to_have_count(2)
            page.locator('[data-action="switch-persona"]').first.click()
            assert page.locator("#persona_name").input_value() == "Hero"
            page.locator("#hidden-file-input").set_input_files({
                "name": "reference.gif", "mimeType": "image/gif",
                "buffer": b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
            })
            page.wait_for_selector(".image-preview")
            page.locator('[data-action="del-persona-img"]').click()
            confirm(page)
            assert page.locator(".image-preview").count() == 0

            navigate(page, "tab-presets")
            page.locator('[data-action="add-preset"]').click()
            assert page.locator(".preset-name").count() == 2
            page.locator('[data-action="del-preset"]').last.click()
            confirm(page)
            navigate(page, "tab-hub")
            backup_switch = page.locator('label[for="route_img_backup"]').get_by_role("switch")
            backup_switch.click()
            expect(page.locator("#route_img_backup")).not_to_be_checked()
            backup_switch.click()
            expect(page.locator("#route_img_backup")).to_be_checked()
            page.locator("#sel-route-img-backup").get_by_role("checkbox", name=re.compile("^backup")).check()
            expect(page.locator("#sel-route-img-backup").get_by_role("checkbox", name="backup · 1", exact=True)).to_be_checked()

            navigate(page, "tab-optimizer")
            optimizer_style = page.locator("#opt_style").locator("..").get_by_role("combobox")
            choose(optimizer_style, "手机日常原生感")
            expect(page.locator("#opt_style")).to_have_value("手机日常原生感")
            choose(optimizer_style, "future-style")

            navigate(page, "tab-usage")
            page.locator('[data-action="refresh-usage"]').click()
            expect(page.locator(".toast-enter")).to_contain_text("统计已刷新")
            page.locator('[data-action="refresh-cache"]').click()
            expect(page.locator(".toast-enter")).to_contain_text("缓存统计已刷新")
            page.locator('[data-action="clear-cache"]').click()
            confirm(page, "清理缓存")
            page.wait_for_function("window.testCalls.some(call => call.name === 'clear_cache')")
            expect(page.locator(".toast-enter")).to_contain_text("已清理")

            navigate(page, "tab-basic")
            page.evaluate("window.testSaveDelay = 500")
            page.locator('[data-action="save-config"]').click()
            page.locator("#reply_draw_pending").fill("Changed while saving")
            page.wait_for_timeout(1000)
            assert page.locator("body").evaluate("el => el.classList.contains('is-dirty')")
            page.evaluate("window.testSaveDelay = 0")
            page.keyboard.press("Control+s")
            page.wait_for_timeout(600)
            assert not page.locator("body").evaluate("el => el.classList.contains('is-dirty')")

            legacy_source = fixture_config()
            legacy_source["permission_config"]["access_users"] = "10001"
            legacy_source["providers"][0].update({"default_size": "", "default_resolution": "old-size", "api_keys": "", "API密钥": "old-key"})
            legacy_source["persona_config"]["profiles"][0].update({"persona_base_prompt": "", "base_prompt": "old-prompt"})
            legacy = browser.new_page()
            legacy.add_init_script(BRIDGE_SCRIPT.replace("CONFIG", json.dumps(legacy_source)))
            legacy.goto(url)
            ready(legacy)
            legacy.locator("#perm_usable_users").fill("")
            legacy.locator('[data-action="save-config"]').click()
            legacy.wait_for_function("window.testCalls.some(call => call.name === 'save_config')")
            legacy_payload = legacy.evaluate("window.testCalls.find(call => call.name === 'save_config').payload")
            assert legacy_payload["permission_config"]["usable_users"] == ""
            assert legacy_payload["permission_config"]["access_users"] == ""
            assert legacy_payload["providers"][0]["default_size"] == ""
            assert legacy_payload["providers"][0]["api_keys"] == ""
            assert legacy_payload["persona_config"]["profiles"][0]["persona_base_prompt"] == ""

            gemini = browser.new_page()
            gemini.on("pageerror", lambda error: errors.append(str(error)))
            gemini.add_init_script(BRIDGE_SCRIPT.replace("CONFIG", json.dumps(source)))
            gemini.goto(url)
            ready(gemini)
            navigate(gemini, "tab-nodes")
            gemini.locator("#prov-url-0").fill("https://relay.example.invalid/gateway/v1beta?tenant=demo")
            gemini.evaluate("window.originalNode = document.getElementById('prov-url-0')")
            gemini.keyboard.press("Control+s")
            gemini.wait_for_function("window.testCalls.length === 1")
            expect(gemini.locator('[data-action="save-config"]')).to_be_enabled()
            assert gemini.evaluate("window.originalNode === document.getElementById('prov-url-0')")
            assert gemini.evaluate("window.testCalls[0].payload.providers[0].base_url") == "https://relay.example.invalid/gateway/v1beta?tenant=demo"
            protocol = gemini.locator("#providers-container .node-card").first.get_by_role("combobox").first
            choose(protocol, "gemini_official")
            expect(gemini.locator("#prov-url-0")).to_have_value("https://relay.example.invalid/gateway/v1beta?tenant=demo")
            gemini.locator("#prov-url-0").fill("https://api.example.com/v1")
            choose(protocol, "openai_image")
            choose(protocol, "gemini_official")
            expect(gemini.locator("#prov-url-0")).to_have_value("https://api.example.com/v1")
            gemini.locator("#prov-url-0").fill("")
            gemini.keyboard.press("Control+s")
            gemini.wait_for_function("window.testCalls.length === 2")
            assert gemini.evaluate("window.testCalls[1].payload.providers[0].base_url") == ""
            expect(gemini.locator("#prov-url-0")).to_have_attribute("placeholder", "https://generativelanguage.googleapis.com/v1beta")

            fallback = browser.new_page()
            fallback.add_init_script(BRIDGE_SCRIPT.replace("CONFIG", json.dumps(source)) + """
                const originalGet = window.AstrBotPluginPage.apiGet;
                window.AstrBotPluginPage.apiGet = async name => {
                    if (name === 'get_page_config') {
                        window.testGets.push(name);
                        throw Object.assign(new Error('endpoint not found'), {status: 404});
                    }
                    return originalGet(name);
                };
            """)
            fallback.goto(url)
            ready(fallback)
            assert fallback.evaluate("window.testGets") == ["get_page_config", "get_config"]
            expect(fallback.locator('[data-action="save-config"]')).to_be_enabled()

            api_failure = browser.new_page()
            api_failure.add_init_script(BRIDGE_SCRIPT.replace("CONFIG", json.dumps(source)) + """
                window.AstrBotPluginPage.apiGet = async name => {
                    window.testGets.push(name);
                    throw Object.assign(new Error('server unavailable'), {status: 503});
                };
            """)
            api_failure.goto(url)
            ready(api_failure)
            assert api_failure.evaluate("window.testGets") == ["get_page_config"]
            expect(api_failure.locator('[data-action="save-config"]')).to_be_disabled()

            stats = browser.new_page()
            stats.add_init_script(BRIDGE_SCRIPT.replace("CONFIG", json.dumps(source)) + """
                const originalGet = window.AstrBotPluginPage.apiGet;
                window.releaseStats = {};
                window.AstrBotPluginPage.apiGet = async name => {
                    if (!['get_usage_stats', 'get_cache_stats'].includes(name)) return originalGet(name);
                    window.testGets.push(name);
                    return new Promise(resolve => { window.releaseStats[name] = () => resolve({success: true, stats: {}}); });
                };
            """)
            stats.goto(url)
            ready(stats)
            assert stats.evaluate("window.testGets") == ["get_page_config"]
            navigate(stats, "tab-usage")
            stats.locator('[data-action="refresh-usage"]').click()
            stats.locator('[data-action="refresh-usage"]').click()
            stats.locator('[data-action="refresh-cache"]').click()
            stats.locator('[data-action="refresh-cache"]').click()
            assert stats.evaluate("window.testGets") == ["get_page_config", "get_usage_stats", "get_cache_stats"]
            navigate(stats, "tab-basic")
            stats.locator("#reply_draw_pending").fill("Stats do not block editing")
            stats.locator('[data-action="save-config"]').click()
            stats.wait_for_function("window.testCalls.length === 1")
            expect(stats.locator('[data-action="save-config"]')).to_be_enabled()
            stats.evaluate("Object.values(window.releaseStats).forEach(release => release())")
            navigate(stats, "tab-usage")
            assert stats.evaluate("window.testGets") == ["get_page_config", "get_usage_stats", "get_cache_stats"]

            old_token = "/astrbot_plugin_omnidraw/get_image?token=" + "a" * 64
            new_token = "/astrbot_plugin_omnidraw/get_image?token=" + "b" * 64
            image_source = fixture_config()
            image_source["persona_config"]["profiles"][0]["persona_ref_image"] = [old_token]
            images = browser.new_page()
            images.on("pageerror", lambda error: errors.append(str(error)))
            unauthorized_requests = []
            images.route("**/astrbot_plugin_omnidraw/get_image?**", lambda route: (
                unauthorized_requests.append(route.request.url), route.fulfill(status=401, body="Forbidden")
            ))
            images.add_init_script(BRIDGE_SCRIPT.replace("CONFIG", json.dumps(image_source)) + """
                window.testPreviewError = true;
                window.revokedPreviews = [];
                const originalRevoke = URL.revokeObjectURL;
                URL.revokeObjectURL = url => { window.revokedPreviews.push(url); originalRevoke(url); };
            """)
            images.goto(url)
            ready(images)
            assert images.locator(".image-preview").count() == 0
            assert images.evaluate("window.testGets") == ["get_page_config"]
            navigate(images, "tab-persona")
            retry = images.get_by_role("button", name="重试预览", exact=True)
            expect(retry).to_be_visible()
            images.evaluate("window.testPreviewError = false")
            retry.click()
            images.wait_for_function("document.querySelector('.image-preview')?.getAttribute('src')?.startsWith('blob:')")
            params = images.evaluate("window.testGetParams.filter(call => call.name === 'get_image')")
            assert len(params) == 2
            assert params[0]["params"] == {"token": "a" * 64, "format": "data_url"}
            assert not unauthorized_requests, unauthorized_requests
            first_upload = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
            images.locator("#hidden-file-input").set_input_files({"name": "first.gif", "mimeType": "image/gif", "buffer": first_upload})
            expect(images.locator(".image-preview")).to_have_count(2)
            saved_refs = {
                "profiles": [{"id": "hero", "persona_ref_image": [old_token, new_token]}, {"id": "other", "persona_ref_image": []}],
                "persona_ref_image": [old_token, new_token],
            }
            images.evaluate("refs => {window.testSavedRefs=refs; window.testHoldSave=true}", saved_refs)
            images.locator('[data-action="save-config"]').click()
            images.locator('[data-action="del-persona-img"]').first.click()
            confirm(images)
            images.locator("#persona_name").fill("Edited during reference mapping")
            images.locator("#hidden-file-input").set_input_files({
                "name": "second.gif", "mimeType": "image/gif", "buffer": first_upload.replace(b"\xff\xff\xff", b"\xff\x00\x00", 1),
            })
            expect(images.locator(".image-preview")).to_have_count(2)
            images.evaluate("window.testHoldSave=false; window.releaseSave()")
            expect(images.locator('[data-action="save-config"]')).to_be_enabled()
            assert images.locator("body").evaluate("el => el.classList.contains('is-dirty')")
            images.evaluate("window.testSavedRefs=null; window.testSaveDelay=0")
            images.locator('[data-action="save-config"]').click()
            images.wait_for_function("window.testCalls.length === 2")
            image_payload = images.evaluate("window.testCalls[1].payload.persona_config")
            assert image_payload["profiles"][0]["persona_name"] == "Edited during reference mapping"
            assert image_payload["profiles"][0]["persona_ref_image"][0] == new_token
            assert image_payload["profiles"][0]["persona_ref_image"][1].startswith("data:image/gif;base64,")
            assert old_token not in image_payload["profiles"][0]["persona_ref_image"]
            assert image_payload["persona_ref_image"] == image_payload["profiles"][0]["persona_ref_image"]
            navigate(images, "tab-basic")
            assert images.evaluate("window.revokedPreviews.length > 0")
            assert not unauthorized_requests, unauthorized_requests

            rejected = browser.new_page()
            rejected.add_init_script(BRIDGE_SCRIPT.replace("CONFIG", json.dumps(source)) + """
                window.AstrBotPluginPage.apiPost = async () => {
                    throw Object.assign(new Error('Reference expired; refresh before retrying'), {status: 400});
                };
            """)
            rejected.goto(url)
            ready(rejected)
            rejected.locator("#reply_draw_pending").fill("Keep unsaved edits")
            rejected.locator('[data-action="save-config"]').click()
            expect(rejected.locator(".toast-enter")).to_contain_text("Reference expired")
            expect(rejected.locator('[data-action="save-config"]')).to_be_enabled()
            assert rejected.locator("body").evaluate("el => el.classList.contains('is-dirty')")

            failed = browser.new_page()
            failed.add_init_script("window.AstrBotPluginPage = {ready: async () => {throw new Error('offline')}, apiPost: async () => {window.badSave=true}}")
            failed.goto(url)
            ready(failed)
            assert failed.locator('[data-action="save-config"]').is_disabled()
            expect(failed.locator(".toast-enter")).to_contain_text("配置页初始化失败")
            failed.keyboard.press("Control+s")
            assert failed.evaluate("window.badSave === undefined")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    assert not errors, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default=None, help="Installed browser, e.g. chrome or msedge")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
    check_static_contract()
    run_browser(args.channel, args.output)
    print("PASS: upstream integrity, configuration roundtrip, seven tabs at four sizes, source controls, keyboard navigation, lazy authenticated previews, race-safe reference mapping, Gemini host retention, deduplicated stats, API fallback, save race, offline/error guards")


if __name__ == "__main__":
    main()
