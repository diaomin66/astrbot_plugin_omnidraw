"""Verify the requested upstream component reuse and no-build deployment contract."""

import hashlib
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "插件配置"
UPSTREAM = PAGE / "src" / "upstream"


class PageSourceContractTest(unittest.TestCase):
    def test_vendored_components_match_pinned_upstream_blobs(self):
        manifest = json.loads((UPSTREAM / "SOURCES.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["repository"], "https://github.com/CookSleep/gpt_image_playground")
        self.assertEqual(manifest["revision"], "6f8f44dadf77f7880f0db1eefb004fe0474b27d4")
        for name, digest in manifest["files"].items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((UPSTREAM / name).read_bytes()).hexdigest(), digest)

    def test_production_assets_are_shipped_and_need_no_node_runtime(self):
        html = (PAGE / "index.html").read_text(encoding="utf-8")
        js = (PAGE / "assets" / "ui.js").read_text(encoding="utf-8")
        css = (PAGE / "assets" / "ui.css").read_text(encoding="utf-8")
        self.assertIn("./assets/ui.js?", html)
        self.assertIn("./assets/ui.css?", html)
        self.assertGreater(len(js), 1000)
        self.assertGreater(len(css), 1000)
        self.assertNotIn("process.env.NODE_ENV", js)
        self.assertNotRegex(html, r'<script[^>]+src=["\']https?://')

    def test_original_palette_and_components_are_used_instead_of_replacements(self):
        source = (PAGE / "src" / "main.tsx").read_text(encoding="utf-8")
        css = (UPSTREAM / "index.css").read_text(encoding="utf-8")
        for component in ("Select", "Checkbox", "ConfirmDialog", "Toast"):
            self.assertIn(f"./upstream/components/{component}", source)
        self.assertIn("./upstream/index.css", source)
        self.assertIn("--primary: 221 83% 53%", css)
        self.assertFalse((PAGE / "playground-ui.css").exists())
        layout = (PAGE / "src" / "integration.css").read_text(encoding="utf-8")
        self.assertNotRegex(layout, r"--(?:primary|background|foreground)\s*:")

    def test_runtime_and_page_versions_agree(self):
        metadata = (ROOT / "metadata.yaml").read_text(encoding="utf-8")
        models = (ROOT / "models.py").read_text(encoding="utf-8")
        version = re.search(r"^version:\s*(\S+)", metadata, re.M).group(1)
        self.assertIn(f'PLUGIN_VERSION = "{version}"', models)
        package = json.loads((PAGE / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(package["version"], version)
        lock = json.loads((PAGE / "package-lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["version"], version)
        self.assertEqual(lock["packages"][""]["version"], version)
        html = (PAGE / "index.html").read_text(encoding="utf-8")
        assets = re.findall(r'(?:src|href)="\./(?:assets/ui\.(?:js|css)|app\.js)\?v=([^"]+)"', html)
        self.assertEqual(len(assets), 3)
        for cache_version in assets:
            self.assertEqual(cache_version.split("-", 1)[0], version)
        compat_css = (PAGE / "style.css").read_text(encoding="utf-8")
        self.assertIn(f"assets/ui.css?v={version}-", compat_css)
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertEqual(re.search(r"^## (\S+)", changelog, re.M).group(1), version)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"**{version}**", readme)
        self.assertIn(f"CHANGELOG.md#{version.replace('.', '')}", readme)

    def test_white_cards_without_page_vendor_credit(self):
        html = (PAGE / "index.html").read_text(encoding="utf-8")
        self.assertNotRegex(html, r"(?i)(?:gpt[ _]image[ _]playground|cooksleep)")
        source = (PAGE / "src" / "main.tsx").read_text(encoding="utf-8")
        cards = re.search(r"'\.card, \.node-card, \.route-row': '([^']+)'", source)
        self.assertIsNotNone(cards)
        self.assertIn("bg-white", cards.group(1).split())
        self.assertTrue((UPSTREAM / "LICENSE").is_file())
        self.assertIn("CookSleep/gpt_image_playground", (ROOT / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
