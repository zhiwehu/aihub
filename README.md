# aihub-web

AIHub 的管理控制台：模型配置、客户端接入与凭证管理、记录回放、MCP 工具、
任务链、日程与统计页。聊天和麦克风录音已移至独立客户端。

纯静态文件，没有构建步骤，也没有运行时依赖。

## 目录

```text
public/
├── index.html            单页外壳
├── app.js                管理与记录逻辑
├── api-response.mjs      响应解码：非 JSON 的失败也要说清 HTTP 状态
├── connections.js        客户端接入向导、设备与固件状态
├── client-access.js      独立客户端凭证管理
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
[`aihub-firmware`](../aihub-firmware)。控制台只保留「客户端接入」向导、刷机面板的
骨架（`index.html` 里的 `#echoear-installer`）和连接设置。

选中喵伴时，`connections.js` 按需 `import('/firmware/echoear-installer.js')`。这个路径
由 `aihub-server` 发布：`AIHUB_FIRMWARE_ROOT`（工作区默认指向
`aihub-firmware/flash`）。模块加载并绑定好面板后会注册 `window.AIHubFlasher`，
控制台据此决定显示面板还是退回文字向导 —— 服务端没挂载那个目录时，面板不出现，
向导和连接配置下载照常可用。

两边通过 `window` 事件通信，改名必须同时改：

| 契约 | 方向 | 说明 |
|---|---|---|
| `window.AIHubFlasher` | 固件模块注册 | 模块绑定完面板后注册；控制台据此认为刷机面板可用 |
| `aihub:firmware` | 控制台 → 模块 | 下发清单里选定的固件（`detail` 含 download 与 sha256） |
| `aihub:connection-prepared` | 模块 → 控制台 | 配网就绪，刷新设备状态 |

没有加载刷机模块时（模块缺失、`AIHUB_FIRMWARE_ROOT` 没指向 `flash/`、或浏览器
不支持 Web Serial），`connections.js` 仍然可用：面板保持隐藏，页面显示接入向导、
连接配置下载和「USB 配网助手没有加载」的说明。

## 迁移说明

从单体仓库 `miaoban-voicehub` 的 `voicehub/static/` 迁出，**不带旧提交历史**。

1. **自定义事件全部改名** `voicehub:*` → `aihub:*`，与 `aihub-firmware` 对齐。
2. **`localStorage` 键改名**（`voicehub-client` → `aihub-client` 等）。代价是升级后
   浏览器里保存的麦克风选择和上次页面会重置一次，之后的偏好正常保留。
3. **刷机脚本从控制台移除，改由 `/firmware/` 加载**（见上一节）。面板骨架留在
   `index.html`，因为模块在加载时直接按 id 绑定；`tests/test_flasher_panel.mjs`
   锁住这份 id 契约。
4. `mcp-calls.mjs` 的单元测试跟过来，路径改为 `../public/`。

## 测试

```sh
node --check public/*.js public/*.mjs
node tests/test_mcp_calls.mjs
node tests/test_api_response.mjs
node tests/test_flasher_panel.mjs
```

现在 11 个自动化用例（调用记录 4、响应解码 4、刷机面板契约 3）。

### 浏览器验证（2026-11-01，Chrome headless）

| 检查 | 结果 |
|---|---|
| 「客户端接入」首屏 | 客户端卡片、向导、设备列表全部渲染 |
| 选中喵伴且服务端挂载 `/firmware` | USB 面板出现（连接设备 → 配网 → 开始对话），高级连接设置收进面板 |
| 选中喵伴但 `/firmware` 缺失 | 面板隐藏，显示接入向导与「USB 配网助手没有加载」说明 |
| 服务端异常返回 text/plain 500 | 页面显示「服务暂时不可用（HTTP 500）」，不再是 JSON 解析错误 |

之前那轮（2026-10-31）的结论「选中 EchoEar 无报错」掩盖了一个问题：面板骨架被删掉后，
`drawGuide()` 仍然隐藏向导，整页只剩高级设置。这次连骨架一起补回来了。

**没有验证的**：真实麦克风收音、语音识别与回复播放的完整链路（需要声卡和已启动的模型
worker）。`app.js` 仍是单个大文件，没有构建工具；界面文案仍写作「声桥 VoiceHub」，
是否改成 AIHub 属于产品命名决定，不在本次拆分范围内。

截图：`/tmp/aihub-connections.png`、`/tmp/aihub-narrow.png`（临时文件，不入库）。

原创代码 MIT（见 [LICENSE](LICENSE)）。

## Independent client and record sources

The browser chat/recording client lives in `aihub-server/clients/web-demo/` and
runs at the separate client listener (default localhost:8768/demo/). This console
never requests microphone access. Create/revoke named client credentials under
client connections; do not put administrator tokens in client scripts.

Conversation/recording lists support source and exact device ID filtering. Online
device entries link to those same global lists with the device filter selected.
Recordings also support status/start-time filters. Old records are explicitly
unknown and are not attributed using display-name guesses. External HTTP model
status reports a read-only discovery probe without offering process controls.
