# 3.4.1 validation

Validation date: 2026-11-08. This is the final release record for the combined
3.3.23-to-3.4.1 update. It includes the GIF and UI work recorded during the
[3.4.0 development stage](release-validation-3.4.0.md); installing that
intermediate version is not required.

## Scope

- Keep the existing configuration schema and public argument order/defaults;
  append optional GIF arguments instead of replacing static-generation APIs.
- Add native GPT Image 2.6 Sunburst/Flare GIF requests, `/gif`, LLM guidance,
  original-byte delivery, send-as-file fallback and protected cache lifetimes.
- Replace the Page layout with left navigation and a consistent white-card UI
  using the pinned upstream components, styles and license notices.
- Add an opt-in compact Page configuration endpoint; keep legacy `get_config` output.
- Load protected persona previews through the actual AstrBot JSON bridge, on demand.
- Move configuration I/O off the event loop, keep rollback inside the transaction lock,
  and retain old reference files until a successful commit.
- Include chat-side configuration changes in the same transaction lock used by
  Page saves to prevent interleaved read-modify-write operations; commands read
  the latest configuration after acquiring the lock.
- Fix Gemini native endpoint composition without changing a configured custom host.
- Retain the existing normalization and security filters. Frontend payload
  preservation is not a guarantee that arbitrary backend extension fields survive.

## Environments

- Local Python tests ran with Python 3.13 and host stubs. Backend fixtures use
  real plugin initialization and temporary files, not production configuration.
- Earlier host-import checks used AstrBot 4.27.4. The deployed 3.4.1 candidate
  and actual-host probes used AstrBot 4.29.1 with Python 3.12.15.
- Browser checks used Chrome. Python 3.9 syntax parsing is a source-compatibility
  check, not a claim that current AstrBot can run on Python 3.9. The installed
  host's Python requirements still apply.

## Automated verification

- The final local regression suite passed 236 Python tests and 158 subtests in
  53.32 seconds, including the chat/Page transaction coverage.
- Ruff passes; Python sources parse with the supported Python 3.9 syntax target.
- TypeScript checking and Vite production build pass; generated JS/CSS ship with the plugin.
- Chrome regression covers all seven tabs at 1440, 900, 390 and 320 pixel widths.
- Page tests cover lazy statistics/rendering, input without global rescans, API fallback
  only for an unsupported endpoint, and save/edit concurrency without losing later edits.
- Preview tests verify `apiGet('get_image', {token, format: 'data_url'})`, no direct
  unauthenticated image request, retry/release behavior, and unchanged token save payloads.
- Backend tests use the actual plugin initialization with isolated temporary data and
  simulated AstrBot/Quart. They cover stable and expired preview tokens, masked keys,
  unchanged-save fast paths, image-preserving rollback, concurrent saves, repeated
  cancellation, native-file change detection and cache scheduler stability.
- Gemini fake-HTTP tests cover bare origins, explicit versions, proxy prefixes,
  `/models/` in intermediate prefixes, complete endpoints, pinned models, query strings,
  empty defaults and invalid nonempty URLs. No paid generation request is made.

### Reproduction

From the repository root, in a development environment:

```sh
python -m pip install -r requirements.txt
python -m pip install pytest ruff playwright
python -B -m pytest -q
python -m ruff check .
git diff --check
```

In the Page package directory described in the README, rebuild frontend assets
after source edits:

```sh
npm ci
npm run build
node --check app.js
```

Return to the repository root. Run browser checks with an installed Chrome, or
omit `--channel chrome` after installing Playwright's Chromium with
`python -m playwright install chromium`:

```sh
python -B tests/page_ui_smoke.py --channel chrome
python -B tests/page_ui_performance.py --channel chrome --runs 5 --assert-performance
```

The performance script accepts `--page-dir` to measure a separately saved Page
snapshot. Its API traffic is simulated; these commands do not need provider
credentials and do not submit generation requests. The release checks also
verify the runtime, metadata, Page package/lockfile, cache-version markers and
release-document version references, plus the upstream source hashes.

## Performance methodology

The browser benchmark uses Chrome at 1440 x 1000 with 80 image nodes, 12 references,
a simulated 40 ms configuration request, 600 ms statistics requests and an 80 ms save
request. Five runs report medians. This measures Page overhead, not Internet latency
or a promise about every user's device. See `tests/page_ui_performance.py` for reproduction.

| Browser measurement | 3.4.0 | 3.4.1 |
| --- | ---: | ---: |
| Initial configuration editable | 792.3 ms | 150.8 ms |
| Configuration response to editable | 624.0 ms | 2.2 ms |
| Save click to button enabled | 527.2 ms | 84.9 ms |
| Save response to button enabled | 439.8 ms | 1.1 ms |
| Document queries during 40-character input | 988 | 0 |
| Element queries during 40-character input | 6422 | 0 |

Both versions perform zero scans during the idle-only sample; the removed overhead
was interaction-driven, not a continuous idle loop. The first screen no longer builds
all 80 node cards or all 12 image previews, but all 80 nodes remain in the save payload.

### Actual-host measurements

The following configuration-read measurements were taken over the running
server's loopback interface with authenticated GET requests, five reads per
endpoint. These compare the legacy and compact endpoints on the previously
deployed 3.4.1 candidate, not two separate production versions:

| Measurement | Response size | Median elapsed time |
| --- | ---: | ---: |
| Live legacy `get_config` GET | 20,406,395 bytes | 266.99 ms |
| Live compact `get_page_config` GET | 2,687 bytes | 7.97 ms |
| Actual-host save handler, isolated copied fixture | 409 bytes | 5.61 ms |

The large legacy response contains local images as Base64 in both profiles and
the active-persona mirror. The compact response contains protected references;
preview bytes are transferred separately on demand, so 2,687 bytes is not the
total transfer size when a user opens every image. Legacy clients still receive
the original response format.

The save row uses real AstrBot/Quart handlers and real disk writes, but only in
a private copied fixture with a separate host root. Five saves alternated a
setting, then restored the fixture's original configuration. Configuration
roundtrips and reference hashes were checked. **No production save POST was
used for benchmarking.** The browser's 80 ms save response is simulated and is
also not a measurement of production save latency.

Results depend on payload size, disk, host, browser and network. They are not
an SLA and do not measure model inference or chat-platform delivery speed.

## Deployment verification

The earlier 3.4.1 candidate deployment completed and the running AstrBot instance
passed its health checks. The procedure took a fresh snapshot of the latest
configuration and plugin data after stopping only the AstrBot container, then
replaced plugin code while preserving the live data directories. It did not
copy local example configuration or benchmark fixture settings into production.

Verification covered the release-file manifest, isolated import against the
actual host, running-container health, configuration semantics, reference-file
hashes and authenticated Page assets. Live checks also confirmed stable compact
references, matching binary and JSON preview bytes, rejected unauthenticated
configuration reads and a 404 for an unknown preview token.

The final PR revision additionally protects concurrent chat-side configuration
changes and Page saves. This protection has local regression coverage but is not
part of the earlier deployed candidate; the final PR revision has not been redeployed.

Real-host save probes use a private `/tmp` fixture with a separate `ASTRBOT_ROOT`.
Live performance checks use authenticated GET requests only; do not POST a potentially
stale configuration merely to measure save latency. Save timing from fixtures and
browser mocks is reported separately from live configuration-read timing.

GET handlers may still persist a native configuration change detected during hot
reload; "GET-only" describes the requests made, not an unconditional guarantee
of zero internal writes. Configuration was not edited during the read benchmark.

## Compatibility and remaining limits

- No required configuration key was added. Existing node order, routes, persona
  data, presets and permissions remain under the same normalization rules; invalid
  entries, reserved command names and unsupported top-level keys may still be
  filtered. Take a fresh full backup before upgrading.
- Existing `gif` macros retain precedence. Using the ordinary draw command with
  `--output_format gif` remains available without renaming that macro. Default
  image and video calls remain static/video calls unless GIF is explicitly
  requested for an image tool.
- Preview tokens are opaque and stable only within a running plugin instance.
  Restart or bounded token-cache eviction may expire them. Saving an expired
  token fails instead of silently deleting the stored reference.
- Page saves still submit a full snapshot without revision-based conflict detection.
  A stale tab can overwrite newer changes, as before; preserve edits and refresh
  before saving after another tab or a chat command changes configuration.
- GIF capability and parameter statements stay within the documented sources in
  [the GIF research notes](gif-api-research.md). Preview entitlement, actual relay
  acceptance, model-specific pixel budgets and animation quality are not proved
  by mocked requests or successful plugin deployment.
- GIF validation checks signature and bounded size while preserving the original
  bytes; it does not validate every animation frame. An inline non-GIF response
  can continue the provider chain; a non-GIF remote URL result fails at download
  and does not restart that already-completed chain.
- File-delivery fallback requires a reported image-send exception. Silent platform
  flattening and actual playback remain adapter-specific. Existing partial-batch
  quota behavior is not redesigned.
- No paid Gemini/GIF generation or real chat-platform delivery is included in these
  tests. These remain integration checks for the intended account and adapter.
