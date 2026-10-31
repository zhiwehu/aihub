# aihub-tools

AIHub 的助手能力层：MCP 工具、任务链工作流、本地日历/购物清单/计时器/物品记忆、
用户导入的 MCP 扩展、Skills，以及本地 Rex 小模型路由器。

**这是被 `aihub-server` 同进程 import 的库，不是一个网络服务。**
工具规划位于每一轮对话的热路径上，拆成 RPC 只会多一次跳转和一个失败点。

## 目录

```text
src/aihub_tools/
├── context.py          服务端必须满足的接口（Protocol）
├── settings.py         只读 settings.json 里的 tools 段
├── errors.py           DeviceMCPError
├── tools.py            工具目录、参数校验、计划解析
├── tool_chat.py        一轮对话里选择/确认/执行工具并接续生成
├── extension_routing.py  规则优先的路由（音乐、文件、音量、闲聊判定）
├── mcp_tools/          内置工具：天气、新闻、系统信息、音乐、文件整理、
│                       日历、购物清单、计时器、物品记忆、设备音量
├── workflows/          任务链：计划、邮件、产物、存储、聊天
├── mcp_client.py       stdio MCP 客户端（内置工具与扩展共用）
├── mcp_http.py         Streamable HTTP MCP 客户端
├── mcp_extensions.py   用户导入/远程 MCP 服务管理
├── rex_planner*.py     本地 Rex 路由器（独立子进程）
├── training/           Rex 的分类/槽位运行时与 LoRA 工具
└── *_store.py          日历、日常记录
```

## 与服务端的关系

工具层**不能 import `aihub_server`**。它需要的一切由调用方传进来：

```python
pipeline.runtime.planner      # 本地 Rex 路由器
pipeline.runtime.data_root    # 数据目录
pipeline.runtime.extensions   # 用户 MCP 扩展
pipeline.runtime.workflows    # 任务链
pipeline.chat(history)        # 普通回复（含工具规划）
pipeline.raw_chat(history)    # 不经过工具层的纯生成
pipeline.device               # 当前会话的设备 MCP 桥（离线时 None）
```

完整契约见 [`context.py`](src/aihub_tools/context.py)。

> 拆库前这些通过一个杂物袋对象 `pipeline.local` 取用，依赖是隐形的。现在统一成
> `pipeline.runtime`，`ToolRuntime` Protocol 把契约写下来了。

## 配置

只读 `settings.json` 的 `tools` 段，不解析服务端的完整配置 schema：

```python
from aihub_tools.settings import data_root, tool_enabled, load_tool_settings

root = data_root()                    # AIHUB_DATA_ROOT > ./data
tool_enabled(root, 'calendar')        # settings.json 里 tools.calendar
```

读不到或文件损坏时回退到 `TOOL_DEFAULTS`，而不是抛错——工具子进程读不到配置时
应该报告「未启用」，不该让整轮对话失败。

## 子进程

三个子进程入口，都用 `python -m` 启动，工作目录是 `src/`（`-m` 会把 cwd 放进
`sys.path`）：

| 入口 | 用途 |
|---|---|
| `aihub_tools.common_tools` | 内置工具的 stdio MCP 服务 |
| `aihub_tools.email_mcp` | 独立邮件 MCP 服务 |
| `aihub_tools.rex_planner_worker` | Rex 分类/抽取进程（torch） |

`CommonToolsClient` 给子进程的环境变量是白名单：只保留
`PATH / PYTHONPATH / HOME / LANG / LC_ALL / TMPDIR / SSL_CERT_FILE / SSL_CERT_DIR`，
不会把模型密钥或管理令牌传下去。

## 安装与测试

```sh
pip install aihub-tools
pip install "aihub-tools[rex]"   # 需要本地路由器时

PYTHONPATH=src python -m pytest tests -q
```

测试不需要模型、网络或 torch：Rex 用假引擎，MCP 走同一进程内的 stdio 子进程。

## 迁移说明

从单体仓库 `miaoban-voicehub` 的 `voicehub/` 迁出，**不带旧提交历史**。改动：

1. `..config.ConfigFile` → `aihub_tools.settings`（只读 tools 段，带默认值回退）。
2. `..device_mcp.DeviceMCPError` → `aihub_tools.errors`。服务端改为从这里 import。
3. `pipeline.local.*` → `pipeline.runtime.*`。
4. `training.*` → `aihub_tools.training.*`；`voicehub.slot_normalizer` → `..slot_normalizer`。
5. 子进程模块名随之改名（`voicehub.common_tools` → `aihub_tools.common_tools` 等）。
   这一处改错会在运行时才炸，已单独核对。

**刻意没改**：`timer_reminders` / `calendar_reminders` 里 `uuid5` 的命名空间字符串仍是
`voicehub-timer:` / `voicehub-calendar:`。它们是稳定 ID 的种子，改了会让已有提醒换 ID。
需要改的话应当单独做一次带迁移的变更。

### 训练与评测

`scripts/` 下是路由器的数据构建、训练与评测脚本，`data/training/router-everyday-v5/`
是配套数据集（`train/validation/test.jsonl` + manifest，sha256 与 manifest 一致）。

```sh
export AIHUB_DATA_ROOT=./data     # 脚本默认相对路径
python scripts/build_router_v5_data.py --help
python scripts/train_rex_adapter.py --help
```

这些脚本按当时的环境写成，依赖本机缓存的基座模型和 adapter；它们**没有自动化测试**，
只有语法检查。数据集进仓库是为了让评测结果可复现。

依赖服务端完整配置 schema 的测试（`test_rex_planner`、`test_skills`、`test_calendar_chat`
等）放在 `aihub-server` 的测试里——那里才有 `config` 模块。

原创代码 MIT（见 [LICENSE](LICENSE)）。
