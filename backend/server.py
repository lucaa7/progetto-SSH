"""
FastAPI wrapper attorno al client SSH Paramiko.
Avvio:
    pip install fastapi uvicorn paramiko
    uvicorn backend.server:app --host localhost --port 8000

Espone:
    POST /api/run    -> esegue una lista di comandi su un dispositivo
    GET  /api/health -> ping
"""
from __future__ import annotations

import io
import socket
import sys
import time
import re
from contextlib import redirect_stdout, redirect_stderr
from typing import List, Optional

import paramiko
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from ssh.Devices import DEVICE_PROFILES
from ssh.client import ANSI_ESCAPE, read_until_prompt, send_command_shell, send_command_exec


# ─────────── API ───────────
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


app = FastAPI(title="rConfig-lite SSH backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # in LAN va bene; restringi in produzione
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"ok": True, "profiles": list(DEVICE_PROFILES.keys())}


@app.post("/api/run", response_model=RunResponse)
def run(req: RunRequest):
    if req.device not in DEVICE_PROFILES:
        raise HTTPException(400, f"device must be one of {list(DEVICE_PROFILES)}")

    profile = DEVICE_PROFILES[req.device]
    prompt_endings = profile["prompt_endings"]
    use_shell = profile["use_shell"]
    term = profile["term"]
    paging_cmd = profile["disable_paging_cmd"]

    client = paramiko.SSHClient()
    if req.no_host_key_check:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        client.load_system_host_keys()

    connect_kwargs = {
        "hostname": req.host,
        "port": req.port,
        "username": req.user,
        "timeout": 15,
        "disabled_algorithms": {"pubkeys": ["rsa-sha2-256", "rsa-sha2-512"]},
        "look_for_keys": False,
        "allow_agent": False,
    }
    if req.password:
        connect_kwargs["password"] = req.password
    if req.key_path:
        connect_kwargs["key_filename"] = req.key_path

    banner_text = None
    results: List[CommandResult] = []

    try:
        client.connect(**connect_kwargs)
        channel = None
        if use_shell:
            channel = client.invoke_shell(term=term, width=200, height=50)
            channel.set_combine_stderr(True)
            banner_text = read_until_prompt(channel, prompt_endings, timeout=20).strip() or None
            if paging_cmd:
                send_command_shell(channel, paging_cmd, prompt_endings, timeout=10)

        for cmd in req.commands:
            t0 = time.time()
            err = None
            try:
                if use_shell:
                    out = send_command_shell(channel, cmd, prompt_endings, timeout=120)
                else:
                    out = send_command_exec(client, cmd, timeout=120)
            except Exception as exc:
                out = ""
                err = str(exc)
            results.append(CommandResult(
                command=cmd, output=out,
                duration_ms=int((time.time() - t0) * 1000),
                error=err,
            ))

        if channel:
            channel.close()

        return RunResponse(host=req.host, device=req.device, success=True,
                           banner=banner_text, results=results)

    except paramiko.AuthenticationException as exc:
        return RunResponse(host=req.host, device=req.device, success=False,
                           results=[], error=f"Auth failed: {exc}")
    except paramiko.SSHException as exc:
        return RunResponse(host=req.host, device=req.device, success=False,
                           results=[], error=f"SSH error: {exc}")
    except socket.timeout:
        return RunResponse(host=req.host, device=req.device, success=False,
                           results=[], error=f"Timeout connecting to {req.host}:{req.port}")
    except Exception as exc:
        return RunResponse(host=req.host, device=req.device, success=False,
                           results=[], error=f"Generic error: {exc}")
    finally:
        client.close()


# ─────────── Servire la GUI statica (HTML/CSS/JS) ───────────
# I file in ../static (index.html, style.css, app.js) sono serviti su /
from pathlib import Path
from fastapi.staticfiles import StaticFiles

_STATIC_DIR = Path(__file__).resolve().parent.parent / "public" / "static"
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
