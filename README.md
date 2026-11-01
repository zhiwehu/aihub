# aihub-web

AIHub 的网页控制台与语音聊天客户端：模型配置、连接实验室、录音工作台、MCP 工具、
任务链、日程与统计页。

纯静态文件，没有构建步骤，也没有运行时依赖。

## 目录

```text
public/
├── index.html            单页外壳
├── app.js                主逻辑（约 92 KB，尚未拆分模块）
├── api-response.mjs      响应解码：非 JSON 的失败也要说清 HTTP 状态
├── connections.js        客户端接入向导、设备与固件状态
├── capture.js            浏览器麦克风采集
├── mcp-*.js/.mjs         MCP 工具、扩展、设置、调用记录
├── workflows-ui.js       任务链
├── skills-ui.js          技能
├── calendar-ui.js        日程
├── everyday-ui.js        购物清单 / 计时器 / 物品记录
├── file-organizer-ui.js  文件整理
├── operations-ui.js      后台任务
└── style.css
tests/
├── test_mcp_calls.mjs    调用记录合并的单元测试
└── test_api_response.mjs 响应解码与非 JSON 错误提示
```

服务端出错时不一定回 JSON：`aiohttp` 的未捕获异常是 `text/plain` 的
`500 Internal Server Error`，直接 `response.json()` 会得到
`Unexpected non-whitespace character after JSON at position 4`（`500 ` 被当成数字）。
所以所有控制台请求都走 `api-response.mjs`，失败时按 HTTP 状态给出可读提示。

## 怎么被服务

`aihub-server` 从 `AIHUB_WEB_ROOT`（默认 `<data>/web`）提供这些文件：

- `/` → `index.html`
- `/static/*` → 同目录下的资源

所以把 `public/` 的内容复制到 `<data>/web` 即可，也可以直接指向这个目录：

```sh
export AIHUB_WEB_ROOT=/Users/you/ai/aihub/aihub-web/public
```

**没有安装构建产物时，服务端首页会显示一行说明**，不会白屏。

## 依赖的服务端契约

| 用途 | 端点 |
|---|---|
| 会话与事件 | `WS /ws`（协议 v1）、`GET /api/events` |
| 配置 | `GET/PUT /api/config`、`GET /api/status` |
| 录音 | `GET/POST /api/recordings…`、`GET /api/recordings/{id}/ready` |
| 会议纪要 | `GET/POST /api/recordings/{id}/minutes…`（服务端代理到 `aihub-models`） |
| 工具与扩展 | `GET /api/mcp…`、`POST /api/mcp/import` |
| 任务链 | `GET/POST /api/workflows…` |
| 客户端接入 | `GET /api/connections`、`GET /api/clients/{client}/…` |

管理接口需要同源访问，或在 `127.0.0.1` 上直连。

## 刷机助手不在这个仓库

USB 刷机（Web Serial、NVS、备份恢复）是设备专属能力，属于
[`aihub-firmware`](../aihub-firmware)。控制台只保留"客户端接入"向导和连接设置。

两边通过 `window` 事件通信，改名必须同时改：

| 契约 | 方向 | 说明 |
|---|---|---|
| `window.AIHubFlasher` | 固件模块注册 | 存在时控制台认为刷机面板可用 |
| `aihub:firmware` | 控制台 → 模块 | 下发清单里选定的固件（`detail` 含 download 与 sha256） |
| `aihub:connection-prepared` | 模块 → 控制台 | 配网就绪，刷新设备状态 |

没有加载刷机模块时，`connections.js` 仍然可用：它会跳过 `#echoear-installer`
面板，只丢掉刷机这一步。

## 迁移说明

从单体仓库 `miaoban-voicehub` 的 `voicehub/static/` 迁出，**不带旧提交历史**。

1. **自定义事件全部改名** `voicehub:*` → `aihub:*`，与 `aihub-firmware` 对齐。
2. **`localStorage` 键改名**（`voicehub-client` → `aihub-client` 等）。代价是升级后
   浏览器里保存的麦克风选择和上次页面会重置一次，之后的偏好正常保留。
3. **刷机面板及其脚本从控制台移除**，见上一节。
4. `mcp-calls.mjs` 的单元测试跟过来，路径改为 `../public/`。

## 测试

```sh
node --check public/*.js public/*.mjs
node tests/test_mcp_calls.mjs
```

只有 4 个自动化用例。

### 浏览器验证（2026-10-31，Chrome headless / Playwright）

对着真实服务端（`aihub-server --data … --port 8807`，`AIHUB_WEB_ROOT` 指向本仓库
`public/`）跑过一轮：

| 检查 | 结果 |
|---|---|
| 首屏加载、事件流连接 | 正常，控制台 **0 个 error / pageerror** |
| 切换 5 个视图（连接、模型、录音、MCP、网页聊天） | 无报错 |
| 「客户端接入」渲染客户端卡片与向导 | 正常 |
| 选中 EchoEar（移除刷机面板的那条分支） | 无报错，`#echoear-installer` 不存在，高级连接设置仍可见 |
| 390×844 窄屏 | 无横向溢出，导航折叠成横条，卡片堆叠 |

**没有验证的**：真实麦克风收音、语音识别与回复播放的完整链路（需要声卡和已启动的模型
worker）。`app.js` 仍是单个大文件，没有构建工具；界面文案仍写作「声桥 VoiceHub」，
是否改成 AIHub 属于产品命名决定，不在本次拆分范围内。

截图：`/tmp/aihub-connections.png`、`/tmp/aihub-narrow.png`（临时文件，不入库）。

原创代码 MIT（见 [LICENSE](LICENSE)）。
