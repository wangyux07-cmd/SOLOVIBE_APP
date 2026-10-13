# V3-2 交付报告：公开商家资料流水线

> 日期：2026-10-13。对照 [V3 方案](AI_AGENT_REDESIGNED_PLAN_V3.md) 的 V3-2。**代码链路已实现并完成真实联调；“3 个固定试点取得分店级官方或授权菜单/价目”的覆盖门槛尚未达到。**

## 本轮实现

- 独立的 `services/public_sources.py` 负责经批准的官网候选、HTTPS/主机校验、Tavily Extract、按 URL 的成功或失败判读、菜单/票价结构化抽取与分店身份检查；不让地图适配器或语言模型解释网页正文。现有 Tavily Search 的结果仍只是线索，不能变成分店事实。
- `venue_identity`、`source_observation`、`venue_claim` 增量保存地点身份、来源域名、URL、抓取结果、字段范围、获取时间、正文哈希与最多 400 字的短片段，以及关联的字段 Claim；不保存 2,581 字的网页全文。单次规划共享相同 URL 的提取结果，最多处理 3 个方案、每个来源最多 2 个 URL。
- 前端展示“品牌菜单示例”和“本分店菜单资料”两种不同范围，给出原始 HTTPS 链接与获取时间。没有页内明示价格不产生价格；品牌商品不通过分店级约束。页面上明确说明菜单不证明当天有售。
- 错店、Tavily HTTP 200 但单 URL 失败、删价、来源价目冲突、非法 URL、区域明确不售卖的商品均有确定性降级测试。当前未实现“当前套餐/优惠、实时营业、库存/座位”，这些分别在 V3-3/V3-4 的证据门槛内。

## 真实证据与覆盖

- 用现有 Tavily Key 对[星巴克中国早餐官网](https://www.starbucks.com.cn/menu/food/great-breakfast/)执行真实 Extract：HTTP 200，`results=1`、`failed_results=0`，正文 2,581 字符；抽取 5 个适用于品牌展示的商品标题。官网没有该试点分店价格或当天在售信息，**分店菜单 0、明示价格 0**。已核对真实 PostgreSQL 记录：`scope=brand`、官网域名和提取状态已存，短片段 86 字，Claim 无价格。
- 真实 DeepSeek → LangGraph → 高德 → Tavily → PostgreSQL 规划返回 3 个星巴克地点方案，均显示品牌菜单、均未显示分店菜单。真实浏览器用**注入的样例 GPS**完成定位、规划、官网来源展示、刷新后恢复；未使用这台设备的实际 GPS。
- [12 个固定试点结果](V3_STAGE2_PILOT_RESULTS_2026-10-13.json)：批准来源目录覆盖 1 个品牌菜单样本，另 11 个没有本轮批准的官方页面；**分店级官方/授权菜单或价目为 0/3**。这衡量的是当前经过核验的来源目录覆盖，不代表网络上不存在其他来源。未经授权的平台详情页、过期活动价和搜索摘要没有被拿来凑数。

### 继续查找官方公开来源的结果

| 固定试点 | 查到的公开来源 | 本轮判定 |
| --- | --- | --- |
| Manner Coffee（美罗城店） | [Manner 官网](https://www.wearemanner.com/) 可被 Tavily Extract 读取，但提取文本是品牌介绍和门店目录，没有该店菜单或价格 | 可作门店线索，不产出分店菜单 Claim |
| 上海电影博物馆 | [上海文旅推广网的常设展页](https://www.meet-in-shanghai.net/cn/museum/permanent-exhibition-at-shanghai-film-museum-982968/)列出漕溪北路 595 号和票价，但注明“以场馆官方发布为准”；[市文旅局 2026 年博物馆名单](https://whlyj.sh.gov.cn/bwg/20260106/265b828de4394054bdc2e61e1599ed4c.html)可核对馆址，却不提供现价 | 两页不能组成可自动确认的当前场馆价目；博物馆自有网站本轮提取超时，继续仅作候选 |
| 上海土山湾博物馆 | [上海文旅推广网页](https://www.meet-in-shanghai.net/cn/museum/shanghai-tushan-bay-museum-471389/)能核对蒲汇塘路 55 号，但收费栏为空；历史文旅月刊写过免费 | 不能把空收费栏或旧月刊解释为当前免费票价 |
| 其他固定试点 | [上海市 2026 年 5 月限时半价活动](https://www.shanghai.gov.cn/nw4411/20260515/d53a017d77fb4c1ca7e5893e063e536b.html)和[9 月旅游节限时优惠](https://www.shanghai.gov.cn/nw17239/20260911/743ed95b8f23494d943ae0f3929b4491.html)有真实价目线索 | 活动均已结束，不能当作 10 月仍有效的套餐/票价 |

这些页面有助于发现来源和交叉核对场馆身份，却不满足本轮要求的**现时、具体地点、可回溯价目**。后续优先联系场馆或接入其官方票务页，再以同一 POI 身份、页面价目和获取时间重新验收。

## 验证

- `scripts/check.ps1` 的 **75 项 Python 边界测试**、TypeScript 类型检查和生产构建通过；常规 Playwright **5 项通过**。隔离端口上的 V3-2 真实浏览器测试 **1 项通过**，刷新后仍能看到数据库持久化方案里的官网资料。
- `scripts/verify_v3_stage2_live.py` 对 Tavily Extract 和 PostgreSQL 做真实读写；`scripts/verify_v3_stage2_graph_live.py` 对 DeepSeek、LangGraph、高德、Tavily 和 PostgreSQL 做真实规划。脚本不输出密钥或网页全文。

## 剩余交付条件

V3-2 的 3 个分店级样本仍需各自的官方门店页、官方票价页或获授权的商家数据，且页面能把**具体门店身份**与**菜单/价目**连在一起。接入时可按已实现的来源目录和字段契约逐一添加并复测；若只有品牌页，就继续只展示品牌示例。下一阶段 V3-3 不能把这些品牌示例当作某分店可售套餐或预算依据。
