# 餐厅预订入口与状态契约

当前没有商家或平台授权的下单接口。晚餐方案只提供已核实的高德餐厅地点页入口；用户可以查看并自行联系餐厅。`reservation.status` 固定为 `unavailable`，`provider_confirmation_id` 固定为 `null`。保存行程、确认导航、打开地点页均不改变这一状态，也不表示已订位。

当前计划快照中的最小结构：

```json
{
  "status": "unavailable",
  "restaurant_poi_id": "<Amap POI ID>",
  "entry_kind": "place_detail",
  "entry_url": "<Amap place URL>",
  "provider_confirmation_id": null,
  "reason": "no_authorized_booking_provider"
}
```

接入授权服务后的目标状态流转：`unavailable → awaiting_confirmation → submitting → confirmed | failed | unknown`。只有明确的用户预订授权、供应商接受的订单响应、有效的供应商确认号和持久化记录同时存在时，才能写入 `confirmed`。超时或连接中断后状态为 `unknown`，应先用幂等键向供应商查单，不能直接重试创建订单或显示成功。用户取消、方案版本变化和餐厅 POI 不一致时必须拒绝提交。接口应返回结构化错误和供应商请求 ID，且不得记录联系人、电话、密钥或付款信息到普通日志。

未来集成的验收至少覆盖：同一确认只能创建一次订单；授权取消/过期不能下单；供应商失败、空响应、超时和查单不明时均不显示已预订；确认号与餐厅及行程版本绑定；页面重载后状态与数据库一致。上线前还需一条真实测试订单的创建、查单和取消闭环。当前没有这些凭据与接口，因此不应把“代订成功”列为已实现功能。
