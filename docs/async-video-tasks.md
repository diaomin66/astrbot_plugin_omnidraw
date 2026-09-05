# 异步视频任务

视频节点的 `async_task` 模式会先提交任务，再轮询任务结果。

- 顶层 `id` / `task_id` 和 `data` 对象中的任务 ID 继续使用原兼容路径：`{videos/generations endpoint}/{task_id}`。
- 对 `data: [{"status": "submitted", "task_id": "..."}]` 结构，插件使用同域名 `/api/tasks/{task_id}` 轮询。
- 轮询状态支持顶层、`data` 对象或 `data` 列表中的 `status` / `task_status` / `state`。

`async_task` 会被明确识别为异步协议，不再因名称中包含 `sync` 而错误归一化成 `openai_sync`。
