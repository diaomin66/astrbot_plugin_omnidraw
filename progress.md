## 2026-07-13 - Task: Issue #35 人设图片查看与指令修改

### What was done

- 新增查看指定或当前人设详情及全部参考图的指令。
- 新增管理员修改现有人设名称或基础描述的指令，并沿用现有配置持久化与 AstrBot 配置同步流程。
- 补充指令帮助、用户文档和回归测试；参考图文件管理仍保留在配置页，避免聊天指令误删文件。

### Testing

- `python -m pytest -q tests/test_custom_endpoint.py -k "PersonaCommandTest"`
- `python -m compileall -q .`

### Notes

- `main.py`：增加人设查看、修改指令及配置更新逻辑。
- `tests/test_custom_endpoint.py`：覆盖人设详情图片输出与名称持久化。
- `docs/persona-commands.md`：记录人设查看与管理员修改用法。
- `progress.md`：追加本任务实施与验证记录。
- 回滚点：`origin/main`；可执行 `git restore --source=origin/main -- main.py tests/test_custom_endpoint.py`，并删除 `docs/persona-commands.md` 与本轮 `progress.md` 追加段落。

## 2026-07-13 - Task: Issue #42 副脑复用 AstrBot 文本模型

### What was done

- 新增“使用 AstrBot 当前文本模型”副脑开关；开启后通过 AstrBot SDK 调用当前 Chat Provider，不再从图像 endpoint 拼接 Chat Completions 路径。
- 保留原图像 Provider 副脑链路作为默认行为；AstrBot 文本模型不可用时继续按现有降级策略使用原始提示词。
- 同步原生配置、Pages 配置、使用文档和回归测试。

### Testing

- `python -m pytest -q tests/test_custom_endpoint.py -k "PromptOptimizerAstrBotProviderTest or astrbot_optimizer_toggle"`
- `python -m py_compile core/prompt_optimizer.py models.py main.py`
- `python -m json.tool _conf_schema.json`
- `node --check pages/插件配置/app.js`

### Notes

- `core/prompt_optimizer.py`：增加 AstrBot Chat Provider 调用分支。
- `models.py`：归一化并暴露副脑文本模型来源开关。
- `main.py`：向副脑传入 AstrBot Context。
- `_conf_schema.json`：增加原生配置开关。
- `pages/插件配置/index.html`、`pages/插件配置/app.js`：增加并持久化 Pages 开关。
- `tests/test_custom_endpoint.py`：覆盖 SDK 调用与配置入口一致性。
- `docs/optimizer.md`：说明两种副脑模型来源和降级行为。
- `progress.md`：追加本任务实施与验证记录。
- 回滚点：`origin/main`；可执行 `git restore --source=origin/main -- core/prompt_optimizer.py models.py main.py _conf_schema.json pages/插件配置/index.html pages/插件配置/app.js tests/test_custom_endpoint.py`，并删除 `docs/optimizer.md`。

## 2026-07-13 - Task: Issue #44 自定义接口请求参数类型

### What was done

- 自定义 JSON 接口会把合法 JSON 参数值恢复为布尔值、数字、数组、对象或 null，普通文本继续保持字符串。
- multipart 图片编辑接口保持表单文本语义，不改变已有协议行为。
- 补充类型矩阵回归测试和使用文档。

### Testing

- `python -m pytest -q tests/test_custom_endpoint.py -k "restores_non_string_parameter_types"`
- `python -m py_compile providers/custom_endpoint_impl.py`

### Notes

- `providers/custom_endpoint_impl.py`：在构建自定义 JSON 请求体前恢复参数类型。
- `tests/test_custom_endpoint.py`：覆盖布尔、整数、浮点、数组、对象和普通字符串。
- `docs/custom-endpoint-parameters.md`：记录参数类型转换规则与 multipart 边界。
- `progress.md`：追加本任务实施与验证记录。
- 回滚点：`origin/main`；可执行 `git restore --source=origin/main -- providers/custom_endpoint_impl.py tests/test_custom_endpoint.py`，并删除 `docs/custom-endpoint-parameters.md`。

## 2026-07-13 - Task: Issue #50 图片接口异步 task_id

### What was done

- 自定义图片接口检测到嵌套 `task_id` 后，自动轮询同域名 `/api/tasks/{task_id}`，直到取得图片、明确失败或达到节点超时。
- 同步直接返回图片的接口保持原行为；轮询继续复用节点认证与统一的响应解析、日志脱敏。
- 补充提交、处理中、完成三阶段回归测试和接口说明。

### Testing

- `python -m pytest -q tests/test_custom_endpoint.py -k "polls_submitted_task_id"`
- `python -m py_compile providers/custom_endpoint_impl.py`

### Notes

- `providers/custom_endpoint_impl.py`：增加异步任务识别、状态提取、轮询和超时处理。
- `tests/test_custom_endpoint.py`：覆盖嵌套列表 task_id 与最终图片 URL。
- `docs/async-image-tasks.md`：记录支持的提交结构、轮询路径和完成边界。
- `progress.md`：追加本任务实施与验证记录。
- 回滚点：`origin/main`；可执行 `git restore --source=origin/main -- providers/custom_endpoint_impl.py tests/test_custom_endpoint.py`，并删除 `docs/async-image-tasks.md`。

## 2026-07-13 - Task: Issue #51 AstrBot 4.26 ContextWrapper 工具事件

### What was done

- LLM 生图、自拍和视频工具在进入权限、图片读取和发送流程前，统一从 `ContextWrapper.context.event` 取得原始 `AstrMessageEvent`。
- 图片发送入口保留同样的解包兜底，普通指令和旧版直接事件调用行为不变。
- 回归测试使用 AstrBot 4.26 的实际包装结构验证自拍结果发送到原始事件。

### Testing

- `python -m pytest -q tests/test_custom_endpoint.py -k "existing_generate_selfie_tool_still_sends_images"`
- `python -m py_compile main.py`

### Notes

- `main.py`：增加 ContextWrapper 事件解包并接入三个 LLM 工具与图片发送。
- `tests/test_custom_endpoint.py`：覆盖包装事件下的自拍发送对象。
- `progress.md`：追加本任务实施与验证记录。
- 回滚点：`origin/main`；可执行 `git restore --source=origin/main -- main.py tests/test_custom_endpoint.py`。

## 2026-07-13 - Task: Issue #52 视频 async_task 误判与 task_id 轮询

### What was done

- 修复 `async_task` 因包含 `sync` 子串而被错误归一化为同步协议的根因。
- 异步视频提交支持从嵌套 `data` 列表提取 task_id，并按该中转结构轮询同域名 `/api/tasks/{task_id}`。
- 轮询状态支持顶层、对象和列表嵌套结构；原有顶层任务 ID 的轮询路径保持兼容。
- 补充协议归一化与完整提交/轮询回归测试和文档。

### Testing

- `python -m pytest -q tests/test_custom_endpoint.py -k "video_async_task_is_not_misclassified or VideoAsyncTaskTest"`
- `python -m py_compile models.py core/video_manager.py`

### Notes

- `models.py`：优先识别异步视频协议，避免 `async_task` 命中同步分支。
- `core/video_manager.py`：增加嵌套任务 ID/状态提取与轮询 URL 选择。
- `tests/test_custom_endpoint.py`：覆盖协议归一化和列表 task_id 的异步完成链路。
- `docs/async-video-tasks.md`：记录两类兼容轮询路径与响应结构。
- `progress.md`：追加本任务实施与验证记录。
- 回滚点：`origin/main`；可执行 `git restore --source=origin/main -- models.py core/video_manager.py tests/test_custom_endpoint.py`，并删除 `docs/async-video-tasks.md`。

## 2026-07-13 - Task: 汇总版本与更新日志

### What was done

- 将插件版本从 3.3.22 统一更新为 3.3.23。
- 更新 Changelog，逐项记录本轮 open Issue 的用户可见行为、兼容修复和测试覆盖。
- 同步 Pages 静态资源缓存版本，避免升级后继续命中旧版配置页资源。

### Testing

- `python -m pytest -q`
- `python -m compileall -q .`
- `python -m json.tool _conf_schema.json`
- `node --check pages/插件配置/app.js`
- 版本一致性检查：`metadata.yaml`、`models.py`、`CHANGELOG.md` 与 Pages 资源标签均为 `3.3.23`。

### Notes

- `metadata.yaml`、`models.py`：更新插件权威版本来源。
- `CHANGELOG.md`：新增 3.3.23 发布记录。
- `pages/插件配置/index.html`：更新 CSS/JS 缓存版本。
- `progress.md`：追加版本汇总与验证记录。
- 回滚点：`origin/main`；可执行 `git restore --source=origin/main -- metadata.yaml models.py CHANGELOG.md pages/插件配置/index.html`。

## 2026-07-13 - Task: 最终审查修复视频任务认证一致性

### What was done

- 最终审查发现异步视频提交与轮询会各自轮换一次 API Key，多 Key 节点可能用不同凭据查询刚提交的任务。
- 改为轮询复用本次提交请求的认证头，确保任务生命周期使用同一凭据。
- 扩展回归测试，在双 Key 节点下锁定提交与轮询 Authorization 一致。

### Testing

- `python -m pytest -q tests/test_custom_endpoint.py -k "VideoAsyncTaskTest"`
- `python -m py_compile core/video_manager.py`

### Notes

- `core/video_manager.py`：轮询复用提交阶段认证头。
- `tests/test_custom_endpoint.py`：覆盖多 Key 节点的任务认证一致性。
- `progress.md`：追加最终审查发现与修复记录。
- 回滚点：`origin/main`；可执行 `git restore --source=origin/main -- core/video_manager.py tests/test_custom_endpoint.py`。

## 2026-07-13 - Task: 全部 open Issue 最终双轴审查

### What was done

- 按规范轴复核最小改动、文件范围、配置/文档同步、版本一致性、行尾、敏感信息和大文件；未发现阻断性规范问题。
- 按 Issue 规格轴逐项复核 #35、#42、#44、#50、#51、#52，并确认 #53 是报告者明确声明的 #52 重复项；未发现遗漏的必需实现。
- 复查 GitHub open Issue，最终清单仍为 #35、#42、#44、#50、#51、#52、#53，没有执行期间新增条目。

### Testing

- `python -m pytest -q`：84 passed，14 subtests passed。
- `python -m compileall -q .`
- `python -m json.tool _conf_schema.json`
- `node --check pages/插件配置/app.js`
- `git diff --check`
- 版本陈旧引用扫描、生产文件敏感信息扫描和 5 MB 以上变更文件检查通过；测试中的 8 个 `sk-*` 命中均为既有或新增的脱敏断言哨兵值。

### Notes

- `progress.md`：追加最终规范轴、规格轴审查结论和完整验证证据。
- 集成边界：未使用真实第三方中转 API Key 执行在线生成；异步图片/视频、AstrBot ContextWrapper 与文本模型调用由离线回归测试和 AstrBot v4.26.0 公开源码接口交叉验证。
- 回滚点：本轮仅追加审查记录；可执行 `git restore --source=origin/main -- progress.md` 回滚全部进度日志，或在提交后执行 `git revert <本轮提交>` 回滚完整变更。
