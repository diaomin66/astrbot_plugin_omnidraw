# 3.4.0 development-stage validation record

This historical stage is included in the combined 3.4.1 release. See the
[final 3.4.1 record](release-validation-3.4.1.md) for the current release scope,
additional Gemini and performance checks, actual-host measurements and remaining
limits. The counts below describe the earlier stage, not the final test suite.

Validated on 2026-11-08 with Python 3.13, an installed AstrBot 4.27.4 package for
host-import checks, and local Chrome. No paid image generation or live
chat-platform delivery was performed.

## Automated checks

| Check | Result |
| --- | --- |
| `python -B -m pytest -q` | 181 passed, 91 subtests passed |
| `python -m ruff check .` | Passed |
| `npm run build` in the Page package directory | TypeScript `--noEmit` and Vite passed; static assets rebuilt |
| `node --check` for the Page's `app.js` | Passed |
| `python -B tests/page_ui_smoke.py --channel chrome --output <directory>` | Passed on the final white-card build |
| Vendored source SHA-256 checks | All 13 original upstream files match the pinned source manifest |
| `git diff --check` for this work | Passed |

The GIF tests cover JSON and multipart field types, supported model and endpoint
selection, parameter bounds, inline/URL response handling, original GIF bytes,
send-as-file fallback, reference-image limits, quota paths, return-only calls,
old `gif` macros, batch cache leases and cancellation cleanup.

The browser checks use a simulated `AstrBotPluginPage` bridge and synthetic
configuration. They cover all seven tabs at 1440x1000, 900x900, 390x844 and
320x740, with no page errors or horizontal overflow. Coverage includes:

- Configuration payload roundtrips, masked keys, legacy empty values, zero
  quota and optimizer styles not present in the built-in choices.
- Model, node, persona, reference GIF and preset editing; confirmation and
  cancellation; ordered backup routes; switches and checkboxes.
- Original React Select mouse and Arrow/Enter interactions, navigation and
  help overlays, Escape dismissal and toast notifications.
- Cache refresh/cleanup, editing during a pending save, and disabled saving
  after configuration initialization fails.
- White card backgrounds and no visible third-party project credit in the
  Page; README acknowledgment and license files remain present.

## Host compatibility checks

Importing the plugin against the installed AstrBot package succeeded in an
isolated host-data directory. Existing
LLM tools registered with the appended optional GIF arguments. AST comparison
confirmed that existing public positional arguments and defaults are preserved;
the configuration schema has no changes from the preceding 3.3.23 baseline.
Existing normalization and safety checks still apply; no guarantee of retaining
unsupported fields is implied.

The installed AstrBot `PluginPageService` successfully rewrote the final HTML
asset URLs while retaining version parameters and the asset token, and injected
the bridge SDK. Rewriting the bundled JS and CSS did not alter their contents.
This checks host asset handling, not a running authenticated dashboard session.

## Remaining integration checks

- GIF preview entitlement, relay-specific behavior, actual model size budgets,
  animation quality and delivery/playback must be checked with the intended
  account and chat adapter. A successful image send that is silently flattened
  by a platform cannot trigger the exception-based file fallback.
- A relay's HTTP result is checked when downloaded. A non-GIF HTTP result fails
  safely rather than being mislabeled, but does not restart the provider chain.
- Frontend extension-field preservation applies to the submitted payload. The
  backend retains its existing normalization and security filtering rules.
- Existing partial-batch quota behavior is not redesigned in this release.
- This record does not claim verification of every AstrBot version declared in
  plugin metadata. Follow the installed host's Python requirements.

For official request sources and preview restrictions, see
[`gif-api-research.md`](gif-api-research.md).
