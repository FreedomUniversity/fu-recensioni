#!/usr/bin/env python3
"""
INVIO INVITO RECENSIONE — con RIDONDANZA (il motore non deve mai morire)
=======================================================================
Un invito recensione ha UNA sola importanza: partire. Prima dipendeva da una
sola via (webhook Make → Klaviyo): se Make cadeva, gli inviti si fermavano in
silenzio. Ora ci sono DUE vie indipendenti verso lo stesso risultato (il Flow
Klaviyo che manda l'invito Trustpilot verificato con BCC AFS):

  • PIANO A — POST al webhook Make (primario, veloce, com'è sempre stato).
  • PIANO B — se A fallisce, aggiunge l'email DIRETTAMENTE alla lista Klaviyo
    TnYVNH via API Klaviyo. Bypassa Make e il webhook: se Make è giù o il webhook
    è rotto/ruotato, l'invito parte lo stesso. Testato end-to-end (HTTP 204).

Se cadono ENTRAMBE le vie → ritorna fallimento: il chiamante NON segna l'invito
come inviato (si ritenta al giro dopo) e alza un allarme. Zero perdite silenziose.

manda_invito(email, nome) -> (ok: bool, via: "A" | "B" | None)
"""
import json, time, urllib.request, urllib.error
import rcfg

WEBHOOK = rcfg.secret("KLAVIYO_WEBHOOK",
                      default="https://hook.eu2.make.com/85i7cv4duj4pr6f8qehducde2rsijg3u")
KTOK    = rcfg.secret("KLAVIYO_TOKEN", "~/.config/klaviyo-token")
LIST_ID = rcfg.secret("KLAVIYO_LIST", default="TnYVNH")
# Interruttore di test: se KLAVIYO_WEBHOOK_FORCE_FAIL=1 il piano A finge sempre di
# cadere → serve a provare che il piano B salva davvero. Mai attivo in produzione.
import os
_FORCE_A_FAIL = os.environ.get("KLAVIYO_WEBHOOK_FORCE_FAIL") == "1"


def _post(url, data, headers, timeout=25):
    """POST che NON solleva su errore HTTP: ritorna sempre (code, body_bytes).
    Serve perché Klaviyo risponde 409 (profilo già esistente) e quel corpo ci serve."""
    req = urllib.request.Request(url, data=json.dumps(data).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.getcode(), r.read()
    except urllib.error.HTTPError as e:
        return e.code, (e.read() if hasattr(e, "read") else b"")
    except Exception:
        return 0, b""


def _plan_a(email, nome):
    if _FORCE_A_FAIL:
        return False
    for _ in range(2):
        code, _b = _post(WEBHOOK, {"Email": email, "Nome": nome or ""},
                         {"Content-Type": "application/json"})
        if code == 200:
            return True
        time.sleep(3)
    return False


def _kheaders():
    return {"Authorization": f"Klaviyo-API-Key {KTOK}", "revision": "2024-10-15",
            "content-type": "application/json", "accept": "application/json"}


def _plan_b(email, nome):
    """Via indipendente: crea/ritrova il profilo Klaviyo e lo aggiunge alla lista
    TnYVNH → innesca lo stesso Flow del webhook. Nessuna dipendenza da Make."""
    if not KTOK:
        return False
    # 1) crea profilo (o ritrova l'id se già esiste → 409 con duplicate_profile_id)
    code, body = _post("https://a.klaviyo.com/api/profiles/",
                       {"data": {"type": "profile",
                                 "attributes": {"email": email, "first_name": nome or ""}}},
                       _kheaders())
    try:
        d = json.loads(body or b"{}")
    except Exception:
        d = {}
    pid = (d.get("data") or {}).get("id")
    if not pid:
        pid = (((d.get("errors") or [{}])[0].get("meta") or {}).get("duplicate_profile_id"))
    if not pid:
        return False
    # 2) aggiungi alla lista → Flow invito
    code, _b = _post(f"https://a.klaviyo.com/api/lists/{LIST_ID}/relationships/profiles/",
                     {"data": [{"type": "profile", "id": pid}]}, _kheaders())
    return code in (200, 201, 204)


def manda_invito(email, nome=""):
    """Ritorna (ok, via). Prova A, poi B. Nessuna via che riesce → (False, None)."""
    if _plan_a(email, nome):
        return True, "A"
    if _plan_b(email, nome):
        return True, "B"
    return False, None
