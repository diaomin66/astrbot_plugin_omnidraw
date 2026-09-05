# 副脑文本模型

副脑默认复用 `optimizer_config.chain_optimizer` 指向的图像 Provider，并按 OpenAI Chat Completions 方式请求。

如果图像节点填写的是完整生图 endpoint，不能再拼接 `/v1/chat/completions`。此时可开启：

```text
optimizer_config.use_astrbot_provider = true
```

开启后，副脑通过 AstrBot SDK 调用当前启用的 Chat Provider；图像节点只负责生图。Pages 中对应开关为“使用 AstrBot 当前文本模型”。

如果 AstrBot 没有可用的当前文本模型，副脑会记录降级原因并保留用户原始提示词，不中断生图。
