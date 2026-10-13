# V3-6 数据生命周期与发布记录

日期：2026-10-13
结论：开发环境中的数据删除、过期清理、配置边界、真实浏览器链路及独立数据库备份恢复演练已验证。**尚未达到生产发布门槛**：生产域名、TLS 代理和商家授权数据未配置，目标生产环境也未进行发布和回滚演练。

## 已实现

- 所有者可以从页面删除单个会话。服务端在同一 PostgreSQL 事务中删除消息、运行、摘要、方案、动作、反馈和三张 LangGraph 检查点表的数据。其他所有者无法删除。
- 匿名会话 30 天过期。`scripts/cleanup_expired.py` 默认只预览；生产调度运行 `--apply`，忙碌会话跳过并在下一轮重试。公开地点来源资料独立于用户会话保留。
- 生产模式要求显式 HTTPS `CORS_ORIGINS`、`PUBLIC_HOSTS` 和安全 Cookie；跨域写入被拒绝。前后端应部署在同一个站点，API 由可信 TLS 代理转发。
- GitHub Actions 运行 Python 编译、隔离依赖的契约测试、TypeScript 检查、生产构建与浏览器模拟测试。真实供应商测试仍须显式启用，以免 CI 消耗额度。
- 修复旧配置助手的语法错误和明文配置输出。`backend/start.bat`、`backend/start.sh` 指向当前应用；旧原型入口仅作为历史参考。

## 实测证据

- 当前开发数据库的增量迁移成功；真实 V3-5 服务测试返回 3 个路线方案，验证版本变更、重放、跨进程状态、单店重查、反馈和一致删除。
- 真实 Edge 浏览器完成：授权定位 → 去返程道路折线 → 官方品牌菜单来源 → 预算修改 → 确认保存 → 刷新恢复 → 删除会话。
- 人工构造的过期匿名会话经预览后被清理，会话及所有者记录均为零；正常全库预览未发现过期会话。
- `pytest -q`：103 passed；前端 lint 和 build 通过；浏览器模拟用例 7 passed、6 skipped（需真实服务的用例默认不运行）；独立真实浏览器用例 1 passed。
- 使用与 Supabase PostgreSQL 17 兼容的本机 PostgreSQL 17.11 客户端，对现有数据库的 `solovibe_v1` 和 `solovibe_graph` schema 完成自定义格式备份；归档清单验证通过。归档保存在被 Git 忽略的 `.runtime/backups/` 中，不进入仓库。
- 在仅绑定 `127.0.0.1` 的独立空白 PostgreSQL 17.11 库中执行 `restore-drill`，并验证业务会话、运行和 LangGraph 检查点表均存在。该测试库与 Supabase 的主机和库不同；源数据库未被恢复操作写入。测试库文件保留在 `.runtime/pg-scratch-data/` 供本机复查。
- [GitHub Actions](https://github.com/wangyux07-cmd/SOLOVIBE_APP/actions/runs/38470722720) 对提交 `6f2e6bff` 的 CI 检查成功。

## 生产操作顺序

1. 使用独立的密钥管理服务注入 `DATABASE_URL`、`DEEPSEEK_API_KEY`、`AMAP_API_KEY`、`TAVILY_API_KEY`；不要放进前端 `VITE_*` 变量或日志。设置 `APP_ENV=production`、`SESSION_COOKIE_SECURE=true`、`PUBLIC_HOSTS=app.example.com`、`CORS_ORIGINS=https://app.example.com`。这里的域名仅为示例。
2. 在受控主机安装与数据库服务器兼容的 PostgreSQL 客户端，运行 `python scripts/backup_restore.py backup`。备份位于忽略提交的 `.runtime/backups/`；另行加密并限制读取权限。
3. 提供一个**独立、空白**的 PostgreSQL 测试数据库，通过本机环境变量 `SOLOVIBE_RESTORE_DSN` 指定。运行 `python scripts/backup_restore.py restore-drill --archive <备份路径>`。脚本拒绝与线上相同的主机/端口/库名组合，也拒绝覆盖已有 SoloVibe 表。
4. 备份与恢复演练都成功后，运行 `python scripts/migrate_stage1.py`，启动后端并检查 `/api/v1/readiness`，再用同站点 TLS 代理发布前端。代理读写超时至少 180 秒；示例见 `deploy/nginx.conf.example`。对外关闭旧原型入口。
5. 每日调度 `python scripts/cleanup_expired.py --apply`，记录只含数量的结果；监控 readiness、HTTP 错误和供应商失败分类，避免记录用户消息、位置或密钥。发布前在目标环境重跑一条无模拟的浏览器完整路径。

回滚时先停止新的写请求，保留当前故障现场，使用第 3 步已验证的备份在受控目标恢复，再切回上一版应用并检查读取与动作幂等性。本次已验证独立数据库恢复，但**尚未演练生产流量切换和上一版应用回退**。

## 仍需外部条件

V3-2 的分店菜单/价目覆盖为 0/3，V3-3 的合格当前套餐为 0/1，V3-4 的真实授权商家为 0/1。它们是供应商来源和授权门槛，代码不会把未知值补成真实状态。
