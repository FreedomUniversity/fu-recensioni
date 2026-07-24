#!/usr/bin/env python3
"""
INVIO INVITO RECENSIONE — con RIDONDANZA (il motore non deve mai morire)
=======================================================================
Un invito recensione ha UNA sola importanza: partire (e ARRIVARE). Due vie verso
lo stesso Flow Klaviyo che manda l'invito Trustpilot verificato (BCC AFS):

  • PIANO A — ISCRIVE il profilo con CONSENSO su Klaviyo + lista TnYVNH (API diretta).
    È la via primaria perché è l'UNICA che consegna davvero: il consenso è la chiave
    (senza, Klaviyo non manda; add-to-list da solo NON basta). Provato: il Flow parte.
  • PIANO B — se A è giù, POST al webhook Make → Klaviyo (canale storico, altra strada).

Se cadono ENTRAMBE → il chiamante NON segna l'invito come inviato (si ritenta) + alert.
Zero perdite silenziose. LEZIONE: "webhook HTTP 200" ≠ "mail arrivata"; conta il consenso.

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


def _kheaders():
    return {"Authorization": f"Klaviyo-API-Key {KTOK}", "revision": "2024-10-15",
            "content-type": "application/json", "accept": "application/json"}


def _plan_a(email, nome):
    """Consegna PRIMARIA: ISCRIVE il profilo (consenso SUBSCRIBED) e lo mette nella lista
    TnYVNH via Klaviyo → il Flow Trustpilot parte e manda l'invito.

    SCOPERTA CHIAVE (24/7/2026): il CONSENSO è tutto. Solo "aggiungere alla lista" NON
    basta — Klaviyo non manda mail marketing a chi non ha consenso, quindi il Flow non
    consegna. Provato: add-to-list → 0 mail; iscrizione con consenso → Flow XiHYbD parte
    e la mail arriva. Per questo l'iscrizione+consenso è la via primaria, non il webhook.
    202 = job accettato."""
    if _FORCE_A_FAIL or not KTOK:
        return False
    # NB: il job d'iscrizione accetta SOLO email + subscriptions (niente first_name → 400).
    body = {"data": {"type": "profile-subscription-bulk-create-job", "attributes": {
                "profiles": {"data": [{"type": "profile", "attributes": {
                    "email": email,
                    "subscriptions": {"email": {"marketing": {"consent": "SUBSCRIBED"}}}}}]}},
            "relationships": {"list": {"data": {"type": "list", "id": LIST_ID}}}}}
    code, _b = _post("https://a.klaviyo.com/api/profile-subscription-bulk-create-jobs/",
                     body, _kheaders())
    return code == 202


def _plan_b(email, nome):
    """Fallback indipendente: POST al webhook Make → Klaviyo (canale storico). Se la via A
    (API Klaviyo diretta) è giù, questo raggiunge Klaviyo per un'altra strada."""
    for _ in range(2):
        code, _b = _post(WEBHOOK, {"Email": email, "Nome": nome or ""},
                         {"Content-Type": "application/json"})
        if code == 200:
            return True
        time.sleep(3)
    return False


def manda_invito(email, nome=""):
    """Ritorna (ok, via). Prova A, poi B. Nessuna via che riesce → (False, None)."""
    if _plan_a(email, nome):
        return True, "A"
    if _plan_b(email, nome):
        return True, "B"
    return False, None
