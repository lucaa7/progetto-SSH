import argparse
import sys
from typing import Optional, List

from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException


# python sshTelnetclient.py 192.168.1.254 cisco -p PswSSH5M! -P 23 -d cisco -c "show run"
# python sshTelnetclient.py 10.40.172.200 rconfig -p pswSSH -P 23 -d mikrotik -c "/export"

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


def run_client(
    host: str,
    user: str,
    password: Optional[str],
    port: int,
    cmds: Optional[List[str]],
    device: str,
    no_host_key_check: bool,
) -> None:

    proto = "ssh" if port == 22 else "telnet"
    device_type = DEVICE_MAP.get((device, proto), "terminal_server")

    print(f"Connessione a {host}:{port} ({device} via {proto} → {device_type})...")

    conn_params = {
        "device_type": device_type,
        "host":        host,
        "username":    user,
        "password":    password or "",
    }

    if proto == "ssh":
        conn_params["port"] = port

    if no_host_key_check and proto == "ssh":
        conn_params["ssh_strict"] = False

    try:
        with ConnectHandler(**conn_params) as conn:
            print(f"Connessione stabilita con {host}!\n")

            if cmds:
                for cmd in cmds:
                    print(f"{'='*60}")
                    print(f"Comando: {cmd}")
                    print(f"{'='*60}")
                    output = conn.send_command(cmd, read_timeout=120)
                    print(output)
                    print()
            else:
                print("Nessun comando fornito.")

    except NetmikoAuthenticationException as exc:
        print(f"Errore autenticazione: {exc}", file=sys.stderr)
        sys.exit(1)
    except NetmikoTimeoutException as exc:
        print(f"Timeout connessione: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Errore generico: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Client SSH/Telnet con Netmiko per apparati di rete multipli"
    )
    parser.add_argument("host", nargs="?")
    parser.add_argument("user", nargs="?")
    parser.add_argument("--password", "-p", default=None)
    parser.add_argument("--port", "-P", type=int, default=22,
                        help="22=SSH (default), 23=Telnet")
    parser.add_argument("--cmd", "-c", action="append")
    parser.add_argument("--device", "-d", default="generic",
                        choices=["mikrotik", "cisco", "cisco_ios", "generic"])
    parser.add_argument("--no-host-key-check", action="store_true")

    args = parser.parse_args()

    if not args.host or not args.user:
        parser.error("Host e User sono obbligatori")

    try:
        run_client(
            args.host, args.user, args.password, args.port,
            args.cmd, args.device, args.no_host_key_check,
        )
    except KeyboardInterrupt:
        print("\nInterrotto dall'utente")