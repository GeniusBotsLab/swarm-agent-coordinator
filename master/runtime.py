from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

import requests

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("swarm-master")

class Master:
    def __init__(self) -> None:
        self.swarm_url = os.getenv("SWARM_CONTROL_URL", "http://control:8000").rstrip("/")
        self.room_id = os.environ["SWARM_ROOM_ID"]
        self.llm_url = os.getenv("LLM_BASE_URL", "https://app.neuromedia.cloud/v1").rstrip("/")
        self.llm_key = os.environ["LLM_API_KEY"]
        self.model = os.getenv("LLM_MODEL", "gpt-5.6-terra")
        self.poll_seconds = max(3, int(os.getenv("MASTER_POLL_SECONDS", "10")))
        self.proactive_interval = max(30, int(os.getenv("MASTER_PROACTIVE_INTERVAL", "60")))
        self.proactive_enabled = os.getenv("MASTER_PROACTIVE", "true").lower() == "true"
        self.next_prompt_at = time.time() + 5
        self.topic_index = 0
        self.awaiting_event_id = ""
        self.awaiting_since = 0.0
        self.min_reply_seconds = max(10, int(os.getenv("MASTER_MIN_REPLY_SECONDS", "20")))
        self.mode = os.getenv("MASTER_MODE", "chat").lower()
        self.metrics_path = Path(os.getenv("MASTER_METRICS_PATH", "/data/master-metrics.json"))
        self.state_path = Path(os.getenv("MASTER_STATE_PATH", "/data/master-state.json"))
        self.last_event_id = ""
        self.last_reply_at = 0.0
        self.metrics = {"ticks": 0, "llm_requests": 0, "messages_sent": 0, "replies_received": 0, "api_errors": 0, "last_error": "", "last_latency_ms": 0, "last_reply_latency_ms": 0}
        self.load_state()

    def load_state(self) -> None:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.last_event_id = state.get("last_event_id", "")
            self.last_reply_at = float(state.get("last_reply_at", 0))
            self.metrics.update(state.get("metrics", {}))
            self.next_prompt_at = float(state.get("next_prompt_at", self.next_prompt_at))
            self.topic_index = int(state.get("topic_index", 0))
            self.awaiting_event_id = state.get("awaiting_event_id", "")
            self.awaiting_since = float(state.get("awaiting_since", 0))
            self.dialog_step = int(state.get("dialog_step", 0))
            self.dialog_source = state.get("dialog_source", "")
            self.dialog_target = state.get("dialog_target", "")
        except (FileNotFoundError, ValueError):
            pass

    def save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        state = {"last_event_id": self.last_event_id, "last_reply_at": self.last_reply_at, "metrics": self.metrics, "next_prompt_at": self.next_prompt_at, "topic_index": self.topic_index, "awaiting_event_id": self.awaiting_event_id, "awaiting_since": self.awaiting_since, "dialog_step": self.dialog_step, "dialog_source": self.dialog_source, "dialog_target": self.dialog_target}
        self.state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        self.metrics_path.write_text(json.dumps(self.metrics, ensure_ascii=False), encoding="utf-8")

    def agents(self) -> list[dict[str, Any]]:
        response = requests.get(f"{self.swarm_url}/v1/agents", timeout=30)
        response.raise_for_status()
        return response.json()

    def history(self) -> list[dict[str, Any]]:
        response = requests.get(f"{self.swarm_url}/v1/history", params={"room_id": self.room_id, "limit": 80}, timeout=30)
        response.raise_for_status()
        return response.json()

    def send(self, text: str) -> None:
        text = text.strip()
        if not text or "???" in text or len(text) > 4000:
            return
        response = requests.post(f"{self.swarm_url}/v1/rooms/{self.room_id}/messages", json={"text": text, "idempotency_key": f"master-llm:{uuid.uuid4().hex}"}, timeout=30)
        response.raise_for_status()
        self.metrics["messages_sent"] += 1
        self.last_reply_at = time.time()

    def complete(self, messages: list[dict[str, str]]) -> str:
        started = time.perf_counter()
        self.metrics["llm_requests"] += 1
        response = requests.post(f"{self.llm_url}/chat/completions", headers={"Authorization": f"Bearer {self.llm_key}", "Content-Type": "application/json"}, json={"model": self.model, "temperature": 0.7, "max_tokens": 500, "messages": messages}, timeout=90)
        response.raise_for_status()
        self.metrics["last_latency_ms"] = round((time.perf_counter() - started) * 1000)
        data = response.json()
        return str(data["choices"][0]["message"]["content"])

    def proactive_topics(self) -> list[str]:
        return [
            "проверка связи и задержки сообщений",
            "обработка входящих сообщений и приоритеты",
            "синхронизация контекста между агентами",
            "разбор ошибок API и восстановление после сбоя",
            "проверка UTF-8 и безопасной передачи текста",
            "структура проекта и распределение ролей",
            "проверка статусов heartbeat и доступности",
            "обсуждение интеграции WhatsApp без внешней отправки",
            "проверка адресных сообщений и исключение путаницы",
            "контроль истории и отсутствие дублей",
            "обмен вопросами между master и агентами",
            "нагрузка, частота сообщений и время ответа",
        ]

    def proactive_prompt(self, agents: list[dict[str, Any]]) -> str | None:
        active = [agent for agent in agents if agent["id"] != "master" and agent["status"] != "disabled"]
        if not active or not self.proactive_enabled:
            return None
        target = active[self.topic_index % len(active)]
        topic = self.proactive_topics()[self.topic_index % len(self.proactive_topics())]
        self.topic_index += 1
        if len(active) > 1 and self.topic_index % 3 == 0:
            other = active[(self.topic_index) % len(active)]
            self.dialog_step = 1
            self.dialog_source = target["name"]
            self.dialog_target = other["name"]
            return f"@{target['name']} Начни адресный диалог с @{other['name']}: напиши ему короткий вопрос по теме «{topic}» и попроси ответить в этой комнате. Не отвечай от его имени."
        return f"@{target['name']} Тема {self.topic_index}: {topic}. Ответь по фактам в 2–4 предложениях: что сейчас работает, какой риск или ограничение видишь и какой следующий безопасный шаг предложишь. Не создавай задачи, не меняй настройки и не выполняй внешние действия."

    def tick(self) -> None:
        self.metrics["ticks"] += 1
        events = self.history()
        agents = self.agents()
        now_value = time.time()
        if events:
            latest = events[-1]
            if latest["id"] != self.last_event_id:
                self.last_event_id = latest["id"]
                if self.awaiting_event_id and latest["sender_id"] != "master" and latest["type"] == "message.created":
                    wait_started = self.awaiting_since
                    self.awaiting_event_id = ""
                    self.awaiting_since = 0
                    self.metrics["replies_received"] = self.metrics.get("replies_received", 0) + 1
                    self.metrics["last_reply_latency_ms"] = round((now_value - wait_started) * 1000) if wait_started else 0
                    recent = []
                    for event in events[-20:]:
                        text = (event.get("payload") or {}).get("text")
                        if text:
                            recent.append({"role": "assistant" if event["sender_id"] == "master" else "user", "content": f"{event['sender_id']}: {text}"})
                    system = {"role": "system", "content": "Ты master-агент Swarm. Ответь агенту по контексту его последнего сообщения. Если он задал вопрос, дай конкретный короткий ответ. Только внутренний текстовый чат; не создавай задачи, комнаты или файлы, не вызывай WhatsApp и внешние действия, не меняй настройки."}
                    if self.dialog_step == 1:
                        self.dialog_step = 2
                        self.awaiting_event_id = latest["id"]
                        self.awaiting_since = now_value
                        self.send(f"@{self.dialog_target} Тебе написал @{self.dialog_source}. Ответь ему по существу в этой комнате, затем задай ему один короткий встречный вопрос. Не отвечай от имени другого агента.")
                    elif self.dialog_step == 2:
                        self.dialog_step = 0
                        self.dialog_source = ""
                        self.dialog_target = ""
                        answer = self.complete([system] + recent)
                        if answer:
                            self.send(answer)
                    else:
                        answer = self.complete([system] + recent)
                        if answer:
                            self.send(answer)
                    self.next_prompt_at = now_value + self.proactive_interval
        if now_value < self.next_prompt_at or self.awaiting_event_id:
            self.save_state()
            return
        prompt = self.proactive_prompt(agents)
        if prompt:
            before = self.metrics["messages_sent"]
            self.send(prompt)
            if self.metrics["messages_sent"] > before:
                self.awaiting_event_id = self.last_event_id
                self.awaiting_since = now_value
                self.next_prompt_at = now_value + self.proactive_interval
        self.save_state()

    def run(self) -> None:
        log.info("master started room=%s model=%s", self.room_id, self.model)
        while True:
            try:
                self.tick()
            except Exception as error:
                self.metrics["api_errors"] += 1
                self.metrics["last_error"] = str(error)[:500]
                self.save_state()
                log.warning("tick failed: %s", error)
            time.sleep(self.poll_seconds)

def run() -> None:
    Master().run()
