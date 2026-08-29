from __future__ import annotations

import os
import time
import uuid
from typing import Any, Callable

from worker import SwarmWorker

class ChatWorker(SwarmWorker):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.room_id = os.getenv("SWARM_ROOM_ID", "")
        self.reply_handler: Callable[[str, dict[str, Any]], str | None] | None = None
        self.last_event_id = ""

    def on_chat(self, handler: Callable[[str, dict[str, Any]], str | None]) -> None:
        self.reply_handler = handler

    def chat_once(self) -> None:
        self.heartbeat()
        rooms = self.rooms()
        room_id = self.room_id or (rooms[0]["id"] if rooms else "")
        if not room_id:
            return
        events = self.history(room_id)
        for event in events:
            if event["id"] == self.last_event_id:
                break
            if event["sender_id"] == os.getenv("SWARM_AGENT_ID") or event["type"] != "message.created":
                continue
            text = str((event.get("payload") or {}).get("text", ""))
            if self.reply_handler:
                reply = self.reply_handler(text, event)
                if reply:
                    self.message(room_id, reply, f"chat:{event['id']}:{uuid.uuid4().hex}")
        if events:
            self.last_event_id = events[-1]["id"]

    def run_chat(self, interval_seconds: int | None = None) -> None:
        self.bootstrap()
        interval = interval_seconds or int(os.getenv("SWARM_POLL_SECONDS", "20"))
        while True:
            try:
                self.chat_once()
            except Exception:
                pass
            time.sleep(interval)
