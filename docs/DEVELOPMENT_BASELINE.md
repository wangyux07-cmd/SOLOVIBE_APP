# SoloVibe 开发基线与阶段 0 交付

日期：2026-09-13。正式目录：`D:\SOLOVIBE_APP`。开发分支现名：`Refactor`。

## 当前交付范围

本阶段建立可重复安装、启动和检查的前后端主路径。默认页面是开发工作台，显示实际 HTTP 连接状态和配置存在情况。它不生成商家或预约结果。

阶段 1–5 尚未交付。LangGraph 已安装并通过 StateGraph 导入验证，但当前请求还没有经过业务 Graph；原生 checkpoint、真实用户状态持久化、摘要、地图/搜索实调、活动推荐和确认恢复要继续实施。配置存在只表示读到了对应变量，不表示鉴权、连通或字段覆盖已通过。

## 仓库基线

- 来源：`https://github.com/wangyux07-cmd/SOLOVIBE_APP.git`。
- 开发起点：`da89caf9c69288cbf369238a66a18455cfccaae5`，与审查使用的提交一致。
- 原 `D:\SOLOVIBE` 对应不同仓库，没有修改其 origin 或业务代码。
- 三份设计文档已复制到本目录 `docs/`，作为历史决策依据。
- 仓库原跟踪 11,618 个 node_modules 文件；已停止跟踪，以锁文件安装依赖。旧依赖文件没有混入本地新安装。
- 原跟踪的两个 `.env` 已停止跟踪；新目录里的旧文件保留为忽略的 `.env.legacy`。默认入口不会读取它们，新 `.env` 来自空值模板。没有输出或使用旧凭据，没有改写远端 Git 历史。
- 整理仓库的本地提交：`2a7870fc`。尚未推送到 GitHub。

最初克隆采用 sparse checkout，排除了历史 node_modules、缓存与虚拟环境；它不是删减业务源代码。停止跟踪后，依赖目录由安装器生成。

## 运行环境

已验证 Windows 环境：Python 3.12.14、Node 24.11.1、npm 11.6.2、uv 0.12.13。

- 项目 Python 放在 `.tools/python/`，虚拟环境为 `.venv/`，不改变系统 Python 默认版本。
- `.python-version` 固定 Python 补丁版本。
- `backend/requirements.in` 是直接运行依赖；`requirements.txt` 固定完整解析结果。
- `backend/requirements-dev.txt` 包含运行依赖与测试依赖，并约束到相同运行版本。
- 当前已解析并安装 FastAPI 0.141.1、LangGraph 1.2.11、Pydantic 2.13.5，全部 78 个已安装 Python 包通过依赖一致性检查。
- 前端使用 npm workspace 与根目录 `package-lock.json`。React 类型定义和 Playwright 测试依赖已纳入锁文件。
- 本次只验证 Windows；其他平台部署时需要单独验证依赖解析与启动。

## 安装与启动

在 PowerShell 进入正式目录：

```powershell
Set-Location D:\SOLOVIBE_APP
powershell -NoProfile -File scripts/setup.ps1
```

setup 负责安装；正常启动与 build 不会偷偷安装或升级包。安装脚本只在 `.env` 不存在时复制模板，不覆盖已有本地配置。

打开两个终端分别运行：

```powershell
# 后端终端
powershell -NoProfile -File scripts/dev.ps1 -Service backend
```

```powershell
# 前端终端
powershell -NoProfile -File scripts/dev.ps1 -Service frontend
```

- 开发页面：`http://127.0.0.1:5173/`。
- 后端 API 文档：`http://127.0.0.1:8000/docs`。
- 后端健康检查：`http://127.0.0.1:8000/api/v1/health`。
- Vite 将 `/api` 转发到本机 8000 端口；浏览器代码统一通过 `src/api.ts` 构造地址。
- 两个服务仅监听本机。5173 被占用会明确失败，不会悄悄改用其他端口。
- VS Code 已提供 `SoloVibe: backend`、`SoloVibe: frontend` 和 `SoloVibe: check` 任务，打开本目录即可查看。
- 终端前台运行时用 Ctrl+C 停止对应进程。本轮后台演示进程记录在 `.runtime/processes.json`，日志也在该目录；进程号仅供本次运行参考。

生产构建使用 `npm run build`。本地预览使用 `npm run preview`，仍需后端服务。线上需单独配置后端地址、CORS、密钥和数据库，本阶段没有部署。

## 服务状态的约定

| 检查 | 阶段 0 预期 |
| --- | --- |
| `/api/v1/health` | HTTP 200，status=ok，ready=false；只证明基线进程可响应 |
| `/api/v1/config-status` | 只返回配置是否存在与 not_checked，不输出凭据 |
| `/api/v1/readiness` | HTTP 503，明确 Agent 尚未实现 |
| `/api/chat`、流式入口、恢复入口、旧方案接口 | 有效请求返回明确的 503，不生成模拟结果 |
| 空消息、空白消息、超长消息 | HTTP 422 |
| 页面“验证聊天入口” | 实际 POST 经过 Vite 到 FastAPI，显示尚未接入 Agent 的明确结果 |

这是阶段 0 的真实状态，而不是功能完成的假成功。下一阶段会用 ApplicationService 与真实 Graph 接替尚未实现的入口。

## 本阶段代码调整

1. 将旧后端入口归档至 `backend/legacy_main.py`，新增小型明确的 `main.py`；配置和日志初始化独立，启动不初始化旧模拟工具或执行外部请求。
2. 补齐旧卡片的 SoloIndexDimensions 类型，未观察维度保留 null；模型集合字段使用独立默认工厂。
3. 新增开发工作台 BaselineApp，旧 App 保留供后续迁移；新入口展示真实健康检查和清晰失败状态。
4. 修复旧前端引用未声明的 framer-motion 包、错误地图类型和非 Vite 环境变量访问；客户端地址集中管理。
5. 固定依赖、整理启动脚本与 VS Code 配置，移除根 build 内部的隐式 npm install。
6. 新增有边界的基线接口检查与真实浏览器检查。

旧 `legacy_main.py` 和其他历史模块仍存在审查指出的业务缺陷，不作为可运行生产入口验收。根目录 `main.py`、旧批处理/SSR 启动脚本及旧说明暂未删除；本文件列出的主路径为当前受支持方式。

## 验证方法与实际结果

```powershell
powershell -NoProfile -File scripts/check.ps1
```

执行后端基线测试、前端生产代码类型检查和生产构建。阶段 0 的 pytest 默认收集 `tests/baseline/`；没有执行会调用旧服务的历史调试脚本。TypeScript 检查生产源码，历史 Jest hook 测试不在生产 tsconfig 范围内，其测试运行器仍需后续迁移，不能说旧测试全部通过。

前后端启动后执行浏览器检查（需要本机已安装 Microsoft Edge）：

```powershell
npm.cmd run test:e2e --workspace frontend
# 屏幕上显示执行过程：
npm.cmd run test:e2e --workspace frontend -- --headed
```

本轮实际结果：

- 11 项后端测试通过，验证启动、配置脱敏、未就绪状态、请求校验、CORS、无模拟商家返回等。
- 生产 TypeScript 检查通过，Vite build 通过。
- 按根 package-lock.json 执行 npm ci 重装成功，随后类型检查、构建和浏览器检查再次通过。
- Python 依赖一致性检查通过；未修改系统 Python。
- 真实后端与 Vite 代理均返回健康检查 200，Agent ready=false。
- 2 项有界浏览器测试通过：真实聊天入口返回明确的 503；模拟网络中断时页面清除原成功状态并禁用检查按钮。
- 桌面与 390px 移动视口检查通过，未发现页面运行异常或横向溢出。截图保存在忽略的 `.runtime/baseline-desktop.png` 和 `.runtime/baseline-mobile.png`。
- 测试库存在一条 BlockingPortal 弃用警告，未影响本阶段检查；没有将该警告当成应用功能错误。
- 未调用真实模型、高德、搜索、Supabase 接口，未验证 API 账号；未部署或推送远端。

## 下一阶段的明确起点

阶段 1：在当前可运行入口后接入 State/DTO、ApplicationService、真实 StateGraph、用户消息与约束持久化及原生 checkpointer。第一条验收对话是“先说明预算和精力，再补充地点”，确认图保留前轮约束。数据库和模型真实联调需要安全配置账号，不能用内存模拟冒充持久化完成。

上下文机制、外部工具规则和后续行动以同目录三份设计方案为准。阶段交付只勾选已实现且通过相应检查的部分。
