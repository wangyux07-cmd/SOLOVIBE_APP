# Vercel 前端与独立后端部署

Vercel 部署前端会获得一个 HTTPS `*.vercel.app` 地址。此项目的 FastAPI、LangGraph 和 PostgreSQL checkpointer 需要稳定的后端运行环境；仅把 Vite 前端传到 Vercel，页面可以打开但无法生成方案。官方 Vercel 外部 rewrites 可把同源 `/api/*` 转发至公网 HTTPS 后端。

1. 先将 `deploy/Dockerfile.backend` 的镜像部署到一个可持续运行、可访问 Supabase 与 DeepSeek/高德的 HTTPS 后端地址。Docker Hub 账号或镜像仓库本身不是持续运行的 Web 服务。可选用 Render Web Service：连接本 GitHub 仓库的 `Refactor` 分支，运行环境选 Docker，仓库根目录作为 build context，Dockerfile 路径设为 `deploy/Dockerfile.backend`，公开端口配置为 `8000`，健康检查路径为 `/api/v1/readiness`。Render 会提供 `*.onrender.com` 地址。密钥只存后端服务的环境配置，不加入镜像或 Vite 变量。首次部署后验证 readiness；如尚无 Render 账号，先完成其他本地/CI 验证即可。
2. 用真实后端 HTTPS origin 替换 `deploy/vercel.frontend.template.json` 中的 `YOUR_PUBLIC_BACKEND_HOST`，把结果保存为 `frontend/vercel.json`，与前端一同提交。API rewrite 必须放在 SPA fallback 前。不要在此文件写密钥。
3. 在 Vercel 导入 GitHub 仓库，Root Directory 设为 `frontend`，Framework 选择 Vite，Build Command 为 `npm run build`，Output Directory 为 `dist`。`VITE_API_BASE_URL` 留空，浏览器始终请求同源 `/api`。Vercel 分配的项目地址可直接用于演示，无需先购买自定义域名。
4. 后端生产配置：`APP_ENV=production`、`SESSION_COOKIE_SECURE=true`、`CORS_ORIGINS=https://<实际-vercel-app-域名>`；`PUBLIC_HOSTS` 至少包含后端自身的 `*.onrender.com` 主机名和代理转发的实际 Host（通常是 Vercel 域名），须在目标环境核实并精确配置。禁止通配符。Cookie、定位、写请求与长请求须在真实 Vercel URL 做完整浏览器验收。
5. 重新运行 `scripts/verify_multistop_live.py` 和一次浏览器真实路径，检查前端到 API 的 Cookie、CORS、响应时长及高德逐段导航链接。发布失败先停止公开入口或恢复上一次 Vercel 部署；生产流量回切演练可在公开给用户前完成。

当前仓库只提供模板，**没有已部署的后端地址、Vercel 项目或可验证的公网域名**，所以不能把 `*.vercel.app` 部署记录为已完成。
