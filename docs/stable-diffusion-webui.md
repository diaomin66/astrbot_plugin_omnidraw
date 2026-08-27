# Stable Diffusion WebUI 节点

图像 Provider 的 `api_type` 设置为 `stable_diffusion_webui` 后，`base_url` 填 Stable Diffusion WebUI 根地址，例如：

```text
http://127.0.0.1:7860
```

插件使用以下接口：

- 无参考图：`POST /sdapi/v1/txt2img`
- 有参考图：`POST /sdapi/v1/img2img`

请求体是 Stable Diffusion WebUI API 的 JSON 格式。`size` 或 `resolution` 会转换为 `width` 和 `height`；`model` 会作为 `override_settings.sd_model_checkpoint` 传入；其他 `--key value` 参数会透传到请求体。

WebUI 返回的 `images` 数组中的第一张 Base64 图片会作为生成结果。API Key 可以留空；启用 `--api-auth` 时，将 `用户名:密码` 填入节点的 API Keys 字段即可。
