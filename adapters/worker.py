from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

import requests


class SwarmWorker:
    protocol_version = 1

    def __init__(self, base_url: str | None = None, api_key: str | None = None, state_path: str = "swarm-worker-state.json"):
        self.base_url = (base_url or os.environ["SWARM_URL"]).rstrip("/")
        self.api_key = api_key or os.environ["SWARM_AGENT_KEY"]
        self.state_path = Path(state_path)
        self.handlers: dict[str, Callable[[dict[str, Any]], None]] = {}

    @property
    def headers(self) -> dict[str, str]:
        return {"X-Agent-Key": self.api_key}

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = requests.request(method, f"{self.base_url}{path}", headers=self.headers, timeout=30, **kwargs)
        response.raise_for_status()
        return response.json()

    def bootstrap(self) -> dict[str, Any]:
        return self.request("GET", "/bootstrap")

    def heartbeat(self) -> dict[str, Any]:
        return self.request("POST", "/heartbeat")

    def rooms(self) -> list[dict[str, Any]]:
        return self.request("GET", "/rooms")

    def history(self, room_id: str) -> list[dict[str, Any]]:
        return self.request("GET", f"/history/{room_id}")

    def inbox(self) -> list[dict[str, Any]]:
        return self.request("GET", "/inbox")

    def message(self, room_id: str, text: str, idempotency_key: str) -> dict[str, Any]:
        return self.request("POST", "/messages", json={"event_type": "message.created", "room_id": room_id, "payload": {"text": text}, "idempotency_key": idempotency_key})

    def task_update(self, task_id: str, status: str, result: dict[str, Any] | None = None, error: str | None = None) -> dict[str, Any]:
        return self.request("POST", f"/tasks/{task_id}", json={"status": status, "result": result, "error": error})

    def upload(self, room_id: str, path: str) -> dict[str, Any]:
        with Path(path).open("rb") as file:
            response = requests.post(f"{self.base_url}/attachments", headers=self.headers, params={"room_id": room_id}, files={"file": (Path(path).name, file)}, timeout=120)
        response.raise_for_status()
        return response.json()

    def on_task(self, handler: Callable[[dict[str, Any]], None]) -> None:
        self.handlers["task"] = handler

    def run_once(self) -> None:
        self.heartbeat()
        for task in self.inbox():
            task_id = task["task_id"]
            self.task_update(task_id, "accepted")
            self.task_update(task_id, "running")
            try:
                handler = self.handlers.get("task")
                result = handler(task) if handler else {"received": True, "note": "No task handler configured"}
                self.task_update(task_id, "succeeded", result=result or {})
            except Exception as error:
                self.task_update(task_id, "failed", error=str(error))

    def run_forever(self, interval_seconds: int = 20) -> None:
        self.bootstrap()
        while True:
            try:
                self.run_once()
            except requests.RequestException:
                pass
            time.sleep(interval_seconds)
