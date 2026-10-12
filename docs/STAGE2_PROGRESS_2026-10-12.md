# 阶段二交付记录 — 2026-10-12

状态：**已实现并完成真实长对话联调**。阶段二只处理上下文连续性；地图、网页搜索、活动方案和确认行动仍属后续阶段。

## 实现

- `prepare_context → compact_history → understand_context`：LangGraph 在理解节点前调用 `ContextBuilder`。当前用户输入、结构化快照和最近四个完整交互回合保持原文。短对话不调用摘要模型。
- DeepSeek `/models` 返回的 `context_window` 用于计算 `min(节点上限, 模型窗口 − 输出预留 − 安全余量)`；理解节点上限默认 8,000 估算 token。完整输入达到该预算约 80% 且存在已完成旧回合时触发摘要，尽量回落到约 60%。这些比例是应用配置初值，非模型标准。估算按 UTF-8 字节保守计算，实际用量另记供应商 `usage`，不能把估算当精确 tokenizer 结果。
- 摘要只保存历史主题、偏好理由、被否决想法和未决问题，作为**有损历史数据**传给模型。预算、时间、位置等当前条件只由带版本和原文依据的 `ContextSnapshot` 决定；摘要不能更新权限或执行状态。结构化提取和摘要均显式使用 DeepSeek 非思考 JSON 模式，以免默认推理耗尽小型 JSON 输出配额。
- 新增 `solovibe_v1.rolling_summaries`：记录摘要 ID/版本、覆盖游标、原文范围及 SHA-256、生成时的状态版本、内容、估算大小和时间。原始消息及 LangGraph checkpoint 分开保留。增量迁移不删除旧表。
- 摘要提交在数据库事务内检查当前活动运行、结构化状态版本、旧摘要版本/游标及已完成原文范围。超时、无效输出或游标冲突时不会推进覆盖范围；若原文安全子集仍能满足硬预算，可以继续，否则明确返回 `CONTEXT_OVERFLOW`，不截断当前消息。
- `GET /api/conversations/{thread_id}` 只暴露摘要版本和覆盖游标，不暴露有损摘要正文。前端在摘要存在时提示“较早对话已整理 · 原文仍保留”。

## 验证

| 检查 | 结果 |
| --- | --- |
| Python 契约/边界测试 | 33 passed：短对话、旧回合选择、摘要失败回退、checkpoint 后重读游标、当前输入超限、模型 JSON/截断/输入预算等 |
| 前端类型检查及生产构建 | 通过 |
| 常规浏览器测试 | 2 passed，1 个真实模型测试默认跳过 |
| 真实浏览器对话 | 显式开启后 1 passed；模型完成时间波动，断言等待上限设为 60 秒 |
| 真实 DeepSeek + PostgreSQL 长对话 | 9 次模型理解调用，摘要版本 1 覆盖消息序号 6；18 条原文保留；第二后端进程读取摘要并将预算更新到 90 元。测试会话 `2f67dbcf-59de-4e25-a55f-65a86a09b1f0` |

首次低预算联调时，DeepSeek 默认思考模式在摘要的 800 输出 token 内只返回推理，`finish_reason=length`，摘要没有写入。改为官方支持的 `thinking: disabled` 后，独立摘要探针和完整长对话联调通过。失败期间未推进摘要游标。相关参数见 [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) 与 [Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)。

复现真实摘要检查：在已运行的正常后端之外，以 `SOLOVIBE_PORT=8001`、`SOLOVIBE_UNDERSTAND_INPUT_TOKENS=4500` 启动第二后端，再运行 `python scripts/verify_stage2_live.py`。该脚本会创建测试会话并消耗少量真实模型额度。常规自动测试不调用外部模型。

## 边界

这里的 token 数是保守估算，不是供应商 tokenizer 的逐 token 计数；应用硬预算仅为当前模型调用的内部上限。摘要是有损叙述，不能保证所有早期语义引用都可恢复；对需要精确引用的后续方案选择，阶段四还必须使用 plan ID/版本与原文或业务记录。阶段三的地图与搜索证据也须各自设输入预算，不能把网页全文塞入摘要。
