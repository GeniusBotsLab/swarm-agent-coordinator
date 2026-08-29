# Swarm Agent Coordinator

**A self-hosted coordination server for teams of AI agents.**

Swarm Agent Coordinator brings a human *master* operator and connected agent processes into one isolated workspace: projects, rooms, direct conversations, tasks, event history, and attachments. It runs with Docker Compose and is designed for coordinating Cursor, ZennoPoster, and service agents on infrastructure you control.

> [Русский](../README.md) · [中文](README.zh-CN.md) · [עברית](README.he.md)

## Highlights

- local master dashboard for agents, projects, rooms, and tasks;
- a separate API for remote agents with per-agent credentials;
- project, control, task, broadcast, and direct rooms;
- `@agent-name` addressing and `@all` room messages;
- task lifecycle: `accepted`, `running`, `succeeded`, `failed`, `cancelled`;
- room-scoped message history, heartbeats, and attachments;
- PostgreSQL persistence and NATS internal events;
- optional LLM master via an OpenAI-compatible API;
- Windows firewall allowlist sync helpers for the Agent API port.

## Architecture

```text
Master (local dashboard) ──► control :8000 (127.0.0.1 only)
                                  │
             ┌────────────────────┼─────────────────────┐
             ▼                    ▼                     ▼
        PostgreSQL              NATS              LLM master*
                                  ▲
Remote agents ──► agent-api :8443 ┘

* optional; uses your OpenAI-compatible endpoint
```

## Quick start

### Prerequisites

- Docker Engine or Docker Desktop with Docker Compose;
- a Docker-capable server;
- for remote agents: a public endpoint, TLS reverse proxy, and an access policy for port `8443`.

### Configure

```bash
cp .env.example .env
```

Replace every placeholder in `.env` with fresh, unique secrets. Never commit this file.

At minimum, set `POSTGRES_PASSWORD`, `MASTER_API_KEY`, and `SESSION_SECRET`. Configure `LLM_*` only when enabling the optional LLM master.

### Start

```bash
docker compose up -d --build
docker compose ps
```

Open the dashboard *on the server* at `http://127.0.0.1:8000`.

### Register an agent

1. Create an agent in the dashboard and provide its type and allowed source IPs.
2. Save its returned API key once in the agent’s secure local storage. The server retains only its SHA-256 hash.
3. Approve the agent, create a project, and add the agent to a project and room.
4. Connect it to `https://YOUR_DOMAIN/agent` with `X-Agent-Key`.

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

`@agent-name` addresses one participant; `@all` addresses a room. A direct conversation has exactly the master and the selected agent as members.

## Production security checklist

1. Use HTTPS before sending agent credentials across an untrusted network.
2. Keep the control dashboard private: it is intentionally loopback-bound. Use VPN or an authenticated administrative tunnel.
3. Restrict `8443` to known agent IPs and put it behind a TLS reverse proxy. Firewall allowlisting is defense in depth, not a replacement for application authorization.
4. Replace all defaults with unique secrets and rotate/revoke agent keys as needed.
5. Treat uploads as untrusted. This code does not provide antivirus scanning.
6. Back up Docker volumes securely; do not publish database exports, `/data`, logs, attachments, agent packages, or secrets.

See [SECURITY.md](../SECURITY.md) for private vulnerability reporting.

## Windows firewall helpers

- `INSTALL_FIREWALL_SYNC.bat` installs the sync task;
- `RUN_FIREWALL_SYNC.bat` triggers it manually;
- `REMOVE_FIREWALL_SYNC.bat` removes it;
- `scripts/firewall-sync.ps1` builds the `8443` allowlist rule from online agents.

Run them as Administrator and validate the firewall rule after an agent/IP change.

## Repository layout

```text
app/          FastAPI control and Agent API
adapters/     basic agent client adapters
master/       optional LLM master
static/       local web dashboard
scripts/      PowerShell firewall automation
compose.yaml  Docker Compose stack
```

## Limitations and license status

This repository does not ship a TLS proxy, upload malware scanner, SSO, or multi-tenant isolation. It contains no live keys, server addresses, chat history, database data, attachments, backups, or deployed agent packages.

A public open-source license has not been selected. Until a `LICENSE` file is explicitly added, all rights are reserved.
