## 🚀 更新日志 (Changelog) 

### [2026/4/25]新增快速切换模型

### [2026/4/25]日志中增加调用用时返回  <img width="332" height="21" alt="PixPin_2026-04-25_21-22-24" src="https://github.com/user-attachments/assets/23d50606-e7bd-4f2b-90d1-5c6cead7ce07" />


### [2026/4/25]优化：兼容base64返回

### [2026/4/25] 新增功能 (New Features)
* **[权限] 增加 QQ 号白名单机制**：在 WebUI (或 `config.json`) 中新增 `allowed_users` 字段。支持配置允许生图的特定 QQ 号（多个以逗号分隔），留空则默认全员可用，有效防止 API 额度被滥用。
* **[交互] 拟真闲聊接力流 (LLM 接管)**：重构了大模型工具调用的响应逻辑。现在大模型接收到画图指令后，底层物理通道 (`await event.send`) 会率先把图片砸到聊天框，随后大模型会接管对话并结合当前语境进行自然闲聊收尾，彻底告别生硬的“机器发图感”。

### [2026/4/25] 核心优化 (Optimizations)
* **[网络] 满级防盗链拦截系统**：重构了 `openai_impl` 与 `openai_chat_impl` 两个底层通信节点的图像读取逻辑。现在遇到如 QQ/微信 等带防盗链机制的临时网络图片时，插件会利用 `aiohttp` 配合全局伪装请求头（User-Agent）先将图片拦截下载到本地内存并转化为 Base64，彻底解决第三方 API 报错 `Failed to load image` 的问题。
* **[调试] 完整提示词日志输出**：在发往第三方 API 网关的最后一毫米，增加了 `logger.info` 节点。可在终端实时打印出最终拼装完毕的纯净提示词，方便排查由于 LLM 乱发散导致的提示词权重污染问题。
* **[框架] 适配 WebUI 的参数解析**：去除了 `@llm_tool` 装饰器内部的 `description` 定义，全面拥抱纯正的函数注释 (Docstring) 解析。解决了 AstrBot 框架在 WebUI 中显示大模型工具为“无参数”的暗坑。

### [2026/4/25] 问题修复 (Bug Fixes)
* **[修复] 致命语法冲突 (`SyntaxError`)**：彻底移除了工具函数内 `yield` 与 `return` 混用引发的异步生成器语法崩溃问题，统一由 `return` 传递系统指令，并交由外部物理通道发图。
* **[修复] `ModuleNotFoundError` 幽灵报错**：清理了 `models.py` 中残留且不应该存在的底层接口依赖导入 (`from .base import BaseProvider`)，实现了数据模型与接口通信的彻底解耦，提升了框架启动稳定性。
* **[修复] 插件加载失败**：修正了 `metadata.yaml` 缺乏英文冒号与空格的格式问题，确保 AstrBot 启动器能顺利读取插件元数据。
