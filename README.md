# AstrBot 万象画卷 OmniDraw

当前版本：**3.4.1** · [更新日志](CHANGELOG.md#341)

`astrbot_plugin_omnidraw` 是一个面向 AstrBot 的生图、改图、人设自拍和视频生成插件。你可以把它理解成一个“画图工作台”：配置好模型接口后，在群聊或私聊里发送指令，就能让机器人帮你画图、参考图片改图、按固定人设自拍，或者提交视频生成任务。

3.4.1 整合原生 GIF、配置 Page 重写、页面加载与保存优化，以及 Gemini 代理地址修复；从 3.3.23 可直接升级，无需先安装 3.4.0。测试范围与实测数据见 [3.4.1 验证记录](docs/release-validation-3.4.1.md)。

交流与反馈：**点击链接加入群聊【雪碧的Astrbot插件交流群】：https://qm.qq.com/q/cmrmXaZaUg**

赞助商

**https://orbitix.site** 满血不降智GPT 0.2x GPT Image 2.5 1K 0.01/次

---

## 效果图

<img width="446" height="534" alt="PixPin_2026-04-25_20-45-31" src="https://github.com/user-attachments/assets/3799f40d-c3d5-41af-8c8d-79e5f59313ce" />

---

## 主要功能

- **文生图**：发送一句描述，让模型直接生成图片。
- **图生图 / 改图**：发送参考图和提示词，让模型按图修改或重绘。
- **原生 GIF 动图**：`/gif` 支持 GPT Image 2.6 Sunburst / Flare 文生动图与参考图动图；LLM 工具可自主选择 GIF。
- **人设自拍**：先在配置页上传人设参考图，再用 `/自拍` 生成固定角色的日常照片。
- **多个人设**：支持多组人设，每组人设都有自己的名称、基础描述和参考图组。
- **人设快速切换**：可以在 WebUI 切换，管理员也可以用 `/切换人设` 指令切换。
- **副脑优化**：自动把简单中文描述优化成更适合画图模型理解的英文提示词。
- **多模型热切换**：同一个画图、自拍或视频链路里可以放多个模型，由管理员随时切换。
- **预设指令管理**：可在聊天里查看预设名、查看单个预设详情，并由管理员添加或删除预设。
- **视频生成**：支持较慢的视频模型，提交后后台等待，完成后自动推送结果。
- **权限控制**：`可使用人员白名单` 用来直接限制谁能用；`用户白名单` 只负责不限次数，不负责限制权限。
- **指令回复自定义**：可以单独修改 `/画`、`/自拍` 的等待文案和报错文案，留空会自动恢复内置默认值。
- **成功结果信息**：可选择在 `/画`、宏指令、`/自拍` 和 `/视频` 成功后显示生成耗时、请求模型，两个开关可独立启用。
- **QQ 图片处理**：自动下载 QQ 图片到本地，减少图片链接失效、防盗链、400 报错等问题。
- **缓存清理**：可在 WebUI 一键清理临时图片缓存，支持定时清理、容量上限自动清理和管理员指令。

---

## 新手快速开始

### 1. 安装插件

在 AstrBot 插件目录中安装本插件，或通过 AstrBot 插件市场 / GitHub 仓库安装。

仓库地址：

```text
https://github.com/diaomin66/astrbot_plugin_omnidraw/
```

安装完成后，在 AstrBot 后台重载插件，看到“万象画卷”正常启用即可。

插件元数据声明支持 AstrBot `>=4.16,<5`；本轮部署验证使用 AstrBot `4.29.1` / Python `3.12.15`，不代表已经逐一验证所有旧版宿主。Python 版本请以所安装 AstrBot 的要求为准。运行依赖见 `requirements.txt`，配置页已附带构建资源，安装和升级均不需要 Node.js。

**从旧版升级：** 先备份宿主保存的原生插件配置，以及 `data/plugin_data/astrbot_plugin_omnidraw/` 整个插件数据目录（含持久化配置、使用统计、人设参考图和上传文件）。更新插件代码时不要用示例配置覆盖这些数据，也不要删除旧节点。重载后检查节点顺序、链路、人设参考图及额度设置，再刷新已打开的 Page。新版本不新增必填配置项，原有旧字段转换、归一化和安全过滤规则仍会执行；备份应取升级前的最新状态。

### 2. 打开插件配置页

进入 AstrBot WebUI：

1. 打开“插件管理”。
2. 找到“万象画卷”。
3. 进入插件的 `Pages / 插件配置` 页面。
4. 按页面分区填写配置。

如果刚打开页面没有数据，先刷新 AstrBot 后台或重载插件。

你也可以直接在 AstrBot 原生插件配置处编辑 `_conf_schema.json` 展示出来的配置项。原生配置页和 `Pages / 插件配置` 使用同一套配置结构：Pages 会先保存并热加载插件自己的配置，再尽力同步回 AstrBot 原生配置；如果原生同步失败，本地配置仍会生效并在日志中记录警告。在原生配置页保存后，重载插件或重新打开 Pages 会读取最新配置。

3.4.1 起，Page 首屏只读取轻量配置，各分区和统计按需加载。已有本地参考图通过受保护的临时引用保存，仅预览时读取图片，不再随每次配置读取和保存重复传输 Base64。引用在同一插件进程中保持稳定，重复读取不会使其他页面失效；插件重启或引用缓存淘汰后，旧页面保存会提示刷新，而不是静默清空原图。请先保留未保存的编辑再刷新。原 `get_config` API 的格式与兼容行为保持不变，新 Page 使用新增的 `get_page_config`。

Page 与聊天配置修改共用事务锁，避免读改写过程交错；Page 仍按原有方式提交完整配置，没有新增版本冲突检测。多个页面同时编辑，或页面打开后又在聊天侧修改设置时，旧页面稍后保存仍可能覆盖较新的值，请先保留编辑并刷新后再保存。

### 3. 配置画图模型

最少需要配置一个画图 Provider。常见字段含义如下：

| 字段 | 怎么填 |
| :--- | :--- |
| 节点 ID | 自己取一个好记的名字，比如 `image_node_1` |
| API 类型 | 按你的接口选择：`openai_image` 标准生图、`openai_chat` 对话透传中转站、`gemini_official` Gemini 原生协议、`custom_endpoint` 自定义完整路径 |
| Base URL | 标准/对话模式填中转站或官方接口地址，例如 `https://example.com/v1`；Gemini 可填原生协议代理地址，只有留空时使用 Google 默认地址；自定义模式必须填完整请求 URL |
| API Keys | 填你的 key，多个 key 可按页面提示添加 |
| 模型 | 填模型名，例如 `gpt-image-1.5`、`gemini-3.1-flash-image` 等 |
| Timeout | 建议画图 120-300，视频 300 或更高 |

`gemini_official` 使用 Google Gemini 原生 `generateContent` 接口，请求会发送到 `/models/{model}:generateContent`，认证使用 `x-goog-api-key`，返回图片会从 `candidates[].content.parts[].inlineData` 解析成 `data:image/...;base64,...`。

这个类型名沿用旧配置，仅表示协议，**不强制使用 Google 主机**。例如 `https://relay.example` 会请求 `https://relay.example/v1beta/models/{model}:generateContent`；显式填写的 `/v1`、`/v1beta`、代理前缀与查询参数会保留。已含完整 `:generateContent` 路径时直接使用；路径中固定的模型优先于节点模型。只有空地址使用 `https://generativelanguage.googleapis.com/v1beta`，非空非法地址会报错。若服务商提供的是 OpenAI 兼容或其他协议，请选择对应 API 类型，而不是只改 Gemini 节点的 URL。

`custom_endpoint` 只请求你填写的完整路径，不会自动追加 `/v1`、`/images/generations`、`/images/edits` 或 `/chat/completions`。例如要请求硅基流动、豆包或海外中转站的某个固定接口时，应直接填写 `https://api.example.com/v1/images/generations`、`https://api.example.com/v1/chat/completions` 或服务商文档给出的完整 endpoint。Chat Completions 仅适合会返回图片链接的中转站；官方 OpenAI 生图建议使用 Images 或 Responses 路径。

然后在“路由 / 链路”里把：

- 文生图链路指向你的画图节点。
- 自拍链路指向你的画图节点。
- 视频链路指向你的视频节点。

如需备用节点，可以在 Pages 的“生成调度”里打开对应任务的“备用节点”开关并按顺序点选；在 AstrBot 原生配置页中也可以把链路写成 `node_1,node_2,node_3`，第一个是主节点，后面的节点会在失败时按顺序尝试。

### 4. 保存并测试

保存配置后，在聊天里发送：

```text
/画 一只穿雨衣的猫走在东京夜晚的街道上，电影感
```

如果能出图，基础配置就成功了。

---

## 权限和回复文案

### 1. 可使用人员白名单

如果你只想让指定的人能用插件，就在配置里的 `permission_config.usable_users` 填入他们的用户 ID 或 QQ 号。

- 这个白名单一旦填写，就只允许名单内用户使用插件功能。
- 留空则默认不开启这层限制，所有未被黑名单拦截的用户都可以使用。
- 支持按行、英文逗号或空格分隔。
- 兼容旧字段名 `access_users` 和 `use_whitelist`，老配置可以直接沿用。

### 2. 白名单和黑名单优先级

当前权限优先级是：

1. `blocked_users`：黑名单，命中后直接禁止使用。
2. `usable_users`：可使用人员白名单，未命中就直接拒绝。
3. `allowed_users` / `unlimited_users`：用户白名单，只负责不限次数。
4. `unlimited_groups`：群组白名单，只负责群内不限次数。

如果你以前只填了“用户白名单”，那它现在仍然只是“不会扣每日次数”，不会再拿来限制谁能用。

### 3. 指令回复文案

在 `reply_config` 里可以分别改这 4 个文案：

- `draw_pending_message`：`/画` 和宏指令开始绘制前的等待文案
- `selfie_pending_message`：`/自拍` 开始前的等待文案
- `draw_error_message`：`/画` 和宏指令失败时的报错文案
- `selfie_error_message`：`/自拍` 失败时的报错文案

支持的常用占位符有：

`{command}` `{prompt}` `{ref_count}` `{param_count}` `{persona_name}` `{user_input}` `{error}` `{error_type}`

默认值分别是：

- `🎨 收到灵感，正在绘制...`
- `ℹ️ 正在为「{persona_name}」生成自拍，请稍候...`
- `💥 绘制失败: {error}`
- `💥 自拍生成失败: {error}`

留空后会自动恢复内置默认值。你可以在 Pages 的“插件配置”页里直接改，也可以在原生配置里改 `reply_config`。

### 成功结果信息

如果希望成功结果里带上本次生成耗时或实际请求模型，可以在 Pages 的“插件配置”页打开：

- `show_generation_time`：显示生成耗时。
- `show_request_model`：显示请求模型。

两个开关彼此独立，可以只显示耗时、只显示模型，或同时显示。它们只作用于 `/画`、宏指令、`/自拍` 和 `/视频` 这些指令触发的成功返回；LLM 工具自动下发图片或视频时不会显示这些信息。

---

## 人设自拍怎么配置

人设自拍适合固定角色、虚拟人物、OC、头像角色等场景。

### 第一步：创建人设

在插件配置页进入“人设”区域：

1. 点击新增人设。
2. 填写人设名称，例如“椰子”。
3. 填写基础人设描述，也就是这个角色长期不变的特征。
4. 上传该人设对应的参考图。
5. 保存配置。

每个人设都有独立参考图组。你给第二个人设上传的图，只会跟第二个人设绑定，不会混到第一个人设里。

### 第二步：切换当前人设

你可以在配置页点击人设卡片切换，也可以在聊天里发送：

```text
/人设
/切换人设 2
```

切换后，`/自拍` 会自动使用当前人设和它自己的参考图组。

### 第三步：生成自拍

```text
/自拍 在便利店门口拿着冰咖啡，手机随手拍，日常生活感
```

自拍模式建议写清楚场景、动作、镜头感和氛围。副脑会进一步整理成更适合画图模型的英文提示词。

---

## 常用指令

| 指令 | 用途 | 示例 |
| :--- | :--- | :--- |
| `/画 [提示词]` | 文生图，或带图时自动图生图 | `/画 赛博朋克猫咪，霓虹灯` |
| `/gif [动作描述]` | 生成原生 GIF，可附参考图 | `/gif 小猫挥手后回到原姿势，无缝循环 --frame_count 9` |
| `/自拍 [动作/场景]` | 使用当前人设生成自拍 | `/自拍 在海边散步，手机自拍` |
| `/视频 [提示词]` | 提交视频生成任务 | `/视频 两个人在森林里跳舞，镜头缓慢推进` |
| `/人设` | 查看所有人设和当前人设 | `/人设` |
| `/切换人设 [序号/ID/名称]` | 管理员切换当前人设 | `/切换人设 2` |
| `/切换链路 [目标] [节点ID]` | 管理员切换指定链路的首选节点 | `/切换链路 画图 node_2` |
| `/切换模型 [目标]` | 管理员查看某类链路的可用模型 | `/切换模型 画图` |
| `/切换模型 [目标] [序号/名称]` | 管理员切换指定模型 | `/切换模型 画图 2` |
| `/查看预设` | 查看所有预设名，不显示提示词 | `/查看预设` |
| `/查看预设 [预设名]` | 查看单个预设的名称和提示词 | `/查看预设 胶片少女` |
| `/添加预设 [预设名] [提示词]` | 管理员添加或更新预设 | `/添加预设 胶片少女 35mm film portrait` |
| `/删除预设 [预设名]` | 管理员删除预设 | `/删除预设 胶片少女` |
| `/清理缓存` | 管理员清理临时图片缓存 | `/清理缓存` |
| `/万象帮助` | 查看插件帮助 | `/万象帮助` |

查看单个预设也兼容紧凑写法，例如 `/查看预设胶片少女` 或 `/查看预设[胶片少女]`。
`/极速宏` 仍作为兼容别名保留，效果等同于 `/查看预设`，只列出预设名，不展示提示词。
如果你在 AstrBot 全局配置里改了指令前缀（例如把 `/` 改成 `#` 或 `，`），极速宏预设也会跟随该前缀触发，例如 `#胶片少女`、`，胶片少女`；旧版 `/胶片少女`、`!胶片少女`、`！胶片少女`、`.胶片少女` 仍保持兼容。预设后可以追加规则，例如 `，胶片少女 皮肤白一点`，插件会把追加规则合并到底层提示词；预设提示词和追加规则里的 `--参数 值` 会像 `/画` 一样解析。添加预设时也支持 `预设名:提示词` 和 `预设名：提示词` 这两种分隔格式。

目标一般可以写：

```text
画图
自拍
视频
```

---

## GIF 动图（3.4.1 已包含）

### 配置与使用

新增或使用一个 `openai_image` 节点，模型填 **`gpt-image-2.6-sunburst`** 或 **`gpt-image-2.6-flare`**，加入文生图链路；动态自拍则加入自拍链路。不需要额外的 GIF 配置区，也不会自动改写现有模型或路由。GIF 按请求显式开启，未开启时沿用静态生成逻辑。

**账号或中转服务必须已开放该模型的 GIF 预览权限。** 仅填写模型名不代表已经获得权限。Chat Completions、Responses、Gemini、旧 GPT Image 模型和未经确认的模型别名不会被当作 GIF 节点；GIF 请求跳过这些节点，不会悄悄降级成静态图。没有合适节点时会明确报错。此处支持范围来自已核对的文档与模拟请求测试，并非付费生图或平台播放实测结论。

```text
/gif 纸鹤轻轻扇动翅膀，再回到初始姿势，无缝循环
/gif 小猫眨眼后挥手 --frame_count 8 --frame_duration_ms 150 --complexity medium
/画 海浪反复拍打沙滩 --output_format gif
/自拍 对着镜头眨眼然后微笑 --output_format gif
```

附图、引用图片和 `/gif` 后 @ 用户头像沿用 `/画` 的参考图规则。标准 Images 节点会切换到 multipart `/images/edits`；`custom_endpoint` 坚持完整 URL 不改写，参考图动图请明确配置 `/images/edits`，纯文字动图可配置 `/images/generations`。

| 参数 | 范围与默认值 |
| :--- | :--- |
| `output_format` | `/gif` 自动固定为 `gif`；其他入口需显式开启 |
| `frame_count` | 整数 2–16，默认 9；这是帧数，不是图片张数 |
| `frame_duration_ms` | 整数 20–2000，默认 200ms；API 按 10ms 取整 |
| `size` | 默认 `auto`；也可用宽高均为 16 倍数的 `宽x高`，如 `512x512` |
| `complexity` | 可选 `low`、`medium`、`high`；省略使用模型默认值 |

GIF 有独立的帧尺寸与总像素预算，不能套用静态 4K 尺寸表。本版本默认 `auto`，不继承节点已有静态默认尺寸；最终尺寸预算由模型决定。GIF 不支持 `aspect_ratio`、流式输出、局部帧、mask 或 `output_compression`。详细参数研究、官方来源及帧间隔文档差异见 [GIF API 研究记录](docs/gif-api-research.md)。

### LLM 自主调用与插件 API

现有 `generate_image`、`generate_selfie` 工具均新增以下可选参数，原有参数顺序和默认静态行为保留：

```json
{
  "prompt": "一只小猫眨眼、挥手，然后回到初始姿势，无缝循环",
  "use_gif": true,
  "frame_count": 9,
  "frame_duration_ms": 200,
  "count": 1
}
```

自拍工具用 `action` 替代 `prompt`。工具说明已告诉 LLM：用户要 GIF、动态表情或动态自拍时自主设置 `use_gif=true`，不要误用视频工具；普通图片保持 `false`。GIF 绕过会强制“单一静止瞬间”的静态副脑，保留原始连续动作和人设提示词。

`count` 是成品 GIF 文件数，沿用原批量上限与额度；帧数不单独计次。`use_gif=true` 时专用 `frame_count` / `frame_duration_ms` 参数优先于 `extra_params` 中的同名项。如果只想使用附加参数，可以不设 `use_gif`，改传 `extra_params="--output_format gif --frame_count 8"`。

`generate_images_for_plugin(...)` 和 `POST /astrbot_plugin_omnidraw/generate_image_for_plugin` 同样接受 `use_gif`、`frame_count`、`frame_duration_ms`。`return_result=true` 是 LLM 工具的参数；Python 方法和 HTTP 接口本身就只返回结果，无需传入该开关。GIF 结果包含 `content_type="image/gif"`、`output_format="gif"`、原始 `.gif` 的 `file_path` 及可供跨进程读取的 `data_url`，旧结果字段继续保留。

### 发送、缓存与旧配置兼容

- GIF 按文件签名识别类型并保留原始字节，不转 PNG，也不提取首帧；无扩展名或带签名参数的 URL 会先经过下载安全检查和 20 MiB 大小限制。签名校验不代表验证了多帧结构、循环效果或动画质量。
- 优先使用 AstrBot 图片组件；适配器抛出发送异常时，尝试发送原始 GIF 文件，不重新请求模型。平台静默压缩、播放或文件支持仍取决于实际适配器，不能保证每个平台都内联播放。
- 返回内联静态图时可继续尝试下一个 GIF 节点；远程 URL 在后续下载时才校验，若下载结果不是 GIF，会明确失败，但不会重新启动已结束的 Provider 链路。
- GIF 纳入原图片缓存统计和清理；批量任务发送或序列化期间保留缓存租约，避免后一张图把前一张提前清理。
- 如果旧配置已有名为 `gif` 的宏，保留旧宏优先级且不会重复执行新命令；可用 `/画 ... --output_format gif`，或自行重命名旧宏。
- 原配置 schema 不变，不要求额外迁移步骤、重置或新增必填项。新版 Page 继续提供原有节点、人设、预设、权限、额度和缓存操作；前端尽量保留未编辑的扩展字段，但后端仍按原有规则处理旧字段、无效节点、保留指令名及不安全引用。未知顶层字段或未受支持的扩展字段不保证持久保留。

### Page 组件与开发构建

页面直接复用 GPT Image Playground 的原始 React 选择器、复选框、确认弹窗、提示组件、交互 hooks 和完整配色样式。输入框、按钮、开关、导航及抽屉容器从其 `SettingsModal` / `ConfirmDialog` 原 JSX 提取，只连接本插件的数据，不另行替换主题或重新设计控件。

插件随仓库提供预构建 `assets/ui.js` / `assets/ui.css`，使用者无需安装 Node.js。只有修改前端源码时，才需要在 `pages/插件配置` 目录运行 `npm ci`、`npm run build`；请一起提交生成的静态资源。源码来源和逐文件校验值见 `pages/插件配置/src/upstream/SOURCES.json`，不会在浏览器动态下载第三方脚本。开发与回归命令见文末“开发验证”。

---

## 给其他插件调用并获取图片

默认的 LLM 工具 `generate_image` 行为保持不变：生成后会直接把图片下发到当前聊天，并返回“已成功下发 N 张图”的文本。

如果其他插件需要“调用万象画卷生图，然后自己拿到图片继续处理”，请显式传入 `return_result=true`。此时不会自动下发图片，而是返回 JSON 字符串：

```json
{
  "success": true,
  "message": "已成功生成 1 张图片。",
  "images": [
    {
      "index": 1,
      "image_url": "https://example.com/out.png",
      "source_type": "url",
      "url": "https://example.com/out.png",
      "file_path": "",
      "data_url": "",
      "content_type": "image/png",
      "output_format": "",
      "provider_id": "image_node_1",
      "model": "gpt-image-1.5",
      "elapsed_seconds": 12.3,
      "prompt": "实际用于请求的提示词"
    }
  ],
  "count": 1,
  "requested_count": 1,
  "ref_count": 0,
  "processed_ref_count": 0,
  "mode": "text2img",
  "chain": "text2img"
}
```

可选参数：

- `return_result=true`：启用返回式生图；不传或为 `false` 时保持原自动下发行为。
- `refs`：参考图 URL、data URL，或插件数据目录内的本地路径；多个参考图可用换行分隔，也可传 JSON 数组字符串。显式传入的其他本地路径会被拒绝。
- `aspect_ratio`、`size`、`extra_params`：与普通 `generate_image` 一致。
- `use_gif=false`、`frame_count=9`、`frame_duration_ms=200`：原生 GIF 的开关和帧设置，完整约束见前文；普通图片无需填写。
- 自拍模式请调用现有 `generate_selfie(return_result=true)` 工具，不需要新增 `generate_selfie_image`。返回结构相同，`mode` 为 `selfie`，会按 `/自拍` 的逻辑构建人设提示词并优先走自拍链路；未传 `refs` 时使用当前激活人设参考图。

`refs` 在这两个 LLM 工具中仅用于 `return_result=true` 分支；普通自动下发分支仍从当前聊天事件获取参考图，自拍同时使用当前人设。拿到插件实例后，受信任的 Python 插件也可直接获取字典结果：

```python
result = await omnidraw.generate_images_for_plugin(
    prompt="纸鹤扇动翅膀后回到原姿势，无缝循环",
    count=1,
    mode="text2img",
    use_gif=True,
    frame_count=9,
    frame_duration_ms=200,
)
```

这里的 `omnidraw` 是已由宿主取得的插件实例，不是新的模块级函数。该方法不自动发送消息；默认 `event=None`、`record_usage=False`。需要按聊天用户检查权限和计次时，由受信任调用方传入真实 `event` 并显式设置 `record_usage=True`。不要对不可信输入开启 `allow_local_refs`。

也可以调用 Web API：

```http
POST /astrbot_plugin_omnidraw/generate_image_for_plugin
Content-Type: application/json

{
  "prompt": "一只橘猫坐在霓虹灯下",
  "count": 1,
  "refs": ["https://example.com/ref.png"],
  "size": "1024x1024"
}
```

示例使用插件注册路径；通过 AstrBot 扩展 API 代理访问时，宿主可能使用 `/api/v1/plugins/extensions/astrbot_plugin_omnidraw/generate_image_for_plugin`，请按宿主实际路由和鉴权方式调用，不要直接公开为匿名接口。

Web API 返回同样的 JSON 结构。自拍模式可传 `{"mode": "selfie", "action": "看着镜头微笑"}`，也兼容 `{"selfie": true}`；GIF 可再添加 `"use_gif": true` 及帧参数。该接口供受信任的插件桥接使用，宿主必须为 Web API 提供鉴权及相应的 CSRF 防护；它不携带聊天事件，因此不会自动扣用户额度。通过 `generate_image(return_result=true)` 或 `generate_selfie(return_result=true)` 且传入事件上下文时，会沿用原权限和额度逻辑。

配置页不会回显 API Key 原文，只显示掩码；保存时保留未修改的掩码项。单张参考图上限 20 MiB、单次最多 14 张且总计最多 64 MiB，具体 Provider 或端点可能有更低上限；副脑批量和后台任务也有硬上限。`file_path` 属于可清理缓存，并非永久下载地址；需要长期保留的调用方应及时保存返回数据。

失败时同样返回 JSON（`success=false`、`images=[]`），便于调用方稳定解析；错误文本会自动脱敏 API Key、Bearer Token 和图片 Base64，避免把敏感信息透传给其他插件或聊天上下文。

---

## 图片参考怎么用

### 图生图 / 改图

在聊天里发送图片时，带上 `/画` 和你的要求即可：

```text
/画 保留人物姿势，把背景改成雨后的城市街头
```

插件会自动识别你发的图片，把它作为参考图传给画图模型。

### 视频多图参考

视频模型如果支持多图参考，你可以一次发送 2-3 张图，再发送：

```text
/视频 让画面中的人物转身看向镜头，真实电影感
```

视频任务通常比图片慢很多，请把视频 Provider 的 `timeout` 设置高一些。

---

## 副脑是什么

副脑是提示词优化器。它会把用户随手写的一句话，整理成画图模型更容易理解的英文提示词。

推荐开启副脑的情况：

- 你希望简单一句话也能出高质量图片。
- 你经常使用自拍、人设、真实日常照片风格。
- 你使用的模型更擅长理解英文提示词。

不推荐开启副脑的情况：

- 你想让模型严格照着原文，不做任何扩写。
- 你的接口很慢，想减少一次额外的模型调用。

---

## 常见配置建议

- **画图超时**：建议 `120` 到 `300`。
- **视频超时**：建议 `300` 或更高。
- **模型名分隔**：如果手动填写多个模型，请使用英文逗号 `,`，不要用中文逗号。
- **人设参考图**：建议上传清晰、无遮挡、人物比例正常的图片。
- **缓存清理**：缓存清理只处理 `temp_images` 与 `user_refs` 里的图片文件，不会删除人设参考图。
- **自拍提示词**：多写日常场景、动作、光线和拍摄设备感，少写夸张身体描述。
- **权限控制**：如果只想自己用，就在“可使用人员白名单”里填写自己的 QQ 号；留空则默认所有未被黑名单拦截的用户都能用。`用户白名单` 只负责不限次数。
- **指令回复**：想改 `/画`、`/自拍` 的等待或报错提示，就去 `reply_config`；留空会回到默认文案。

---

## 常见问题

### 1. 保存配置后不生效怎么办？

先在 AstrBot 后台重载插件，再刷新配置页。如果仍然不生效，检查必填项是否为空，尤其是 Base URL、API Key、模型名和链路节点。

### 2. 为什么第二个人设刷新后看不到参考图？

新版已经修复临时预览链接被保存的问题。每个人设参考图会保存为真实本地路径，刷新后仍然能显示。如果你升级前已经保存过异常配置，重新上传一次对应人设的参考图并保存即可恢复。

### 3. 画图报 400 怎么办？

常见原因是模型名不对、接口类型选错、图片太大、接口不支持当前参数。先用最简单的 `/画 一只猫` 测试，再逐步增加参考图和复杂提示词。

### 4. 视频一直没返回怎么办？

视频模型通常很慢。请检查视频 Provider 的 `timeout`，并确认你的中转站是否真的支持视频端点。

### 5. API Key 可以填多个吗？

可以。多个 key 会按插件逻辑轮换使用，适合有多个额度来源的情况。

---

## 文件结构

```text
astrbot_plugin_omnidraw/
├── main.py              # 插件入口、指令、Web API、图片缓存
├── models.py            # 配置解析、Provider、人设数据结构
├── constants.py         # 默认值和常量
├── core/
│   ├── chain_manager.py     # 模型链路管理
│   ├── image_options.py     # GIF 参数校验与节点能力判断
│   ├── parser.py            # 指令解析
│   ├── persona_manager.py   # 人设切换与自拍提示词
│   ├── prompt_optimizer.py  # 副脑提示词优化
│   └── video_manager.py     # 视频任务后台等待
├── providers/           # 不同 API 类型的请求实现
├── pages/插件配置/      # 插件 WebUI 配置页
├── metadata.yaml        # 插件元信息
└── requirements.txt     # Python 依赖
```

---

## 开发验证

以下命令在仓库根目录执行；测试使用模拟接口与临时数据，不需要 API Key，也不发起付费生成请求。开发环境需先具备与宿主兼容的 Python；浏览器测试另需 Playwright 和浏览器。

```sh
python -m pip install -r requirements.txt
python -m pip install pytest ruff playwright
python -B -m pytest -q
python -m ruff check .
node --check "pages/插件配置/app.js"
git diff --check
```

修改前端后重新检查类型并构建：

```sh
cd "pages/插件配置"
npm ci
npm run build
cd ../..
```

安装 Playwright 自带 Chromium 后，可运行独立浏览器回归与五轮性能基准；已有 Chrome 时可省略浏览器安装并为两条测试命令加 `--channel chrome`：

```sh
python -m playwright install chromium
python -B tests/page_ui_smoke.py
python -B tests/page_ui_performance.py --runs 5 --assert-performance
```

页面回归覆盖 7 个分区、4 种宽度。浏览器模拟负载、真实宿主只读 GET 与隔离数据的保存测试是不同场景，不能把其耗时当作模型生成速度或生产保存 SLA。最终回归结果、环境、方法、实测值与未验证项见 [3.4.1 验证记录](docs/release-validation-3.4.1.md)。

---

## 鸣谢

- [CookSleep/gpt_image_playground](https://github.com/CookSleep/gpt_image_playground)：新版 Page 直接复用该项目的配色、组件源码与样式，包括按钮、输入框、选择器、复选框、开关、导航、抽屉容器和确认弹窗。保留原组件视觉与交互，不再另做近似主题；本地预构建资源随插件提供。固定来源版本、接入说明和完整 MIT 许可见 [第三方声明](THIRD_PARTY_NOTICES.md)。
- [AstrBot](https://github.com/Soulter/AstrBot)：感谢提供强大、可扩展的机器人插件框架。
- [astrbot_plugin_shoubanhua](https://github.com/shskjw/astrbot_plugin_shoubanhua)：感谢动态模型热切换思路。
- [astrbot_plugin_gitee_aiimg](https://github.com/muyouzhi6/astrbot_plugin_gitee_aiimg)：感谢视频接入与异步渲染思路。

也感谢所有测试、反馈和贡献建议的用户。
