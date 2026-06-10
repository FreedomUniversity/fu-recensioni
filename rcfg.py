#!/usr/bin/env python3
"""Config condivisa del sistema Recensioni — funziona in cloud (env) e in locale (file).
Lo STATO (csv, seen, gettoni) vive in ./state nel repo e viene committato dai workflow."""
import os

ROOT  = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get("REC_STATE", os.path.join(ROOT, "state"))
os.makedirs(STATE, exist_ok=True)

def secret(env, file_path=None, key=None, default=None):
    """token da variabile d'ambiente (cloud) o da file ~/.config (locale)."""
    v = os.environ.get(env)
    if v:
        return v.strip()
    if file_path and os.path.exists(os.path.expanduser(file_path)):
        raw = open(os.path.expanduser(file_path)).read()
        if key:  # file tipo KEY=VALUE
            for line in raw.splitlines():
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip()
            return default
        return raw.strip()
    return default

PD_BASE = secret("PIPEDRIVE_API_BASE", default="https://freedomuniversity.pipedrive.com/api/v1")
