# GPT Image 2.6 GIF API notes

Verified against the official OpenAI documentation on 2026-11-08. These are
documentation and mocked-request findings, not a claim that an account has GIF
preview access or that a paid generation request was executed.

## Sources

- [Image generation guide, including animated GIF output](https://developers.openai.com/api/docs/guides/image-generation)
- [Generate image API reference](https://developers.openai.com/api/reference/resources/images/methods/generate)
- [Edit image API reference](https://developers.openai.com/api/reference/resources/images/methods/edit)
- [GPT Image 2.6 Sunburst](https://developers.openai.com/api/docs/models/gpt-image-2.6-sunburst)
- [GPT Image 2.6 Flare](https://developers.openai.com/api/docs/models/gpt-image-2.6-flare)

## Confirmed request contract

Use `gpt-image-2.6-sunburst` or `gpt-image-2.6-flare`, through
`POST /v1/images/generations` for text-to-GIF or `POST /v1/images/edits` for
still-reference-to-GIF. The project/account must have access to the GIF preview
for the selected model. A correct request does not itself grant that access.

| Field | Verified behavior | Plugin behavior |
| --- | --- | --- |
| `output_format` | `gif` selects animation output | Explicit, per-request opt-in; normal images remain unchanged |
| `frame_count` | Integer 2 through 16, default 9 | Validates before requesting, including integer strings from commands |
| `frame_duration_ms` | Default 200; rounded to the nearest 10 ms | Accepts 20 through 2000, as published in the guide; passes the requested integer to the API |
| `size` | `auto`, or positive `WIDTHxHEIGHT` dimensions divisible by 16 | Defaults to `auto`; does not inherit a node's static-image default size |
| `complexity` | `low`, `medium`, `high`; default `high` | Optional; validates these values for GIF, otherwise lets the API use its default |
| `quality` | Rendering quality, independent from complexity | Preserves the existing parameter passthrough |
| `n` | Number of finished animations, not number of frames | One animation per underlying request; existing plugin batch/quota handling stays in control |

**Documentation discrepancy:** the guide's GIF table explicitly lists
`frame_duration_ms` as 20-2000 ms. The generate/edit reference instead specifies
only a minimum of 20 and describes the GIF encoding cap of 655,350 ms per frame.
The plugin deliberately uses the guide's narrower documented range. It does not
present the encoding cap as a promise that all larger input values are accepted.

The documentation says frame dimensions, frame count, and `n` must fit the
selected model's GIF size limits and total request pixel budget, but the pages
above do not publish a numeric GIF pixel budget. The static-image 4K limits are
not a verified GIF budget. This implementation therefore validates syntax and
16-pixel alignment, defaults to `auto`, and leaves model-specific pixel-budget
errors to the API. Reduce frame count or dimensions if the API rejects a size.

GIF does not support streaming, partial images, masks, or custom
`output_compression`. The plugin rejects enabled/incompatible values rather than
quietly dropping user intent. Disabled `stream`/`partial_images` are removed.
`frame_count` and `frame_duration_ms` must only be used with GIF at the API level;
legacy static parameter passthrough remains untouched for compatibility.

The guide recommends describing the subject, motion, and intended loop in the
prompt. A frame count is not a number of independent pictures. For example,
9 frames at 200 ms corresponds to approximately 1.8 seconds per animation loop.

## Wire format and response

Text-to-GIF uses the existing JSON Images request:

```json
{
  "model": "gpt-image-2.6-flare",
  "prompt": "A small paper crane gently flaps its wings and returns to its starting pose in a seamless loop.",
  "n": 1,
  "output_format": "gif",
  "frame_count": 9,
  "frame_duration_ms": 200,
  "size": "auto"
}
```

Reference-guided GIF uses multipart image edits, reusing the plugin's bounded,
validated reference loading. Multipart integer fields are decimal text, while
generation JSON uses real integers. The normal OpenAI image provider switches
an explicit `/images/generations` URL to `/images/edits` for GIF references while
preserving the query string. Its legacy static-image JSON relay behavior is
unchanged. A custom full-endpoint provider never rewrites the configured URL:
configure `/images/edits` explicitly for reference-guided GIF.

Official GIF results contain a finished animation in `data[].b64_json`. Decode
and retain those bytes as GIF; do not render a single frame or re-encode PNG.
The shared extractor identifies the binary signature rather than labeling all
base64 output `image/png`. GIF providers reject non-GIF inline results before
the fallback chain is considered successful. HTTP(S) results from compatible
relays are retained for the plugin's checked download/delivery path; a URL name
or MIME header alone does not prove the bytes are GIF.

## Compatibility and bounded resource use

- Existing configuration keys, chains, node types, API key rotation, endpoint
  construction for static images, and static node default sizes are preserved.
- GIF requests use the existing image chain but skip unsupported nodes. They
  never silently fall back to a static image or an unrelated video model.
- Supported nodes are OpenAI Images nodes or custom full endpoints ending in
  `/images/generations` or `/images/edits`, with a verified 2.6 model name.
  Date-suffixed names of those two models are recognized for compatibility;
  this is not a claim that a particular dated snapshot has been published.
- Bare `gpt-image-2.6`, arbitrary relay aliases, Chat Completions, Responses,
  Gemini, and older GPT Image models are not assumed to support GIF. Keep those
  existing nodes for ordinary images and add a confirmed GIF-capable node.
- The provider response reader retains its existing 64 MiB response-body cap.
  GIF binary output retains the existing 20 MiB image-file cap, checked before
  full inline decoding as well as after decoding. No new unbounded GIF buffer
  or image conversion library is introduced. Ordinary references retain their
  existing per-image/aggregate limits and remote-address checks.
- Generation may take substantially longer than a static preview. Set the
  existing node timeout appropriately; this update does not change saved
  timeout values or regenerate after delivery failure. If image delivery raises
  an error, it may retry delivery once as the original GIF file.

## Verification scope

`tests/test_gif_provider.py` uses fake HTTP sessions to cover JSON/multipart
types, GIF parameter boundaries, model/type gating, reference edit routing,
static request preservation, base64 MIME detection, byte limits, and fallback
after a static inline result. Real account permissions, provider-specific size
budgets, generated motion quality, and actual chat-platform animation playback
still require integration testing with the intended account and adapter.
