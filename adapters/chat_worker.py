from __future__ import annotations

import os
import time
from typing import Any, Callable

from worker import SwarmWorker

class ChatWorker(SwarmWorker):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.room_id = os.getenv("SWARM_ROOM_ID", "")
        self.agent_id = os.getenv("SWARM_AGENT_ID", "")
        self.reply_handler: Callable[[str, dict[str, Any]], str | None] | None = None
        self.last_event_id = ""
        self._catch_up = True

    def on_chat(self, handler: Callable[[str, dict[str, Any]], str | None]) -> None:
        self.reply_handler = handler

    def chat_once(self) -> None:
        self.heartbeat()
        rooms = self.rooms()
        room_id = self.room_id or (rooms[0]["id"] if rooms else "")
        if not room_id:
            return
        events = self.history(room_id)
        if self._catch_up:
            self.last_event_id = events[-1]["id"] if events else ""
            self._catch_up = False
            return
        started = not self.last_event_id
        for event in events:
            if not started:
                if event["id"] == self.last_event_id:
                    started = True
                continue
            if event["sender_id"] == self.agent_id or event["type"] != "message.created":
                continue
            text = str((event.get("payload") or {}).get("text", ""))
            if self.reply_handler:
                reply = self.reply_handler(text, event)
                if reply:
                    self.message(room_id, reply, f"chat:{event['id']}")
        if events:
            self.last_event_id = events[-1]["id"]

    def run_chat(self, interval_seconds: int | None = None) -> None:
        data = self.bootstrap()
        agent = data.get("agent") or {}
        self.agent_id = str(agent.get("agent_id") or self.agent_id)
        interval = interval_seconds or int(os.getenv("SWARM_POLL_SECONDS", "20"))
        while True:
            try:
                self.chat_once()
            except Exception:
                pass
            time.sleep(interval)
