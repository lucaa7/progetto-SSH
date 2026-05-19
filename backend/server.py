"""
FastAPI + SQLModel backend per net·console.
Avvio:
    pip install fastapi uvicorn netmiko sqlmodel
    uvicorn backend.server:app --host localhost --port 8000
"""
from __future__ import annotations

import time
import json
from typing import List, Optional
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from sqlmodel import SQLModel, Field as SQLField, Session, create_engine, select, Column, JSON

from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

# ─────────── DB setup ───────────
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "netconsole.db"
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)


# ─────────── Modelli DB ───────────
class Device(SQLModel, table=True):
    id:           Optional[int] = SQLField(default=None, primary_key=True)
    name:         str
    host:         str
    port:         int = 22
    user:         str
    password:     Optional[str] = None
    device_type:  str = "generic"
    no_host_key:  bool = True


class Script(SQLModel, table=True):
    id:          Optional[int] = SQLField(default=None, primary_key=True)
    name:        str
    device_type: str = "generic"
    commands:    str  # JSON array salvato come stringa


class HistoryEntry(SQLModel, table=True):
    id:          Optional[int] = SQLField(default=None, primary_key=True)
    timestamp:   str  # ISO format
    host:        str
    user:        str
    device:      str
    success:     bool
    error:       Optional[str] = None
    results:     str  # JSON array salvato come stringa


def get_session():
    with Session(engine) as session:
        yield session


def create_db():
    SQLModel.metadata.create_all(engine)


# ─────────── Mappa device Netmiko ───────────
DEVICE_MAP = {
    ("mikrotik",  "ssh"):    "mikrotik_routeros",
    ("mikrotik",  "telnet"): "mikrotik_routeros",
    ("cisco",     "ssh"):    "cisco_s300",
    ("cisco",     "telnet"): "cisco_s300_telnet",
    ("cisco_ios", "ssh"):    "cisco_ios",
    ("cisco_ios", "telnet"): "cisco_ios_telnet",
    ("generic",   "ssh"):    "terminal_server",
    ("generic",   "telnet"): "generic_telnet",
}
SUPPORTED_DEVICES = list({k[0] for k in DEVICE_MAP.keys()})


# ─────────── Modelli API ───────────
class CommandResult(BaseModel):
    command:     str
    output:      str
    duration_ms: int
    error:       Optional[str] = None


class RunRequest(BaseModel):
    host:             str
    user:             str
    password:         Optional[str] = None
    port:             int = 22
    device:           str = Field("generic")
    commands:         List[str]
    no_host_key_check: bool = True
    key_path:         Optional[str] = None


class RunResponse(BaseModel):
    host:    str
    device:  str
    success: bool
    banner:  Optional[str] = None
    results: List[CommandResult]
    error:   Optional[str] = None


# Schemi API per Device
class DeviceCreate(BaseModel):
    name:        str
    host:        str
    port:        int = 22
    user:        str
    password:    Optional[str] = None
    device_type: str = "generic"
    no_host_key: bool = True


class DeviceRead(BaseModel):
    id:          int
    name:        str
    host:        str
    port:        int
    user:        str
    password:    Optional[str]
    device_type: str
    no_host_key: bool


# Schemi API per Script
class ScriptCreate(BaseModel):
    name:        str
    device_type: str = "generic"
    commands:    List[str]


class ScriptRead(BaseModel):
    id:          int
    name:        str
    device_type: str
    commands:    List[str]


# Schemi API per History
class HistoryRead(BaseModel):
    id:        int
    timestamp: str
    host:      str
    user:      str
    device:    str
    success:   bool
    error:     Optional[str]
    results:   List[CommandResult]


# ─────────── App ───────────
app = FastAPI(title="rConfig-lite SSH backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    create_db()


# ─────────── Health ───────────
@app.get("/api/health")
def health():
    return {"ok": True, "devices": SUPPORTED_DEVICES}


# ─────────── SSH Run ───────────
@app.post("/api/run", response_model=RunResponse)
def run(req: RunRequest, session: Session = Depends(get_session)):
    if req.device not in SUPPORTED_DEVICES:
        raise HTTPException(400, f"device must be one of {SUPPORTED_DEVICES}")

    proto = "ssh" if req.port == 22 else "telnet"
    device_type = DEVICE_MAP.get((req.device, proto), "terminal_server")

    conn_params = {
        "device_type": device_type,
        "host":        req.host,
        "username":    req.user,
        "password":    req.password or "",
    }
    if proto == "ssh":
        conn_params["port"] = req.port
    if req.no_host_key_check and proto == "ssh":
        conn_params["ssh_strict"] = False
    if req.key_path:
        conn_params["key_file"] = req.key_path

    results: List[CommandResult] = []
    success = False
    error = None

    try:
        with ConnectHandler(**conn_params) as conn:
            for cmd in req.commands:
                t0 = time.time()
                err = None
                out = ""
                try:
                    out = conn.send_command(cmd, read_timeout=120)
                except Exception as exc:
                    err = str(exc)
                results.append(CommandResult(
                    command=cmd,
                    output=out,
                    duration_ms=int((time.time() - t0) * 1000),
                    error=err,
                ))
        success = True

    except NetmikoAuthenticationException as exc:
        error = f"Auth failed: {exc}"
    except NetmikoTimeoutException as exc:
        error = f"Timeout: {exc}"
    except Exception as exc:
        error = f"Errore: {exc}"

    # Salva in history
    entry = HistoryEntry(
        timestamp=datetime.utcnow().isoformat(),
        host=req.host,
        user=req.user,
        device=req.device,
        success=success,
        error=error,
        results=json.dumps([r.dict() for r in results]),
    )
    session.add(entry)
    session.commit()

    return RunResponse(
        host=req.host, device=req.device,
        success=success, results=results, error=error,
    )


# ─────────── Device CRUD ───────────
@app.get("/api/devices", response_model=List[DeviceRead])
def list_devices(session: Session = Depends(get_session)):
    return session.exec(select(Device)).all()


@app.post("/api/devices", response_model=DeviceRead)
def create_device(data: DeviceCreate, session: Session = Depends(get_session)):
    dev = Device(**data.dict())
    session.add(dev)
    session.commit()
    session.refresh(dev)
    return dev


@app.delete("/api/devices/{device_id}")
def delete_device(device_id: int, session: Session = Depends(get_session)):
    dev = session.get(Device, device_id)
    if not dev:
        raise HTTPException(404, "Device non trovato")
    session.delete(dev)
    session.commit()
    return {"ok": True}


# ─────────── Script CRUD ───────────
@app.get("/api/scripts", response_model=List[ScriptRead])
def list_scripts(session: Session = Depends(get_session)):
    scripts = session.exec(select(Script)).all()
    return [
        ScriptRead(
            id=s.id, name=s.name, device_type=s.device_type,
            commands=json.loads(s.commands),
        )
        for s in scripts
    ]


@app.post("/api/scripts", response_model=ScriptRead)
def create_script(data: ScriptCreate, session: Session = Depends(get_session)):
    s = Script(name=data.name, device_type=data.device_type,
               commands=json.dumps(data.commands))
    session.add(s)
    session.commit()
    session.refresh(s)
    return ScriptRead(id=s.id, name=s.name, device_type=s.device_type,
                      commands=json.loads(s.commands))


@app.delete("/api/scripts/{script_id}")
def delete_script(script_id: int, session: Session = Depends(get_session)):
    s = session.get(Script, script_id)
    if not s:
        raise HTTPException(404, "Script non trovato")
    session.delete(s)
    session.commit()
    return {"ok": True}


# ─────────── History ───────────
@app.get("/api/history", response_model=List[HistoryRead])
def list_history(session: Session = Depends(get_session)):
    entries = session.exec(select(HistoryEntry).order_by(HistoryEntry.id.desc()).limit(100)).all()
    return [
        HistoryRead(
            id=e.id, timestamp=e.timestamp, host=e.host,
            user=e.user, device=e.device, success=e.success,
            error=e.error, results=json.loads(e.results),
        )
        for e in entries
    ]


@app.delete("/api/history")
def clear_history(session: Session = Depends(get_session)):
    entries = session.exec(select(HistoryEntry)).all()
    for e in entries:
        session.delete(e)
    session.commit()
    return {"ok": True}


# ─────────── Static files ───────────
_STATIC_DIR = Path(__file__).resolve().parent.parent / "public" / "static"
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")