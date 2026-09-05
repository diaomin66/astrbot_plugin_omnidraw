# 自定义接口参数类型

`custom_endpoint` 使用 JSON 请求时，会把附加参数中的合法 JSON 标量或结构恢复为对应类型：

```text
--watermark false
--steps 20
--cfg_scale 7.5
--tags ["portrait","photo"]
```

发送到接口时分别为布尔值、整数、浮点数和数组，不再统一为字符串。不能解析为合法 JSON 的值（例如模型名、尺寸和普通文本）保持字符串。

`/images/edits` 使用 multipart 表单，表单字段按协议仍以文本形式传输。
