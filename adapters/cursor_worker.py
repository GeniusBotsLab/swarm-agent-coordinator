from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from worker import SwarmWorker
except ImportError:
    from adapters.worker import SwarmWorker


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


class CursorWorker(SwarmWorker):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("state_path", _env("SWARM_STATE_PATH", default="swarm-cursor-state.json"))
        super().__init__(*args, **kwargs)
        self.workspace = Path(_env("CURSOR_WORKSPACE", "SWARM_WORKSPACE", default=os.getcwd())).resolve()
        self.room_id = _env("SWARM_ROOM_ID")
        self.model = _env("CURSOR_MODEL", default="composer-2.5")
        self.fast = _env("CURSOR_FAST", default="false").lower() == "true"
        self.timeout = int(_env("CURSOR_TIMEOUT", default="1800"))
        self.agent_bin = _env("CURSOR_AGENT_BIN", default="") or shutil.which("agent") or ""
        self.agent_id = ""
        self.agent_name = ""
        self.cursors: dict[str, str] = {}
        self.sessions: dict[str, str] = {}
        self._sdk_agents: dict[str, Any] = {}
        self.load_state()

    def load_state(self) -> None:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return
        self.agent_id = state.get("agent_id", "")
        self.agent_name = state.get("agent_name", "")
        self.cursors = {str(k): str(v) for k, v in (state.get("cursors") or {}).items()}
        self.sessions = {str(k): str(v) for k, v in (state.get("sessions") or {}).items()}

    def save_state(self) -> None:
        self.state_path.write_text(
            json.dumps(
                {"agent_id": self.agent_id, "agent_name": self.agent_name, "cursors": self.cursors, "sessions": self.sessions},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def bootstrap(self) -> dict[str, Any]:
        data = super().bootstrap()
        agent = data.get("agent") or {}
        self.agent_id = str(agent.get("agent_id") or self.agent_id)
        self.agent_name = str(agent.get("name") or self.agent_name)
        self.save_state()
        return data

    def addressed(self, text: str, room: dict[str, Any]) -> bool:
        if room.get("type") in {"direct", "task"}:
            return True
        names = {self.agent_name.lower(), self.agent_id.lower()}
        for match in re.findall(r"@([^\s,.;:!?]+)", text):
            token = match.lower().rstrip(".,;:!?")
            if token == "all" or token in names:
                return True
        return False

    def new_events(self, room_id: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        last = self.cursors.get(room_id, "")
        ids = [event["id"] for event in events]
        if not last or last not in ids:
            if events:
                self.cursors[room_id] = events[-1]["id"]
                self.save_state()
            return []
        out = events[ids.index(last) + 1 :]
        if events:
            self.cursors[room_id] = events[-1]["id"]
            self.save_state()
        return out

    def _sdk_model(self) -> Any:
        from cursor_sdk import ModelParameterValue, ModelSelection

        return ModelSelection(id=self.model, params=[ModelParameterValue(id="fast", value="true" if self.fast else "false")])

    def _sdk_local(self, room_id: str) -> Any:
        from cursor_sdk import CustomTool, CustomToolContext, LocalAgentOptions

        worker = self

        def post_message(args: dict[str, Any], context: CustomToolContext) -> str:
            text = str(args.get("text") or "").strip()
            if not text:
                return "empty"
            worker.message(room_id, text, f"cursor-tool:{context.tool_call_id or text[:40]}")
            return "posted"

        def update_task(args: dict[str, Any], context: CustomToolContext) -> dict[str, Any]:
            task_id = str(args.get("task_id") or "")
            status = str(args.get("status") or "")
            if not task_id or status not in {"accepted", "running", "succeeded", "failed", "cancelled"}:
                return {"ok": False, "error": "invalid task_id or status"}
            worker.task_update(task_id, status, result=args.get("result") if isinstance(args.get("result"), dict) else None, error=args.get("error"))
            return {"ok": True, "task_id": task_id, "status": status}

        return LocalAgentOptions(
            cwd=str(self.workspace),
            custom_tools={
                "post_message": CustomTool(
                    execute=post_message,
                    description="Post a message to the current Swarm room.",
                    input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                ),
                "update_task": CustomTool(
                    execute=update_task,
                    description="Update a Swarm task assigned to this agent.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "task_id": {"type": "string"},
                            "status": {"type": "string", "enum": ["accepted", "running", "succeeded", "failed", "cancelled"]},
                            "result": {"type": "object"},
                            "error": {"type": "string"},
                        },
                        "required": ["task_id", "status"],
                    },
                ),
            },
        )

    def run_sdk(self, room_id: str, prompt: str) -> str:
        from cursor_sdk import Agent

        model = self._sdk_model()
        local = self._sdk_local(room_id)
        handle = self._sdk_agents.get(room_id)
        if handle is None:
            session = self.sessions.get(room_id)
            if session:
                handle = Agent.resume(session, {"model": model, "local": local})
            else:
                handle = Agent.create(model=model, local=local)
            self._sdk_agents[room_id] = handle
            self.sessions[room_id] = handle.agent_id
            self.save_state()
        text = handle.send(prompt).text()
        return (text or "").strip()

    def run_cli(self, room_id: str, prompt: str) -> str:
        if not self.agent_bin:
            raise RuntimeError("cursor-sdk is not installed and agent CLI is not on PATH")
        cmd = [self.agent_bin, "-p", "--force", "--trust", "--output-format", "json", "--workspace", str(self.workspace)]
        session = self.sessions.get(f"cli:{room_id}")
        if session:
            cmd.extend(["--resume", session])
        cmd.append(prompt)
        env = os.environ.copy()
        completed = subprocess.run(cmd, cwd=self.workspace, capture_output=True, text=True, timeout=self.timeout, env=env)
        if completed.returncode != 0:
            err = (completed.stderr or completed.stdout or "agent failed").strip()
            raise RuntimeError(err[:2000])
        raw = (completed.stdout or "").strip()
        try:
            data = json.loads(raw)
        except ValueError:
            return raw
        session_id = data.get("session_id")
        if session_id:
            self.sessions[f"cli:{room_id}"] = str(session_id)
            self.save_state()
        return str(data.get("result") or "").strip() or raw

    def run_cursor(self, room_id: str, prompt: str) -> str:
        if _env("CURSOR_RUNTIME", default="auto") == "cli":
            return self.run_cli(room_id, prompt)
        try:
            return self.run_sdk(room_id, prompt)
        except ImportError:
            return self.run_cli(room_id, prompt)

    def reply(self, room_id: str, event: dict[str, Any], room: dict[str, Any]) -> None:
        text = str((event.get("payload") or {}).get("text") or "").strip()
        if not text or not self.addressed(text, room):
            return
        prompt = (
            f"You are the local Cursor agent for Swarm room {room.get('name') or room_id} ({room.get('type')}).\n"
            f"Workspace: {self.workspace}\n"
            f"Sender: {event.get('sender_id')}\n"
            f"Message:\n{text}\n"
            "Do the work in this workspace. Reply with a short status of what you did."
        )
        try:
            answer = self.run_cursor(room_id, prompt)
        except Exception as error:
            self.message(room_id, f"Cursor failed: {error}", f"cursor-fail:{event['id']}")
            return
        if answer:
            self.message(room_id, answer[:10000], f"cursor-reply:{event['id']}")

    def run_task(self, task: dict[str, Any]) -> None:
        task_id = task["task_id"]
        room_id = f"task_{task_id}"
        prompt = (
            f"Swarm task {task_id}: {task.get('title')}\n"
            f"Workspace: {self.workspace}\n"
            f"Input JSON: {json.dumps(task.get('input') or {}, ensure_ascii=False)}\n"
            "Do the work in this workspace. Reply with a short status of what you did."
        )
        self.task_update(task_id, "accepted")
        self.task_update(task_id, "running")
        try:
            answer = self.run_cursor(room_id, prompt)
            self.task_update(task_id, "succeeded", result={"text": answer})
            if answer:
                try:
                    self.message(room_id, answer[:10000], f"cursor-task:{task_id}")
                except Exception:
                    pass
        except Exception as error:
            self.task_update(task_id, "failed", error=str(error)[:2000])

    def tick(self) -> None:
        self.heartbeat()
        rooms = self.rooms()
        wanted = {self.room_id} if self.room_id else {room["id"] for room in rooms}
        for room in rooms:
            if room["id"] not in wanted:
                continue
            events = self.history(room["id"])
            for event in self.new_events(room["id"], events):
                if event.get("sender_id") == self.agent_id or event.get("type") != "message.created":
                    continue
                self.reply(room["id"], event, room)
        for task in self.inbox():
            self.run_task(task)

    def run_forever(self, interval_seconds: int | None = None) -> None:
        self.bootstrap()
        interval = interval_seconds or int(_env("SWARM_POLL_SECONDS", default="20"))
        print(f"cursor worker online agent={self.agent_id} workspace={self.workspace}", flush=True)
        while True:
            try:
                self.tick()
            except Exception as error:
                print(f"tick failed: {error}", flush=True)
            self.save_state()
            import time

            time.sleep(interval)


def main() -> None:
    if not _env("SWARM_URL", "SWARM_BASE_URL"):
        sys.exit("SWARM_URL or SWARM_BASE_URL is required")
    if not os.getenv("SWARM_AGENT_KEY"):
        sys.exit("SWARM_AGENT_KEY is required")
    CursorWorker().run_forever()


if __name__ == "__main__":
    main()
