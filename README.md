# AstrBot 万象画卷 OmniDraw

`astrbot_plugin_omnidraw` 是一个面向 AstrBot 的生图、改图、人设自拍和视频生成插件。你可以把它理解成一个“画图工作台”：配置好模型接口后，在群聊或私聊里发送指令，就能让机器人帮你画图、参考图片改图、按固定人设自拍，或者提交视频生成任务。

交流与反馈：**[点击加入 QQ 群 1081773675](https://qm.qq.com/q/Qr45Vz0a8o)**

推荐香蕉（nano-banana谷歌最强生图模型系列）以及gpt-image-2（支持4K）中转站：**[Meinianda AI](https://meinianda.top)**

---

## 效果图

<img width="446" height="534" alt="PixPin_2026-04-25_20-45-31" src="https://github.com/user-attachments/assets/3799f40d-c3d5-41af-8c8d-79e5f59313ce" />

---

## 主要功能

- **文生图**：发送一句描述，让模型直接生成图片。
- **图生图 / 改图**：发送参考图和提示词，让模型按图修改或重绘。
- **人设自拍**：先在配置页上传人设参考图，再用 `/自拍` 生成固定角色的日常照片。
- **多个人设**：支持多组人设，每组人设都有自己的名称、基础描述和参考图组。
- **人设快速切换**：可以在 WebUI 切换，也可以用 `/切换人设` 指令切换。
- **副脑优化**：自动把简单中文描述优化成更适合画图模型理解的英文提示词。
- **多模型热切换**：同一个画图、自拍或视频链路里可以放多个模型，随时切换。
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

### 2. 打开插件配置页

进入 AstrBot WebUI：

1. 打开“插件管理”。
2. 找到“万象画卷”。
3. 进入插件的 `Pages / 插件配置` 页面。
4. 按页面分区填写配置。

如果刚打开页面没有数据，先刷新 AstrBot 后台或重载插件。

你也可以直接在 AstrBot 原生插件配置处编辑 `_conf_schema.json` 展示出来的配置项。原生配置页和 `Pages / 插件配置` 使用同一套配置结构：在 Pages 保存会同步回原生配置；在原生配置页保存后，重载插件或重新打开 Pages 会读取最新配置。

### 3. 配置画图模型

最少需要配置一个画图 Provider。常见字段含义如下：

| 字段 | 怎么填 |
| :--- | :--- |
| 节点 ID | 自己取一个好记的名字，比如 `image_node_1` |
| API 类型 | 按你的接口选择：`openai_image` 标准生图、`openai_chat` 对话透传中转站、`gemini_official` Gemini 官方、`custom_endpoint` 自定义完整路径、`stable_diffusion_webui` Stable Diffusion WebUI |
| Base URL | 标准/对话模式填中转站或官方接口地址，例如 `https://example.com/v1`；Gemini 官方可留空或填 `https://generativelanguage.googleapis.com/v1beta`；自定义模式必须填完整请求 URL；Stable Diffusion WebUI 填 WebUI 根地址，例如 `http://127.0.0.1:7860` |
| API Keys | 填你的 key，多个 key 可按页面提示添加 |
| 模型 | 填模型名，例如 `gpt-image-1`、`gemini-3.1-flash-image-preview` 等 |
| Timeout | 建议画图 120-300，视频 300 或更高 |

`gemini_official` 使用 Google Gemini 原生 `generateContent` 接口，请求会发送到 `/models/{model}:generateContent`，认证使用 `x-goog-api-key`，返回图片会从 `candidates[].content.parts[].inlineData` 解析成 `data:image/...;base64,...`。

`custom_endpoint` 只请求你填写的完整路径，不会自动追加 `/v1`、`/images/generations`、`/images/edits` 或 `/chat/completions`。例如要请求硅基流动、豆包或海外中转站的某个固定接口时，应直接填写 `https://api.example.com/v1/images/generations`、`https://api.example.com/v1/chat/completions` 或服务商文档给出的完整 endpoint。Chat Completions 仅适合会返回图片链接的中转站；官方 OpenAI 生图建议使用 Images 或 Responses 路径。

`stable_diffusion_webui` 使用 Stable Diffusion WebUI 的 `/sdapi/v1/txt2img` 和 `/sdapi/v1/img2img` 接口。无参考图时调用 `txt2img`，带参考图时调用 `img2img`；WebUI 返回的 Base64 图片会自动转换为插件内部的图片结果。API Key 可以留空；如果 WebUI 启用了 `--api-auth`，可将 `用户名:密码` 填入 API Keys。

Stable Diffusion WebUI 节点还可以配置 `SD 采样步数`、`SD CFG Scale` 和 `SD 采样器自定义` 三个默认参数，分别对应 WebUI API 的 `steps`、`cfg_scale` 和 `sampler_name`。单次指令或工具调用通过 `--steps`、`--cfg_scale`、`--sampler_name` 传入的值会覆盖节点默认值。

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
| `/自拍 [动作/场景]` | 使用当前人设生成自拍 | `/自拍 在海边散步，手机自拍` |
| `/视频 [提示词]` | 提交视频生成任务 | `/视频 两个人在森林里跳舞，镜头缓慢推进` |
| `/人设` | 查看所有人设和当前人设 | `/人设` |
| `/切换人设 [序号/ID/名称]` | 切换当前人设 | `/切换人设 2` |
| `/切换模型 [目标]` | 查看某类链路的可用模型 | `/切换模型 画图` |
| `/切换模型 [目标] [序号/名称]` | 切换指定模型 | `/切换模型 画图 2` |
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

## 给其他插件调用并获取图片

默认的 LLM 工具 `generate_image` 行为保持不变：生成后会直接把图片下发到当前聊天，并返回“已成功下发 N 张图”的文本。

如果其他插件需要“调用万象画卷生图，然后自己拿到图片继续处理”，请显式传入 `return_result=true`。此时不会自动下发图片，而是返回 JSON 字符串：

```json
{
  "success": true,
  "message": "已成功生成 1 张图片。",
  "images": [
    {
      "image_url": "https://example.com/out.png",
      "source_type": "url",
      "url": "https://example.com/out.png",
      "file_path": "",
      "data_url": "",
      "content_type": "image/png",
      "provider_id": "image_node_1",
      "model": "gpt-image-1",
      "elapsed_seconds": 12.3,
      "prompt": "实际用于请求的提示词"
    }
  ],
  "count": 1,
  "requested_count": 1,
  "mode": "text2img",
  "chain": "text2img"
}
```

可选参数：

- `return_result=true`：启用返回式生图；不传或为 `false` 时保持原自动下发行为。
- `refs`：参考图 URL、本地路径或 data URL；多个参考图可用换行分隔，也可传 JSON 数组字符串。
- `aspect_ratio`、`size`、`extra_params`：与普通 `generate_image` 一致。
- 自拍模式请调用现有 `generate_selfie(return_result=true)` 工具，不需要新增 `generate_selfie_image`。返回结构相同，`mode` 为 `selfie`，会按 `/自拍` 的逻辑构建人设提示词并优先走自拍链路；未传 `refs` 时使用当前激活人设参考图。

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

Web API 返回同样的 JSON 结构。自拍模式可传 `{"mode": "selfie", "action": "看着镜头微笑"}`，也兼容 `{"selfie": true}`。为了避免绕过具体用户上下文，Web API 不会自动扣用户额度；通过 `generate_image(return_result=true)` 或 `generate_selfie(return_result=true)` 且传入事件上下文时，会沿用原权限和额度逻辑。

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

## 鸣谢

- [AstrBot](https://github.com/Soulter/AstrBot)：感谢提供强大、可扩展的机器人插件框架。
- [astrbot_plugin_shoubanhua](https://github.com/shskjw/astrbot_plugin_shoubanhua)：感谢动态模型热切换思路。
- [astrbot_plugin_gitee_aiimg](https://github.com/muyouzhi6/astrbot_plugin_gitee_aiimg)：感谢视频接入与异步渲染思路。

也感谢所有测试、反馈和贡献建议的用户。
