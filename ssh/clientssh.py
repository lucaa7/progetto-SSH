import argparse
import sys
import time
import socket
import re
from typing import Optional, List

import paramiko


# ──────────────────────────────────────────────
# Profili per tipo di dispositivo
# ──────────────────────────────────────────────
DEVICE_PROFILES = {
    "cisco": {
        "prompt_endings": ("#", ">"),
        "disable_paging_cmd": "terminal datadump",  # Cisco SB (SF300 ecc.)
        "use_shell": True,
        "term": "vt100",
    },
    "cisco_ios": {
        "prompt_endings": ("#", ">"),
        "disable_paging_cmd": "terminal length 0",  # Cisco IOS standard
        "use_shell": True,
        "term": "vt100",
    },
    "mikrotik": {
        "prompt_endings": ("] > ", "] >"),
        # MikroTik: usa exec_command, niente shell interattiva
        "use_shell": False,
        "term": None,
        "disable_paging_cmd": None,
    },
    "generic": {
        "prompt_endings": ("#", ">", "$"),
        "disable_paging_cmd": None,
        "use_shell": True,
        "term": "vt100",
    },
}

# Regex per rimuovere ANSI escape codes
ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


# ──────────────────────────────────────────────
# Lettura output SSH (shell interattiva)
# ──────────────────────────────────────────────
def read_until_prompt(
    channel: paramiko.Channel,
    prompt_endings: tuple = ("#", ">"),
    timeout: float = 60.0,
    chunk_delay: float = 0.3,
) -> str:
    output = ""
    channel.settimeout(timeout)
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            if channel.recv_ready():
                chunk = channel.recv(4096).decode("utf-8", errors="replace")
                output += chunk
                deadline = time.time() + timeout
            else:
                if channel.exit_status_ready():
                    break
                stripped = output.rstrip()
                if any(stripped.endswith(p) for p in prompt_endings):
                    break
                time.sleep(chunk_delay)
        except socket.timeout:
            stripped = output.rstrip()
            if any(stripped.endswith(p) for p in prompt_endings):
                break
            continue
        except Exception:
            break

    return output


def send_command_shell(
    channel: paramiko.Channel,
    command: str,
    prompt_endings: tuple = ("#", ">"),
    timeout: float = 60.0,
) -> str:
    """Invia comando su shell interattiva (Cisco/generic)."""
    channel.send(command + "\n")
    time.sleep(0.5)
    raw = read_until_prompt(channel, prompt_endings=prompt_endings, timeout=timeout)

    lines = raw.splitlines()
    cmd = command.strip()

    # Rimuovi eco del comando (anche progressivo tipo e, ex, exp...)
    while lines and lines[0].strip() and cmd.startswith(lines[0].strip()):
        lines = lines[1:]

    # Rimuovi ultima riga se è il prompt
    if lines and any(lines[-1].rstrip().endswith(p) for p in prompt_endings):
        lines = lines[:-1]

    return "\n".join(lines)


def send_command_exec(
    client: paramiko.SSHClient,
    command: str,
    timeout: float = 60.0,
) -> str:
    """
    Esegue comando con exec_command (MikroTik).
    Niente PTY, niente echo, output pulito.
    """
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    stdout.channel.set_combine_stderr(True)

    output_lines = []
    for line in stdout:
        # Rimuovi ANSI escape codes residui
        clean = ANSI_ESCAPE.sub("", line).rstrip("\r\n")
        output_lines.append(clean)

    return "\n".join(output_lines)


# ──────────────────────────────────────────────
# Client principale
# ──────────────────────────────────────────────
def run_client(
    host: str,
    user: str,
    password: Optional[str],
    port: int,
    cmds: Optional[List[str]],
    keys: Optional[List[str]],
    no_host_key_check: bool,
    device: Optional[str],
) -> None:

    profile        = DEVICE_PROFILES.get(device or "generic", DEVICE_PROFILES["generic"])
    prompt_endings = profile["prompt_endings"]
    use_shell      = profile["use_shell"]
    term           = profile["term"]
    paging_cmd     = profile["disable_paging_cmd"]

    client = paramiko.SSHClient()
    if no_host_key_check:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        client.load_system_host_keys()

    connect_kwargs = {
        "hostname": host,
        "port": port,
        "username": user,
        "timeout": 15,
        "disabled_algorithms": {"pubkeys": ["rsa-sha2-256", "rsa-sha2-512"]},
        "look_for_keys": False,
        "allow_agent": False,
    }
    if password:
        connect_kwargs["password"] = password
    if keys:
        connect_kwargs["key_filename"] = keys[0]

    try:
        print(f"Connessione a {host}:{port} (device: {device or 'generic'})...")
        client.connect(**connect_kwargs)
        print(f"Connessione stabilita con {host}!\n")

        channel = None

        if use_shell:
            # Shell interattiva con PTY — Cisco/SF300/generic
            channel = client.invoke_shell(term=term, width=200, height=50)
            channel.set_combine_stderr(True)

            print("Attesa prompt iniziale...")
            banner = read_until_prompt(channel, prompt_endings=prompt_endings, timeout=20)
            if banner.strip():
                print(f"[Prompt iniziale]\n{banner.strip()}\n")

            if paging_cmd:
                print(f"Disabilitazione paging ({paging_cmd})...")
                _ = send_command_shell(channel, paging_cmd,
                                       prompt_endings=prompt_endings, timeout=10)

        if cmds:
            if isinstance(cmds, str):
                cmds = [cmds]
            for cmd in cmds:
                print(f"{'='*60}")
                print(f"Comando: {cmd}")
                print(f"{'='*60}")
                if use_shell:
                    result = send_command_shell(channel, cmd,
                                                prompt_endings=prompt_endings, timeout=120)
                else:
                    result = send_command_exec(client, cmd, timeout=120)
                print(result)
                print()
        else:
            print("Nessun comando fornito.")

        if channel:
            channel.close()

    except paramiko.AuthenticationException as exc:
        print(f"Errore autenticazione: {exc}", file=sys.stderr)
        sys.exit(1)
    except paramiko.SSHException as exc:
        print(f"Errore SSH: {exc}", file=sys.stderr)
        sys.exit(1)
    except socket.timeout:
        print(f"Timeout connessione a {host}:{port}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Errore generico: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        client.close()


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Client SSH con Paramiko per apparati di rete multipli"
    )
    parser.add_argument("host", nargs="?")
    parser.add_argument("user", nargs="?")
    parser.add_argument("--password", "-p", default=None)
    parser.add_argument("--port", "-P", type=int, default=22)
    parser.add_argument("--cmd", "-c", action="append", help="Comando da eseguire (ripetibile)")
    parser.add_argument("--key", "-k", action="append", help="Chiave privata SSH")
    parser.add_argument("--no-host-key-check", action="store_true",
                        help="Disabilita verifica host key (solo lab)")
    parser.add_argument(
        "--device", "-d",
        default=None,
        choices=list(DEVICE_PROFILES.keys()),
        help=f"Tipo dispositivo. Opzioni: {', '.join(DEVICE_PROFILES.keys())}. Default: generic"
    )

    args = parser.parse_args()

    if not args.host or not args.user:
        parser.error("Host e User sono obbligatori")

    try:
        run_client(
            args.host,
            args.user,
            args.password,
            args.port,
            args.cmd,
            args.key,
            args.no_host_key_check,
            args.device,
        )
    except KeyboardInterrupt:
        print("\nInterrotto dall'utente")
