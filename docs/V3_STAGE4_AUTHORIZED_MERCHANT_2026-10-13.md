# V3-4 授权商家实时数据轨：开发与验收记录

日期：2026-10-13。状态：**接入机制已实现，真实授权门店验收未完成（0/1）**。本机 `backend/.env` 未配置商家授权字段；没有向美团、大众点评或任何商家实时接口发送请求，也没有把模拟响应当作真实商家资料。

## 渠道结论

美团[生态开放平台](https://openapi.meituan.com/)列出的路径包含合作申请、商务对接、方案确认、开发测试和上线。美团技术服务合作中心有[门店配置查询](https://developer.meituan.com/docs/api/foodmop-shop-queryShops)、[商品信息查询](https://developer.meituan.com/docs/api/foodmop-sku-queryVendorSpu)等**具体业务场景**接口；对应文档标明需要业务授权。文档中的[门店状态更新](https://developer.meituan.com/docs/api/foodmop-shop-status-update)是品牌方向平台同步状态，不能直接当作 SoloVibe 可以读取任意门店当前状态的公共接口。是否能用于本产品、哪些字段可读取或展示，必须由实际合作协议和平台授权确定。

现阶段选择**商家直接授权的只读 HTTPS 桥接接口**作为试点接入契约。它只是 SoloVibe 与商家系统之间的契约，不是假装已拥有美团/点评接口。未来获得平台合作后，可在相同领域契约下另写平台适配器；不能把平台私有接口 URL 填进现有桥接配置就声称接入成功。

## 已实现的边界

- `backend/services/merchant_live.py` 只在服务端完整配置固定 HTTPS 端点、Bearer 令牌、授权记录编号、授权到期时间、明确字段权限、商家公开来源页以及一组分店 ID 后才发起 GET。端点与门店 ID 来自部署配置，用户或模型不能指定请求 URL。令牌不进入前端、证据表或日志。
- 响应必须是单一门店的严格 JSON：`branch_id`、`amap_poi_id`、`observed_at`、`valid_until`，以及获授权的 `open_now` 布尔值和/或 `availability`（`available`、`limited`、`unavailable`）。错误、403、超时、错店、字段变化、授权过期、数据超过两分钟或有效期超过两分钟都降为未知。`available` 只是商家当次反馈，不表示锁位或预订成功。
- 成功读取后创建 `merchant_direct` 分店级 observation/claim，持久化成功才写入方案。前端只在有效期内显示值、来源链接和检查时间；过期立即移除状态，并阻止用旧方案准备或确认动作。
- `prepare_action` 之前重新读取并比较原方案的门店事实；确认之后 LangGraph 的 `revalidate_selected` 再读一次。不同、过期或不可读取都会拒绝旧断言，要求用户重新生成方案。现有行动仍只有保存和导航链接交接，**不执行预约、下单或支付**。

## 商家桥接响应契约

商家端提供一个固定的 HTTPS GET 地址。请求带 `Authorization: Bearer <server-side token>` 和 `Accept: application/json`。成功响应示例只说明字段格式，并非真实门店数据：

```json
{
  "branch_id": "merchant-branch-id",
  "amap_poi_id": "matched-amap-poi-id",
  "observed_at": "2026-10-13T10:00:00+08:00",
  "valid_until": "2026-10-13T10:02:00+08:00",
  "open_now": true,
  "availability": "limited"
}
```

只有取得真实商家书面授权、确认 `branch_id` 与高德 POI 映射、字段读取与产品展示权限、允许的刷新频率、授权到期日、公开来源页，以及数据语义后，才可在 `backend/.env` 填写 `.env.example` 所列 `MERCHANT_LIVE_*` 字段。`MERCHANT_LIVE_AUTHORIZATION_REF` 是运营留存的协议/工单编号，**代码无法仅凭这个字符串验证法律授权**；部署负责人必须核对原件。现有桥接契约不包含座位数、具体时段、商品库存或完整菜单；这些要在取得对应字段权限和语义定义后单独扩展，不能把笼统的 `availability` 解释成精确库存。

## 验证与剩余门槛

隔离测试覆盖未授权零请求、字段白名单、门店错配、过期、403、超时、响应格式变化、并发读取不同结果、确认前状态变化；运行 `pytest`、前端 TypeScript 检查及构建。所有这些测试使用本地 MockTransport，**不证明商家接口已接通**。

V3-4 的外部验收仍需至少一家真实授权试点门店：在协议允许的时段从该门店服务获取当前状态，在前端显示来源和检查时间，现场验证权限过期、状态变化与失败后不会继续显示旧“可用”。取得授权前，本阶段只能标记“代码准备完成、外部验收待完成”。
