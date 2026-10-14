# Vercel 前端与独立后端部署

Vercel 部署前端会获得一个 HTTPS `*.vercel.app` 地址。Render Free 上的 Python FastAPI 后端已在 `https://solovibe-oxne.onrender.com/api/v1/readiness` 返回 `ready: true`（2026-10-13 人工截图核验）。`frontend/vercel.json` 将同源 `/api/*` 转发到这个地址，浏览器代码无需存放后端密钥。

1. Render 后端使用原生 Python 服务，根目录 `backend`，构建命令 `pip install -r requirements.txt`，启动命令 `uvicorn main:app --host 0.0.0.0 --port $PORT`。Docker 不参与当前部署。密钥只存 Render 环境变量。
2. 在 Vercel 导入 GitHub 仓库的 `Refactor` 分支，Root Directory 设为 `frontend`，Framework 选择 Vite，Build Command 为 `npm run build`，Output Directory 为 `dist`。`VITE_API_BASE_URL` 留空。`frontend/vercel.json` 已包含真实后端地址、API rewrite 与 SPA fallback。
3. 已部署的 `https://solovibe-app-vcdl.vercel.app` 是后端的精确允许来源；新增自定义域名时，将其完整 HTTPS origin 加入 Render 的 `CORS_ORIGINS`。`PUBLIC_HOSTS` 保留 `solovibe-oxne.onrender.com`，如代理实际传入 Vercel Host 且触发 `Invalid host header`，再追加实际 Vercel 主机名。禁止通配符。
4. 在 Vercel URL 打开 `/api/v1/readiness`，随后做真实浏览器流程：建立会话、定位/输入、生成多站方案、修改条件、确认保存和逐段导航。检查 Cookie 与 POST 来源限制。

Render 后端和 Vercel 前端均已部署。完整公网浏览器流程仍须以实际操作结果验证。
