import argparse
import sys
import time
import socket
import re
from typing import Optional, List

import paramiko

ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def read_until_prompt(channel, prompt_endings, timeout=60.0, chuck_delay=0.3): # Legge output da un canale SSH fino a quando non rileva un prompt o scade il timeout
    output = ""
    channel.settimeout(timeout) # Imposta timeout per operazioni di lettura
    deadline = time.time() + timeout # Calcola scadenza per timeout
    while time.time() < deadline:
        try:
            if channel.recv_ready():
                output += channel.recv(4096).decode("utf-8",errors="replace") # Legge dati se disponibili
                deadline = time.time() + timeout # Reset scadenza dopo ricezione dati
            else:
                if channel.exit_status_ready():
                    break # Esce se il canale è chiuso
                stripped = output.rstrip() # rimuove spazi bianchi finali
                if any(stripped.endswith(p) for p in prompt_endings):
                    break # Esce se l'output termina con un prompt
                time.sleep(chuck_delay) # Attende prima di tentare di leggere di nuovo
        except socket.timeout:
            stripped = output.rstrip()
            if any(stripped.endswith(p) for p in prompt_endings):
                break # esce se l'output termina con un prompt
            continue # Continua a tentare di leggere fino alla scadenza
        except Exception:
            break # Esce in caso di errori imprevisti
    return output


def send_command_shell(channel, command, prompt_endings, timeout=60.0): # Invia un comando a un canale SSH e legge l'output fino al prompt
    channel.send(command + "\n") # invia comando seguito da invio
    time.sleep(0.5) # Attende un breve periodo per permettere al dispositivo di rispondere
    raw = read_until_prompt(channel, prompt_endings, timeout) # legge l'output fino al prompt
    lines = raw.splitlines() # divide l'output in linee
    cmd = command.strip() # rimuove spazi bianchi dal comando
    while lines and lines[0].strip() and cmd.startswith(lines[0].strip()): # Rimuove l'eco del comando se presente
        lines = lines[1:] # Rimuove la prima linea se è l'eco del comando
    if lines and any(lines[-1].rstrip().endswith(p) for p in prompt_endings): # Rimuove l'ultima linea se è un prompt
        lines = lines[:-1]
    return "\n".join(lines) # Restituisce l'output pulito senza eco


def send_command_exec(channel, command, timeout=60.0): # Invia un comando usando exec_command e legge l'output
    stdin, stdout, stderr = channel.exec_command(command, timeout=timeout) # Esegue il comando
    output = stdout.read().decode("utf-8", errors="replace") # Legge l'output standard
    error = stderr.read().decode("utf-8", errors="replace") # Legge l'output di errore
    return output + error # Restituisce la combinazione di output e errori
