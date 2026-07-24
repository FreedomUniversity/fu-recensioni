#!/usr/bin/env python3
"""Config condivisa del sistema Recensioni — funziona in cloud (env) e in locale (file).
Lo STATO (csv, seen, gettoni) vive in ./state nel repo e viene committato dai workflow."""
import os, json, re, datetime

ROOT  = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get("REC_STATE", os.path.join(ROOT, "state"))
os.makedirs(STATE, exist_ok=True)

# ---------------------------------------------------------------------------
# EMAIL — validazione condivisa (usata da tutti i canali)
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
def valid_email(e):
    return bool(e) and bool(_EMAIL_RE.match(e.strip()))

# ---------------------------------------------------------------------------
# REGISTRO INVITI UNICO — una sola fonte di verità per TUTTI i canali
# (GHL "Vinto" + modulo Tally + coda legacy). Serve a due cose insieme:
#   • DEDUP cross-canale: una persona è invitata UNA volta sola, da qualsiasi porta entri.
#   • BUDGET coerente: il tetto 50/mese del piano Trustpilot free si conta qui, in un
#     posto solo. Prima era spaccato (Pipedrive contava un canale, GHL un altro) → si
#     poteva sforare il tetto e bruciare l'account. Mai più.
# Formato: { "email_lowercase": {"date":"YYYY-MM-DD","canale":"ghl|tally|coda"},
#            "__baseline__": {"month":"YYYY-MM","count":N} }  # inviti già usati nel mese
# al momento in cui il registro è nato (una tantum, per non ripartire da 0 a metà mese).
# ---------------------------------------------------------------------------
INVITES_LEDGER = os.path.join(STATE, "invites_ledger.json")

def _ledger_load():
    try:
        return json.load(open(INVITES_LEDGER))
    except Exception:
        return {}

def _ledger_save(d):
    os.makedirs(STATE, exist_ok=True)
    tmp = INVITES_LEDGER + ".tmp"
    json.dump(d, open(tmp, "w"), indent=1, ensure_ascii=False)
    os.replace(tmp, INVITES_LEDGER)   # scrittura atomica: niente file mezzo scritto

def invite_seen(email):
    """True se questa email ha GIA' ricevuto un invito (qualsiasi canale, a vita)."""
    if not email:
        return False
    return email.strip().lower() in _ledger_load()

def invite_record(email, canale="?"):
    """Registra un invito inviato. Idempotente: ritorna False se era già presente."""
    if not email:
        return False
    e = email.strip().lower()
    d = _ledger_load()
    if e in d:
        return False
    d[e] = {"date": datetime.date.today().isoformat(), "canale": canale}
    _ledger_save(d)
    return True

def invites_this_month():
    """Inviti consumati nel mese corrente = baseline (se stesso mese) + inviti reali."""
    mese = datetime.date.today().strftime("%Y-%m")
    d = _ledger_load()
    base = d.get("__baseline__") or {}
    b = int(base.get("count", 0)) if base.get("month") == mese else 0
    real = sum(1 for k, v in d.items()
               if k != "__baseline__" and str((v or {}).get("date", "")).startswith(mese))
    return b + real

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
