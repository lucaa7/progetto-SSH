"""
FastAPI wrapper attorno al client SSH/Telnet Netmiko.
Avvio:
    pip install fastapi uvicorn netmiko
    uvicorn backend.server:app --host localhost --port 8000

Espone:
    POST /api/run    -> esegue una lista di comandi su un dispositivo
    GET  /api/health -> ping
"""
from __future__ import annotations

import time
from typing import List, Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

# ─────────── Mappa device → netmiko device_type ───────────
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
    command: str
    output: str
    duration_ms: int
    error: Optional[str] = None


class RunRequest(BaseModel):
    host: str
    user: str
    password: Optional[str] = None
    port: int = 22
    device: str = Field("generic")
    commands: List[str]
    no_host_key_check: bool = True
    key_path: Optional[str] = None


class RunResponse(BaseModel):
    host: str
    device: str
    success: bool
    banner: Optional[str] = None
    results: List[CommandResult]
    error: Optional[str] = None


# ─────────── App ───────────
app = FastAPI(title="rConfig-lite SSH backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"ok": True, "devices": SUPPORTED_DEVICES}


@app.post("/api/run", response_model=RunResponse)
def run(req: RunRequest):
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

        return RunResponse(
            host=req.host, device=req.device,
            success=True, results=results,
        )

    except NetmikoAuthenticationException as exc:
        return RunResponse(host=req.host, device=req.device, success=False,
                           results=[], error=f"Auth failed: {exc}")
    except NetmikoTimeoutException as exc:
        return RunResponse(host=req.host, device=req.device, success=False,
                           results=[], error=f"Timeout: {exc}")
    except Exception as exc:
        return RunResponse(host=req.host, device=req.device, success=False,
                           results=[], error=f"Errore: {exc}")


# ─────────── Serve GUI statica ───────────
_STATIC_DIR = Path(__file__).resolve().parent.parent / "public" / "static"
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")