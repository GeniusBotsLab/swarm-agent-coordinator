from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import nats
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./swarm.db"
    master_api_key: str = "change-me"
    cors_origins: str = "http://localhost:8000"
    agent_only: bool = False
    attachment_dir: str = "/data/attachments"
    max_attachment_bytes: int = 20 * 1024 * 1024


settings = Settings()
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(40))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    ip_allowlist: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    members: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(20))
    members: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    type: Mapped[str] = mapped_column(String(60))
    room_id: Mapped[str | None] = mapped_column(ForeignKey("rooms.id"), nullable=True, index=True)
    sender_id: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    correlation_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(250))
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    created_by: Mapped[str] = mapped_column(String(40))
    assigned_to: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    room_id: Mapped[str] = mapped_column(String(80), index=True)
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    sender_id: Mapped[str] = mapped_column(String(40))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)
    disk_name: Mapped[str] = mapped_column(String(80), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class AgentRegistration(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(pattern="^(cursor|zennoposter|service)$")
    capabilities: list[str] = Field(default_factory=list)
    ip_allowlist: list[str] = Field(default_factory=list)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    members: list[str] = Field(default_factory=list)


class RoomCreate(BaseModel):
    project_id: str
    name: str
    type: str = Field(pattern="^(project|task|broadcast|control|direct)$")
    members: list[str] = Field(default_factory=list)


class Envelope(BaseModel):
    event_type: str = "message.created"
    room_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None
    idempotency_key: str | None = None


class TaskCreate(BaseModel):
    project_id: str
    title: str
    input: dict[str, Any] = Field(default_factory=dict)
    assigned_to: str | None = None

    @field_validator("title")
    @classmethod
    def reject_corrupted_title(cls, value: str) -> str:
        if "???" in value:
            raise ValueError("task title is corrupted; send JSON as UTF-8")
        return value


class TaskUpdate(BaseModel):
    status: str = Field(pattern="^(accepted|running|succeeded|failed|cancelled)$")
    result: dict[str, Any] | None = None
    error: str | None = None


app = FastAPI(title="Swarm Agent API" if settings.agent_only else "Swarm Control", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.cors_origins.split(",")], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
nats_client = None


@app.middleware("http")
async def ingress_scope(request: Request, call_next):
    if settings.agent_only and not request.url.path.startswith("/agent/") and request.url.path != "/health":
        return Response(status_code=404)
    return await call_next(request)


def db_session():
    with SessionLocal() as db:
        yield db


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def hash_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def master_guard(x_master_key: str = Header(default="")) -> None:
    if not settings.agent_only:
        return
    if not secrets.compare_digest(x_master_key, settings.master_api_key):
        raise HTTPException(401, "master authorization required")


def agent_guard(x_agent_key: str = Header(default=""), db: Session = Depends(db_session)) -> Agent:
    agent = db.scalar(select(Agent).where(Agent.key_hash == hash_key(x_agent_key)))
    if not agent or agent.status != "online":
        raise HTTPException(401, "invalid or inactive agent credential")
    return agent


def project_for_agent(db: Session, project_id: str, agent_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project or agent_id not in project.members:
        raise HTTPException(403, "project access denied")
    return project


def room_for_agent(db: Session, room_id: str, agent_id: str) -> Room:
    room = db.get(Room, room_id)
    if not room or agent_id not in room.members or not room.project_id:
        raise HTTPException(403, "room access denied")
    project_for_agent(db, room.project_id, agent_id)
    return room


def audit(db: Session, event_type: str, sender_id: str, payload: dict[str, Any], room_id: str | None = None, target_id: str | None = None, correlation_id: str | None = None, idempotency_key: str | None = None) -> Event:
    if idempotency_key:
        existing = db.scalar(select(Event).where(Event.idempotency_key == idempotency_key))
        if existing:
            return existing
    event = Event(id=new_id("evt"), type=event_type, sender_id=sender_id, room_id=room_id, target_id=target_id, payload=payload, correlation_id=correlation_id, idempotency_key=idempotency_key)
    db.add(event)
    return event


async def publish(event: Event) -> None:
    if nats_client:
        await nats_client.publish(f"swarm.events.{event.type}", json.dumps({"event_id": event.id, "room_id": event.room_id, "sender_id": event.sender_id}).encode())


@app.on_event("startup")
async def startup() -> None:
    global nats_client
    try:
        nats_client = await nats.connect(os.getenv("NATS_URL", "nats://nats:4222"), connect_timeout=2, max_reconnect_attempts=-1)
    except Exception:
        nats_client = None
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for statement in ("ALTER TABLE rooms ADD COLUMN IF NOT EXISTS project_id VARCHAR(40)", "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS project_id VARCHAR(40)"):
            try:
                connection.execute(text(statement))
            except Exception:
                pass
    Path(settings.attachment_dir).mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        if not db.get(Agent, "master"):
            db.add(Agent(id="master", name="Global Master", kind="master", key_hash=hash_key(settings.master_api_key), capabilities=["swarm.manage"], status="online"))
            db.commit()


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(Path("static/index.html"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "agent-api" if settings.agent_only else "control", "nats": "connected" if nats_client else "unavailable"}


@app.post("/v1/agents/register", dependencies=[Depends(master_guard)])
def register_agent(data: AgentRegistration, db: Session = Depends(db_session)) -> dict[str, Any]:
    key = secrets.token_urlsafe(32)
    agent = Agent(id=new_id("agt"), name=data.name, kind=data.kind, key_hash=hash_key(key), capabilities=data.capabilities, ip_allowlist=data.ip_allowlist)
    db.add(agent)
    audit(db, "agent.registered", "master", {"agent_id": agent.id, "ip_allowlist": agent.ip_allowlist})
    db.commit()
    return {"agent_id": agent.id, "api_key": key, "status": "pending", "agent_api": "http://MASTER_IP:8443/agent"}


@app.get("/v1/agents", dependencies=[Depends(master_guard)])
def list_agents(db: Session = Depends(db_session)) -> list[dict[str, Any]]:
    return [{"id": a.id, "name": a.name, "kind": a.kind, "capabilities": a.capabilities, "ip_allowlist": a.ip_allowlist, "status": a.status, "last_seen_at": a.last_seen_at} for a in db.scalars(select(Agent).order_by(Agent.created_at.desc()))]


@app.post("/v1/agents/{agent_id}/approve", dependencies=[Depends(master_guard)])
def approve_agent(agent_id: str, db: Session = Depends(db_session)) -> dict[str, str]:
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "agent not found")
    agent.status = "online"
    audit(db, "agent.approved", "master", {"agent_id": agent_id})
    db.commit()
    return {"agent_id": agent_id, "status": agent.status}




@app.post("/v1/agents/{agent_id}/rotate-key", dependencies=[Depends(master_guard)])
def rotate_agent_key(agent_id: str, db: Session = Depends(db_session)) -> dict[str, str]:
    agent = db.get(Agent, agent_id)
    if not agent or agent.id == "master":
        raise HTTPException(404, "agent not found")
    key = secrets.token_urlsafe(32)
    agent.key_hash = hash_key(key)
    audit(db, "agent.key.rotated", "master", {"agent_id": agent_id})
    db.commit()
    return {"agent_id": agent.id, "api_key": key}

@app.post("/v1/agents/{agent_id}/disable", dependencies=[Depends(master_guard)])
def disable_agent(agent_id: str, db: Session = Depends(db_session)) -> dict[str, str]:
    agent = db.get(Agent, agent_id)
    if not agent or agent.id == "master":
        raise HTTPException(404, "agent not found")
    agent.status = "disabled"
    audit(db, "agent.disabled", "master", {"agent_id": agent_id})
    db.commit()
    return {"agent_id": agent_id, "status": agent.status}


@app.delete("/v1/agents/{agent_id}", dependencies=[Depends(master_guard)])
def delete_agent(agent_id: str, db: Session = Depends(db_session)) -> dict[str, str]:
    agent = db.get(Agent, agent_id)
    if not agent or agent.id == "master":
        raise HTTPException(404, "agent not found")
    if db.scalar(select(Task).where(Task.assigned_to == agent_id, Task.status.in_(["assigned", "running"]))):
        raise HTTPException(409, "agent has active tasks")
    for project in db.scalars(select(Project)).all():
        if agent_id in project.members:
            project.members = [member for member in project.members if member != agent_id]
    for room in db.scalars(select(Room)).all():
        if agent_id in room.members:
            room.members = [member for member in room.members if member != agent_id]
    db.delete(agent)
    db.commit()
    return {"deleted": agent_id}

@app.post("/v1/projects", dependencies=[Depends(master_guard)])
def create_project(data: ProjectCreate, db: Session = Depends(db_session)) -> dict[str, Any]:
    members = list(set(data.members + ["master"]))
    if any(not db.get(Agent, member) for member in members):
        raise HTTPException(422, "unknown project member")
    project = Project(id=new_id("prj"), name=data.name, members=members)
    db.add(project)
    audit(db, "project.created", "master", {"project_id": project.id, "members": members})
    db.commit()
    return {"id": project.id, "name": project.name, "members": members}


@app.get("/v1/projects", dependencies=[Depends(master_guard)])
def list_projects(db: Session = Depends(db_session)) -> list[dict[str, Any]]:
    return [{"id": p.id, "name": p.name, "members": p.members} for p in db.scalars(select(Project).order_by(Project.created_at.desc()))]



@app.delete("/v1/projects/{project_id}", dependencies=[Depends(master_guard)])
def delete_project(project_id: str, db: Session = Depends(db_session)) -> dict[str, str]:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    if db.scalar(select(Task).where(Task.project_id == project_id, Task.status.in_(["assigned", "running"]))):
        raise HTTPException(409, "project has active tasks")
    room_ids = [room.id for room in db.scalars(select(Room).where(Room.project_id == project_id)).all()]
    if room_ids:
        for attachment in db.scalars(select(Attachment).where(Attachment.room_id.in_(room_ids))).all():
            (Path(settings.attachment_dir) / attachment.disk_name).unlink(missing_ok=True)
            db.delete(attachment)
        db.execute(Event.__table__.delete().where(Event.room_id.in_(room_ids)))
        db.execute(Room.__table__.delete().where(Room.id.in_(room_ids)))
    db.execute(Task.__table__.delete().where(Task.project_id == project_id))
    db.delete(project)
    db.commit()
    return {"deleted": project_id}


class MembersUpdate(BaseModel):
    members: list[str] = Field(default_factory=list)


@app.put("/v1/projects/{project_id}/members", dependencies=[Depends(master_guard)])
def update_project_members(project_id: str, data: MembersUpdate, db: Session = Depends(db_session)) -> dict[str, Any]:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    members = list(set(data.members + ["master"]))
    if any(not db.get(Agent, member) for member in members):
        raise HTTPException(422, "unknown agent")
    project.members = members
    for room in db.scalars(select(Room).where(Room.project_id == project_id)).all():
        room.members = [member for member in room.members if member in members]
    audit(db, "project.members.updated", "master", {"project_id": project_id, "members": members})
    db.commit()
    return {"id": project.id, "members": project.members}


@app.put("/v1/rooms/{room_id}/members", dependencies=[Depends(master_guard)])
def update_room_members(room_id: str, data: MembersUpdate, db: Session = Depends(db_session)) -> dict[str, Any]:
    room = db.get(Room, room_id)
    if not room or not room.project_id:
        raise HTTPException(404, "room not found")
    project = db.get(Project, room.project_id)
    members = list(set(data.members + ["master"]))
    if any(member not in project.members for member in members):
        raise HTTPException(403, "room members must belong to project")
    room.members = members
    audit(db, "room.members.updated", "master", {"room_id": room.id, "members": members}, room.id)
    db.commit()
    return {"id": room.id, "members": room.members}

@app.post("/v1/rooms", dependencies=[Depends(master_guard)])
def create_room(data: RoomCreate, db: Session = Depends(db_session)) -> dict[str, Any]:
    project = db.get(Project, data.project_id)
    if not project:
        raise HTTPException(404, "project not found")
    members = list(set(data.members + ["master"]))
    if any(member not in project.members for member in members):
        raise HTTPException(403, "all room members must belong to project")
    room = Room(id=new_id("room"), project_id=project.id, name=data.name, type=data.type, members=members)
    db.add(room)
    db.flush()
    audit(db, "room.created", "master", {"project_id": project.id, "members": members}, room.id)
    db.commit()
    return {"id": room.id, "project_id": room.project_id, "name": room.name, "members": room.members}


@app.get("/v1/rooms", dependencies=[Depends(master_guard)])
def list_rooms(db: Session = Depends(db_session)) -> list[dict[str, Any]]:
    return [{"id": r.id, "project_id": r.project_id, "name": r.name, "type": r.type, "members": r.members} for r in db.scalars(select(Room).order_by(Room.created_at.desc()))]


@app.post("/v1/direct/{agent_id}", dependencies=[Depends(master_guard)])
def create_direct_room(agent_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    agent = db.get(Agent, agent_id)
    if not agent or agent_id == "master":
        raise HTTPException(404, "agent not found")
    project = next((item for item in db.scalars(select(Project)).all() if agent_id in item.members and "master" in item.members), None)
    if not project:
        raise HTTPException(403, "agent has no common project with master")
    members = ["master", agent_id]
    existing = next((room for room in db.scalars(select(Room)).all() if room.type == "direct" and room.project_id == project.id and set(room.members) == set(members)), None)
    if existing:
        return {"id": existing.id, "project_id": existing.project_id, "name": existing.name, "type": existing.type, "members": existing.members}
    room = Room(id=new_id("room"), project_id=project.id, name=f"Личный чат: {agent.name}", type="direct", members=members)
    db.add(room)
    db.flush()
    audit(db, "room.created", "master", {"project_id": project.id, "members": members, "direct_agent_id": agent_id}, room.id)
    db.commit()
    return {"id": room.id, "project_id": room.project_id, "name": room.name, "type": room.type, "members": room.members}



@app.delete("/v1/rooms/{room_id}", dependencies=[Depends(master_guard)])
def delete_room(room_id: str, db: Session = Depends(db_session)) -> dict[str, str]:
    room = db.get(Room, room_id)
    if not room:
        raise HTTPException(404, "room not found")
    for attachment in db.scalars(select(Attachment).where(Attachment.room_id == room_id)).all():
        (Path(settings.attachment_dir) / attachment.disk_name).unlink(missing_ok=True)
        db.delete(attachment)
    db.execute(Event.__table__.delete().where(Event.room_id == room_id))
    db.delete(room)
    db.commit()
    return {"deleted": room_id}

@app.post("/v1/tasks", dependencies=[Depends(master_guard)])
async def create_task(data: TaskCreate, db: Session = Depends(db_session)) -> dict[str, Any]:
    project = db.get(Project, data.project_id)
    if not project:
        raise HTTPException(404, "project not found")
    if data.assigned_to and data.assigned_to not in project.members:
        raise HTTPException(403, "assignee outside project")
    task = Task(id=new_id("tsk"), project_id=project.id, title=data.title, input=data.input, created_by="master", assigned_to=data.assigned_to, status="assigned" if data.assigned_to else "queued")
    room = Room(id=f"task_{task.id}", project_id=project.id, name=task.title, type="task", members=["master"] + ([data.assigned_to] if data.assigned_to else []))
    db.add_all([task, room])
    db.flush()
    event = audit(db, "task.assigned" if data.assigned_to else "task.queued", "master", {"task_id": task.id, "project_id": project.id, "title": task.title, "input": task.input}, room.id, data.assigned_to, idempotency_key=f"task:create:{task.id}")
    db.commit()
    await publish(event)
    return {"id": task.id, "project_id": project.id, "status": task.status, "room_id": room.id}



@app.delete("/v1/tasks/{task_id}", dependencies=[Depends(master_guard)])
def delete_task(task_id: str, db: Session = Depends(db_session)) -> dict[str, str]:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "task not found")
    db.execute(Event.__table__.delete().where(Event.room_id == f"task_{task_id}"))
    db.execute(Room.__table__.delete().where(Room.id == f"task_{task_id}"))
    db.delete(task)
    db.commit()
    return {"deleted": task_id}

@app.get("/v1/tasks", dependencies=[Depends(master_guard)])
def list_tasks(db: Session = Depends(db_session)) -> list[dict[str, Any]]:
    return [{"id": t.id, "project_id": t.project_id, "title": t.title, "status": t.status, "assigned_to": t.assigned_to, "updated_at": t.updated_at} for t in db.scalars(select(Task).order_by(Task.updated_at.desc()))]



class MasterMessage(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    idempotency_key: str | None = None


@app.post("/v1/rooms/{room_id}/attachments", dependencies=[Depends(master_guard)])
def master_upload_attachment(room_id: str, file: UploadFile = File(...), db: Session = Depends(db_session)) -> dict[str, Any]:
    room = db.get(Room, room_id)
    if not room or not room.project_id:
        raise HTTPException(404, "room not found")
    filename = Path(file.filename or "file").name
    disk_name = new_id("att")
    target = Path(settings.attachment_dir) / disk_name
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with target.open("wb") as output:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_attachment_bytes:
                output.close()
                target.unlink(missing_ok=True)
                raise HTTPException(413, "attachment too large")
            output.write(chunk)
    attachment = Attachment(id=new_id("att"), room_id=room.id, project_id=room.project_id, sender_id="master", filename=filename, content_type=file.content_type or "application/octet-stream", size=size, disk_name=disk_name)
    db.add(attachment)
    event = audit(db, "attachment.created", "master", {"attachment_id": attachment.id, "filename": filename, "size": size}, room.id)
    db.commit()
    return {"attachment_id": attachment.id, "filename": filename, "size": size, "event_id": event.id}


@app.post("/v1/rooms/{room_id}/messages", dependencies=[Depends(master_guard)])
async def master_message(room_id: str, data: MasterMessage, db: Session = Depends(db_session)) -> dict[str, str]:
    room = db.get(Room, room_id)
    if not room:
        raise HTTPException(404, "room not found")
    event = audit(db, "message.created", "master", {"text": data.text}, room.id, idempotency_key=data.idempotency_key or f"master:{room.id}:{uuid.uuid4().hex}")
    db.commit()
    await publish(event)
    return {"event_id": event.id}

@app.get("/v1/history", dependencies=[Depends(master_guard)])
def admin_history(room_id: str, limit: int = Query(default=100, le=500), db: Session = Depends(db_session)) -> list[dict[str, Any]]:
    return event_list(db, room_id, limit)


def event_list(db: Session, room_id: str, limit: int) -> list[dict[str, Any]]:
    events = db.scalars(select(Event).where(Event.room_id == room_id).order_by(Event.created_at.desc()).limit(limit)).all()
    return [{"id": e.id, "type": e.type, "sender_id": e.sender_id, "payload": e.payload, "created_at": e.created_at.isoformat()} for e in reversed(events)]



@app.get("/agent/bootstrap")
def agent_bootstrap(agent: Agent = Depends(agent_guard), db: Session = Depends(db_session)) -> dict[str, Any]:
    projects = [project for project in db.scalars(select(Project)).all() if agent.id in project.members]
    rooms = [room for room in db.scalars(select(Room)).all() if agent.id in room.members and room.project_id]
    known_agents = {item.id: {"agent_id": item.id, "name": item.name, "kind": item.kind, "status": item.status} for item in db.scalars(select(Agent)).all()}
    return {"protocol_version": 1, "agent": known_agents[agent.id], "projects": [{"id": project.id, "name": project.name, "members": [known_agents[member] for member in project.members if member in known_agents]} for project in projects], "rooms": [{"id": room.id, "project_id": room.project_id, "name": room.name, "type": room.type, "members": [known_agents[member] for member in room.members if member in known_agents]} for room in rooms], "policy": {"tasks_require_ack": True, "unknown_fields": "ignore"}}

@app.post("/agent/heartbeat")
def agent_heartbeat(agent: Agent = Depends(agent_guard), db: Session = Depends(db_session)) -> dict[str, Any]:
    agent.last_seen_at = now()
    db.commit()
    projects = [p.id for p in db.scalars(select(Project)) if agent.id in p.members]
    return {"agent_id": agent.id, "status": agent.status, "projects": projects, "lease_seconds": 60}


@app.get("/agent/rooms")
def agent_rooms(agent: Agent = Depends(agent_guard), db: Session = Depends(db_session)) -> list[dict[str, Any]]:
    return [{"id": r.id, "project_id": r.project_id, "name": r.name, "type": r.type} for r in db.scalars(select(Room)) if agent.id in r.members and r.project_id]


@app.get("/agent/history/{room_id}")
def agent_history(room_id: str, limit: int = Query(default=100, le=500), agent: Agent = Depends(agent_guard), db: Session = Depends(db_session)) -> list[dict[str, Any]]:
    room_for_agent(db, room_id, agent.id)
    return event_list(db, room_id, limit)


@app.post("/agent/messages")
async def agent_message(data: Envelope, agent: Agent = Depends(agent_guard), db: Session = Depends(db_session)) -> dict[str, str]:
    room = room_for_agent(db, data.room_id, agent.id)
    event = audit(db, data.event_type, agent.id, data.payload, room.id, correlation_id=data.correlation_id, idempotency_key=data.idempotency_key)
    agent.last_seen_at = now()
    db.commit()
    await publish(event)
    return {"event_id": event.id}


@app.get("/agent/inbox")
def agent_inbox(agent: Agent = Depends(agent_guard), db: Session = Depends(db_session)) -> list[dict[str, Any]]:
    tasks = db.scalars(select(Task).where(Task.assigned_to == agent.id, Task.status.in_(["assigned", "queued"]))).all()
    return [{"task_id": t.id, "project_id": t.project_id, "title": t.title, "input": t.input, "status": t.status} for t in tasks if t.project_id and agent.id in db.get(Project, t.project_id).members]


@app.post("/agent/tasks/{task_id}")
async def agent_task_update(task_id: str, data: TaskUpdate, agent: Agent = Depends(agent_guard), db: Session = Depends(db_session)) -> dict[str, str]:
    task = db.get(Task, task_id)
    if not task or task.assigned_to != agent.id or not task.project_id:
        raise HTTPException(403, "task access denied")
    project_for_agent(db, task.project_id, agent.id)
    task.status, task.result, task.error = data.status, data.result, data.error
    event = audit(db, f"task.{data.status}", agent.id, {"task_id": task.id, "result": data.result, "error": data.error}, f"task_{task.id}", "master")
    db.commit()
    await publish(event)
    return {"task_id": task.id, "status": task.status}


@app.post("/agent/attachments")
def upload_attachment(room_id: str, file: UploadFile = File(...), agent: Agent = Depends(agent_guard), db: Session = Depends(db_session)) -> dict[str, Any]:
    room = room_for_agent(db, room_id, agent.id)
    filename = Path(file.filename or "file").name
    disk_name = new_id("att")
    target = Path(settings.attachment_dir) / disk_name
    size = 0
    with target.open("wb") as output:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_attachment_bytes:
                output.close()
                target.unlink(missing_ok=True)
                raise HTTPException(413, "attachment too large")
            output.write(chunk)
    attachment = Attachment(id=new_id("att"), room_id=room.id, project_id=room.project_id, sender_id=agent.id, filename=filename, content_type=file.content_type or "application/octet-stream", size=size, disk_name=disk_name)
    db.add(attachment)
    audit(db, "attachment.created", agent.id, {"attachment_id": attachment.id, "filename": filename, "size": size}, room.id)
    db.commit()
    return {"attachment_id": attachment.id, "filename": filename, "size": size}


@app.get("/agent/attachments/{attachment_id}")
def download_attachment(attachment_id: str, agent: Agent = Depends(agent_guard), db: Session = Depends(db_session)) -> FileResponse:
    attachment = db.get(Attachment, attachment_id)
    if not attachment:
        raise HTTPException(404, "attachment not found")
    room_for_agent(db, attachment.room_id, agent.id)
    return FileResponse(Path(settings.attachment_dir) / attachment.disk_name, filename=attachment.filename, media_type=attachment.content_type)
