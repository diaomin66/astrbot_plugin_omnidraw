# Third-party notices

## GPT Image Playground

The configuration page directly uses React UI component source from
[CookSleep/gpt_image_playground](https://github.com/CookSleep/gpt_image_playground),
copyright (c) 2026 CookSleep, licensed under MIT.

Source revision: `6f8f44dadf77f7880f0db1eefb004fe0474b27d4`.

The vendored source is in `pages/插件配置/src/upstream/`. The components and
global stylesheet listed in `SOURCES.json` are byte-for-byte copies of the
pinned upstream files, with SHA-256 hashes for verification. The original
white/zinc/blue palette, border radii, control sizes, shadows and state styles
are used without a replacement theme. In particular, selects, checkboxes,
tooltips and confirmation dialogs run the original React component code.

| Upstream source | Local use |
| --- | --- |
| `src/index.css` | Entire original stylesheet, unmodified |
| `tailwind.config.js` | Original color tokens, zinc gray mapping and font theme; only local content paths differ |
| `src/components/Select.tsx`, `Checkbox.tsx` | Original React selection and checkbox components, unmodified |
| `src/components/ConfirmDialog.tsx` | Original React confirmation dialog, unmodified; a small host store adapter supplies its state |
| `src/components/TooltipButton.tsx`, `ViewportTooltip.tsx`, `Toast.tsx`, `icons.tsx` | Original React components and icons, unmodified |
| `src/hooks/useTooltip.ts`, `useCloseOnEscape.ts`, `usePreventBackgroundScroll.ts` | Original interaction hooks, unmodified |
| `src/lib/dropdown.ts`, `tooltipDismiss.ts` | Original dropdown/tooltip utilities, unmodified |
| `src/components/SettingsModal.tsx` and `ConfirmDialog.tsx` | Input, button, navigation, switch and modal JSX/classes extracted into `SettingsPrimitives.tsx`; application-specific bindings replaced with props |

Host-specific code connects these components to the existing plugin state and
configuration bridge without importing the unrelated upstream image-generation
application. `store.ts` only supplies confirmation and toast state; `lib/platform.ts`
sets the browser titlebar height to zero rather than loading Tauri. The settings
page layout remains the requested left navigation and right configuration area.

React, React DOM and Zustand are bundled into the checked-in `assets/ui.js`;
the Tailwind output is `assets/ui.css`. The plugin runs from these local static
assets without a CDN, npm installation or browser-side compilation. Development
builds use the committed `package-lock.json`. The original upstream license is
also preserved at `src/upstream/LICENSE`.

Bundled runtime dependencies retain their own MIT licenses:

- React, React DOM and Scheduler: Copyright (c) Meta Platforms, Inc. and affiliates.
  Full texts: `src/upstream/licenses/React-MIT.txt`, `React-DOM-MIT.txt` and
  `Scheduler-MIT.txt`.
- Zustand: Copyright (c) 2019 Paul Henschel.
  Full text: `src/upstream/licenses/Zustand-MIT.txt`.

These license paths are relative to `pages/插件配置/`. Exact dependency versions
and integrity hashes are recorded in its `package-lock.json`.

### MIT License

Copyright (c) 2026 CookSleep

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
