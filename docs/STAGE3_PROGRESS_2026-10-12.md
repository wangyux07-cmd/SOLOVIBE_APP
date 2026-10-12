# 阶段三交付记录 — 2026-10-12

状态：**已实现并完成真实模型、数据库、高德、Tavily 与浏览器联调**。凭据来自用户本机原有的被 Git 忽略的配置文件，仅复制到当前项目的被忽略 `.env`，没有进入提交或日志。高德 Key 在 2026-10-12 的真实请求中有效；将来失效时需要更换地图供应商或新 Key。

## 已实现

- 原 LangGraph 在约束齐备后进入 `collect_evidence → verify_feasibility → enrich_sources → publish_plans → persist_reply`。早期对话整理和结构化状态仍由阶段二处理。地点查询只发生在规划意图且城市、出发位置、预算、可用时间均已提供时。
- 高德 Web 服务适配器调用地理编码、周边 POI 搜索、步行路线 2.0 和 POI ID 详情。地点必须有 POI ID、名称、地址、坐标；城市不一致、定位结果多义或过粗时拒绝使用。最多 3 个兴趣词、8 个候选、4 路并发算路，临时只读错误最多重试一次。偏好无结果时最多一次扩大为公园/博物馆；不会放宽时间、步行或排除条件。POI 详情的 ID/坐标/地址冲突会拒绝合并。
- 规则层只采纳有步行路线、去程在可用时间及步行上限以内、未命中排除条件的地点。返回 1–3 个有 POI ID、来源、查询时间、路线距离和去程时长的**待核实选项**。详情有值时展示高德评分、参考人均和登记营业时间；这些不是实际消费或实时营业证明。网页摘要不进入硬约束判定。
- 可选 Tavily 搜索最多为每个选项返回 3 个标题/链接。门店身份未核实，前端明确标注。没有搜索 Key 时保留 `not_configured`；搜索失败不伪造套餐、价格、评级或营业时间。
- `solovibe_v1.plan_sets` 按 run 和状态版本保存方案或空结果。读取会话及 `GET /api/conversations/{thread_id}/plans` 均检查现有会话所有权，并只返回当前状态版本的最近方案组。改了地点或预算后旧版本方案不会显示。
- 前端以真实 API 的方案组绘制地点卡，展示地图来源、路线证据和未知项；不提供假预约/假执行。

## 验证证据

| 检查 | 结果 |
| --- | --- |
| 供应商契约测试 | MockTransport 验证正常 POI+路线、定位歧义、无权限不重试、超时有界重试、空结果、网页链接白名单；通过 |
| LangGraph 分支测试 | 完整图实际运行并穿过阶段三 5 个节点；通过 |
| Python 全部当前测试 | 42 passed |
| 前端类型与生产构建 | 通过 |
| 数据库增量迁移 | 对本地配置的 Supabase Session pooler 执行成功 |
| 真实 DeepSeek + PostgreSQL + LangGraph | 先验证缺 Key 时 `provider_unavailable`、0 方案；配置后完整图返回 3 个真实 POI，方案组持久化，模型/地图/搜索链路实际运行 |
| 高德与 Tavily 实际调用 | 地理编码、周边 POI、步行路线及 POI 详情真实成功；3 个选项的详情 ID 均匹配，评分与登记营业时间有来源。Tavily 对 3 个选项各返回 3 个链接，均标为未核实分店 |
| 浏览器端到端 | Edge 实际发送规划消息、显示 1–3 张真实卡片、刷新后从数据库恢复，1 passed；常规 UI 检查 3 passed，1 个阶段一真实测试默认跳过 |

使用 `python scripts/verify_stage3_live.py --require-options` 复验真实供应商。该脚本会创建新会话、消耗模型及外部 API 配额，要求 1–3 个实际地点及持久化方案组。浏览器测试可用 `SOLOVIBE_LIVE_STAGE3=1` 显式开启。不要把 Key 粘贴到聊天、提交到 Git 或放进前端环境变量。

## 阶段边界

当前的时间判断只核对**去程步行**，并未核对往返时间、活动耗时、实时拥挤、当前营业状态、实际消费与门店可用性，因此卡片保持“待核实”。网页搜索仅给来源链接，不能把同名门店网页与高德 POI 自动绑定；菜单、套餐和实际价格仍未知。部分候选的路线查询曾返回供应商错误，系统剔除了这些候选，仍用有路线证据的候选生成 3 张卡。阶段四才实现方案选择、确认、导航交接和状态恢复。

供应商接口按官方文档实现：[高德地理编码](https://lbs.amap.com/api/webservice/guide/api/georegeo/)、[高德 POI 搜索与 ID 详情](https://lbs.amap.com/api/webservice/guide/api/search/)、[高德步行路线 2.0](https://lbs.amap.com/api/webservice/guide/api/newroute)、[Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search)。真实联调发现步行耗时只有在 `show_fields=cost` 时返回，位置为 `route.paths[0].cost.duration`；适配器与测试已据此修正。
