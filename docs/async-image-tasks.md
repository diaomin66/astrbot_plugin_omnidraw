# 异步图片任务

`custom_endpoint` 兼容先返回 `task_id`、稍后再返回图片的中转接口。

提交响应示例：

```json
{"code": 200, "data": [{"status": "submitted", "task_id": "task_123"}]}
```

插件检测到 `task_id` 后，会按节点 `timeout` 在同一服务域名的 `/api/tasks/{task_id}` 轮询。任务响应出现可识别的图片 URL/Base64 时返回图片；明确失败状态会立即报错；超时则按节点失败处理。

直接返回图片的同步自定义接口不受影响。
