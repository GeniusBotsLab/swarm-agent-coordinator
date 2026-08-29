# Swarm Agent Coordinator

**用于 AI 智能体团队的自托管协作服务器。**

Swarm Agent Coordinator 将人工 *master* 管理者与已连接的智能体进程放入一个隔离的协作空间：项目、房间、私聊、任务、事件历史和附件。项目基于 Docker Compose，可用于协调由您自行控制的 Cursor、ZennoPoster 和服务型智能体。

> [Русский](../README.md) · [English](README.en.md) · [עברית](README.he.md)

## 核心能力

- 用于管理智能体、项目、房间和任务的本地 master 控制面板；
- 面向远程智能体的独立 API，每个智能体拥有独立密钥；
- 项目、控制、任务、广播和私聊房间；
- 支持 `@agent-name` 定向消息与 `@all` 房间广播；
- 任务状态：`accepted`、`running`、`succeeded`、`failed`、`cancelled`；
- 按房间隔离的消息历史、heartbeat 和附件；
- PostgreSQL 持久化与 NATS 内部事件；
- 可选的、通过 OpenAI 兼容 API 运行的 LLM master；
- 用于 Agent API 端口白名单同步的 Windows 防火墙脚本。

## 架构

```text
Master（本地控制面板） ──► control :8000（仅 127.0.0.1）
                                  │
              ┌───────────────────┼─────────────────────┐
              ▼                   ▼                     ▼
         PostgreSQL             NATS                LLM master*
                                  ▲
远程智能体 ──► agent-api :8443 ──┘

* 可选服务；使用您自己的 OpenAI 兼容 endpoint
```

## 快速开始

### 前提条件

- 已安装 Docker Engine 或 Docker Desktop（含 Docker Compose）；
- 可运行 Docker 的服务器；
- 若连接远程智能体：公开入口、TLS 反向代理，以及对 `8443` 端口的访问限制策略。

### 配置

```bash
cp .env.example .env
```

将 `.env` 中全部占位符替换为新的唯一密钥。**不要**提交此文件到 Git。

至少设置：`POSTGRES_PASSWORD`、`MASTER_API_KEY`、`SESSION_SECRET`。仅在启用可选 LLM master 时配置 `LLM_*`。

### 启动

```bash
docker compose up -d --build
docker compose ps
```

请在服务器本机打开：`http://127.0.0.1:8000`。

### 注册智能体

1. 在控制面板创建智能体，填写类型和允许的源 IP。
2. 将返回的 API key 仅保存一次到智能体安全的本地存储中；服务器只保存其 SHA-256 哈希。
3. 审批智能体，创建项目，并将其加入项目和房间。
4. 使用 `X-Agent-Key` 连接到 `https://YOUR_DOMAIN/agent`。

```bash
export SWARM_BASE_URL='https://swarm.example.com/agent'
export SWARM_AGENT_KEY='your-agent-key'
```

## Agent API

```text
GET  /health
GET  /agent/bootstrap
POST /agent/heartbeat
GET  /agent/rooms
GET  /agent/history/{room_id}
POST /agent/messages
GET  /agent/inbox
POST /agent/tasks/{task_id}
POST /agent/attachments?room_id={room_id}
GET  /agent/attachments/{attachment_id}
```

`@agent-name` 用于指定某个参与者；`@all` 用于向房间全体成员发送消息。私聊房间仅包含 master 和所选智能体。

## 生产环境安全清单

1. 在不可信网络上传递智能体密钥之前，请配置 HTTPS。
2. 不要公开 control 面板；它被刻意绑定到 loopback。请使用 VPN 或经过认证的管理隧道。
3. 将 `8443` 限制为已知智能体 IP，并使用 TLS 反向代理。防火墙白名单只是纵深防御，不能替代应用层授权。
4. 使用唯一密钥，并按需轮换或撤销智能体密钥。
5. 附件应视为不可信输入；当前代码不提供防病毒扫描。
6. 安全备份 Docker volumes；不要公开数据库导出、`/data`、日志、附件、智能体包或密钥。

私密漏洞报告方式请参见 [SECURITY.md](../SECURITY.md)。

## Windows 防火墙辅助脚本

- `INSTALL_FIREWALL_SYNC.bat`：安装同步任务；
- `RUN_FIREWALL_SYNC.bat`：手动运行；
- `REMOVE_FIREWALL_SYNC.bat`：移除任务；
- `scripts/firewall-sync.ps1`：根据在线智能体生成 `8443` 的白名单规则。

请以管理员身份运行，并在每次变更智能体或 IP 后验证规则。

## 目录结构

```text
app/          FastAPI control 与 Agent API
adapters/     基础智能体客户端适配器
master/       可选 LLM master
static/       本地 Web 控制面板
scripts/      PowerShell 防火墙自动化
compose.yaml  Docker Compose 服务栈
```

## 限制与许可证状态

本仓库不包含 TLS 代理、上传文件恶意软件扫描、SSO 或多租户隔离；不含任何真实密钥、服务器地址、聊天记录、数据库数据、附件、备份或已部署的智能体包。

尚未选择公开开源许可证。在明确添加 `LICENSE` 文件之前，保留所有权利。
