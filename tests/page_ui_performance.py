"""Repeatable local-only browser benchmark for the configuration page.

python tests/page_ui_performance.py --channel chrome --output /path/to/report.json
Use --page-dir to compare a saved page snapshot and --assert-performance for the
optimized page. All API traffic is simulated; no real configuration is read.
"""

import argparse
import hashlib
import json
import statistics
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from page_ui_smoke import fixture_config


PAGE_DIR = Path(__file__).resolve().parents[1] / "pages" / "\u63d2\u4ef6\u914d\u7f6e"
TYPING_SAMPLE = "Measured typing stays local to the field"


def large_fixture():
    config = fixture_config()
    template = config["providers"][0]
    for index in range(2, 80):
        provider = dict(template)
        provider["id"] = f"image-{index}"
        provider["available_models"] = [template["model"], *[f"compat-model-{model}" for model in range(6)]]
        config["providers"].append(provider)
    config["persona_config"]["profiles"][0]["persona_ref_image"] = [
        f"/reference-preview/mock-{index}.gif" for index in range(12)
    ]
    return config


INSTRUMENTATION = r"""
window.perfData = {api: [], queries: {document: 0, element: 0}};
const nativeDocumentQueryAll = Document.prototype.querySelectorAll;
const nativeDocumentQuery = Document.prototype.querySelector;
const nativeElementQueryAll = Element.prototype.querySelectorAll;
Document.prototype.querySelectorAll = function(...args) {
    window.perfData.queries.document++;
    return nativeDocumentQueryAll.apply(this, args);
};
Element.prototype.querySelectorAll = function(...args) {
    window.perfData.queries.element++;
    return nativeElementQueryAll.apply(this, args);
};
const pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const config = CONFIG;
window.AstrBotPluginPage = {
    ready: async () => ({}),
    apiGet: async name => {
        const entry = {name, started: performance.now()};
        window.perfData.api.push(entry);
        const isConfig = name === 'get_config' || name === 'get_page_config';
        await pause(isConfig ? 40 : 600);
        entry.finished = performance.now();
        if (isConfig) return structuredClone(config);
        if (name === 'get_usage_stats') return {success: true, stats: {date: '2026-11-08', total: 0, users: []}};
        return {success: true, stats: {total: {count: 0, bytes: 0, human_size: '0 B'}, dirs: {}}};
    },
    apiPost: async (name, payload) => {
        const entry = {name, started: performance.now()};
        window.perfData.api.push(entry);
        window.perfData.savedProviderCount = payload.providers?.length;
        await pause(80);
        entry.finished = performance.now();
        if (name === 'save_config') window.perfData.saveRespondedAt = entry.finished;
        return {success: true};
    }
};
document.addEventListener('DOMContentLoaded', () => {
    const main = nativeDocumentQuery.call(document, 'main');
    const save = nativeDocumentQuery.call(document, '[data-action="save-config"]');
    const check = () => {
        const data = window.perfData;
        if (main.getAttribute('aria-busy') === 'false' && !save.disabled && !data.firstReadyAt) {
            data.firstReadyAt = performance.now();
            data.apiAtReady = data.api.map(entry => entry.name);
            data.providerCardsAtReady = nativeDocumentQueryAll.call(document, '#providers-container .node-card').length;
            data.previewImagesAtReady = nativeDocumentQueryAll.call(document, '.image-preview').length;
            data.islandsAtReady = nativeDocumentQueryAll.call(document, '[data-playground-island]').length;
            data.elementsAtReady = nativeDocumentQueryAll.call(document, '*').length;
        }
        if (data.saveRespondedAt && !save.disabled && !data.saveEnabledAt) data.saveEnabledAt = performance.now();
    };
    const observer = new MutationObserver(check);
    observer.observe(main, {attributes: true, attributeFilter: ['aria-busy']});
    observer.observe(save, {attributes: true, attributeFilter: ['disabled']});
    check();
});
"""


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def counters(page):
    return page.evaluate("({...window.perfData.queries})")


def differences(before, after):
    return {name: after[name] - value for name, value in before.items()}


def benchmark(page_dir, channel, runs):
    from playwright.sync_api import sync_playwright

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(page_dir)))
    Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    results = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=channel or None, headless=True)
            for run in range(runs):
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                # Keep preview traffic local and deterministic, even if a page eagerly loads it.
                page.route("**/reference-preview/**", lambda route: route.fulfill(status=204, body=""))
                page.add_init_script(INSTRUMENTATION.replace("CONFIG", json.dumps(large_fixture())))
                page.goto(url)
                page.wait_for_function("window.perfData.firstReadyAt > 0")
                page.wait_for_selector('html[data-playground-ready="true"]')
                page.wait_for_timeout(300)

                idle_before = counters(page)
                page.wait_for_timeout(1000)
                idle = differences(idle_before, counters(page))

                field = page.locator("#reply_draw_pending")
                field.fill("")
                page.wait_for_timeout(100)
                typing_before = counters(page)
                field.press_sequentially(TYPING_SAMPLE, delay=10)
                page.wait_for_timeout(100)
                typing = differences(typing_before, counters(page))

                page.evaluate("""() => {
                    window.perfData.saveClickedAt = performance.now();
                    document.querySelector('[data-action="save-config"]').click();
                }""")
                page.wait_for_function("window.perfData.saveEnabledAt > 0")
                page.evaluate("""() => {
                    window.perfData.nodesClickedAt = performance.now();
                    document.querySelector('[data-target="tab-nodes"]').click();
                }""")
                page.wait_for_selector('#providers-container .node-card [role="combobox"]')
                nodes_ready = page.evaluate("performance.now() - window.perfData.nodesClickedAt")
                assert page.locator("#providers-container .node-card").count() == 80
                model = page.locator("#providers-container .node-card").first.get_by_role("combobox").nth(1)
                model.click()
                page.wait_for_selector('[data-option-value="gpt-image-1.5"]')
                data = page.evaluate("window.perfData")
                config_call = next(call for call in data["api"] if call["name"] in {"get_config", "get_page_config"})
                result = {
                    "run": run + 1,
                    "first_ready_ms": round(data["firstReadyAt"], 2),
                    "config_response_to_ready_ms": round(data["firstReadyAt"] - config_call["finished"], 2),
                    "first_node_tab_ready_ms": round(nodes_ready, 2),
                    "save_total_ms": round(data["saveEnabledAt"] - data["saveClickedAt"], 2),
                    "save_response_to_enabled_ms": round(data["saveEnabledAt"] - data["saveRespondedAt"], 2),
                    "idle_1000ms_queries": idle,
                    "typing_40chars_queries": typing,
                    "api_at_ready": data["apiAtReady"],
                    "provider_cards_at_ready": data["providerCardsAtReady"],
                    "preview_images_at_ready": data["previewImagesAtReady"],
                    "islands_at_ready": data["islandsAtReady"],
                    "elements_at_ready": data["elementsAtReady"],
                    "saved_provider_count": data["savedProviderCount"],
                    "page_errors": errors,
                }
                assert not errors, errors
                results.append(result)
                print(json.dumps(result, ensure_ascii=True))
                context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    metrics = ("first_ready_ms", "config_response_to_ready_ms", "first_node_tab_ready_ms", "save_total_ms", "save_response_to_enabled_ms")
    return {
        "page_dir": str(page_dir.resolve()),
        "artifacts_sha256": {name: hashlib.sha256((page_dir / name).read_bytes()).hexdigest() for name in ("app.js", "assets/ui.js")},
        "conditions": {"browser_channel": channel, "viewport": [1440, 1000], "providers": 80, "preview_refs": 12, "config_delay_ms": 40, "stats_delay_ms": 600, "save_delay_ms": 80, "typing_characters": len(TYPING_SAMPLE), "runs": runs},
        "median": {metric: round(statistics.median(result[metric] for result in results), 2) for metric in metrics},
        "median_counts": {metric: {scope: statistics.median(result[metric][scope] for result in results) for scope in ("document", "element")} for metric in ("idle_1000ms_queries", "typing_40chars_queries")},
        "runs": results,
    }


def assert_performance(report):
    for result in report["runs"]:
        assert not ({"get_usage_stats", "get_cache_stats"} & set(result["api_at_ready"])), result
        assert result["provider_cards_at_ready"] == 0, result
        assert result["preview_images_at_ready"] == 0, result
        assert result["idle_1000ms_queries"]["document"] == 0, result
        assert result["typing_40chars_queries"]["document"] == 0, result
        assert result["save_response_to_enabled_ms"] < 150, result
        assert result["config_response_to_ready_ms"] < 500, result
        assert result["saved_provider_count"] == 80, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page-dir", type=Path, default=PAGE_DIR)
    parser.add_argument("--channel", default=None)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--assert-performance", action="store_true")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    report = benchmark(args.page_dir, args.channel, args.runs)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print("MEDIAN " + json.dumps(report["median"]))
    if args.assert_performance:
        assert_performance(report)
        print("PASS: lazy initialization, no idle/global typing scans, immediate save completion, unchanged provider payload")


if __name__ == "__main__":
    main()
