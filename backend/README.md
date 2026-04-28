# net·console — backend FastAPI + GUI statica

GUI scritta in **HTML + CSS + JavaScript vanilla** (cartella `static/`),
backend Python con **FastAPI + Paramiko** per le connessioni SSH.

## Avvio (tutto in uno)

```bash
cd backend
pip install fastapi "uvicorn[standard]" paramiko
uvicorn server:app --host 0.0.0.0 --port 8000
```

Poi apri nel browser: **http://localhost:8000**

Il server FastAPI serve sia le API (`/api/run`, `/api/health`) sia i file
statici della GUI (`static/index.html`, `static/style.css`, `static/app.js`).

## Solo GUI (senza backend Python)

Puoi anche aprire `static/index.html` direttamente nel browser
(doppio click). In quel caso devi indicare manualmente l'URL del backend
nella casella in alto a destra (es. `http://192.168.1.50:8000`).

## API

`POST /api/run` — body JSON:
```json
{
  "host": "192.168.1.10",
  "port": 22,
  "user": "admin",
  "password": "xxx",
  "device": "cisco",
  "commands": ["show version"],
  "no_host_key_check": true
}
```

`GET /api/health` — risponde `{"ok": true}`.

## Profili device supportati

`generic`, `cisco` (SB / SF300), `cisco_ios`, `mikrotik`.
