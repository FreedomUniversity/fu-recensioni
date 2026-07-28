#!/usr/bin/env python3
"""
INVIO INVITO RECENSIONE — consegna affidabile e onesta
======================================================
Verità (24-28/7/2026): Klaviyo manda l'invito SOLO se il profilo (1) ha CONSENSO e
(2) NON e' soppresso, e SOLO se il Flow riceve un evento "Added to List". Un semplice
add-to-list, o un 202 dell'API, NON garantiscono la consegna.

SEQUENZA AFFIDABILE (la stessa che ha consegnato 83 recensioni, in klaviyo_subscribe):
  1. ISCRIVI l'email con consenso SUBSCRIBED nella lista TnYVNH (3 retry).
  2. Leggi il profilo: se e' SOPPRESSO (bounce/unsubscribe reale) -> NON consegnabile,
     ritorna (False,"soppresso"): onesto, non lo conto come inviato.
  3. FORZA il trigger: rimuovi dalla lista + ri-aggiungi -> evento "Added to List"
     fresco -> il Flow XiHYbD parte e manda l'invito verificato (BCC AFS Trustpilot).

Se Klaviyo e' irraggiungibile -> (False,None): invito IN CODA, mai falso "inviato",
si ritenta (e klaviyo_subscribe.py fa da backstop). Klaviyo e' dipendenza dura: il
Flow verificato vive li'.

manda_invito(email, nome) -> (ok, via: "klaviyo" | "soppresso" | None)
"""
import json, os, time, urllib.request, urllib.error, urllib.parse
import rcfg

KTOK    = rcfg.secret("KLAVIYO_TOKEN", "~/.config/klaviyo-token")
LIST_ID = rcfg.secret("KLAVIYO_LIST", default="TnYVNH")
_FORCE_FAIL = os.environ.get("KLAVIYO_FORCE_FAIL") == "1"   # test: forza "in coda"


def _kheaders():
    return {"Authorization": f"Klaviyo-API-Key {KTOK}", "revision": "2024-10-15",
            "content-type": "application/json", "accept": "application/json"}


def _req(url, data=None, method="GET", timeout=25):
    """Ritorna sempre (code, dict/bytes) senza sollevare su errore HTTP."""
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=_kheaders(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try:
                return r.getcode(), json.loads(raw or b"{}")
            except Exception:
                return r.getcode(), {}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception:
        return 0, {}


def _iscrivi(email):
    """Iscrive con consenso SUBSCRIBED + aggiunge alla lista. 202 = accettato."""
    body = {"data": {"type": "profile-subscription-bulk-create-job", "attributes": {
                "custom_source": "Richiesta recensione FU",
                "profiles": {"data": [{"type": "profile", "attributes": {
                    "email": email,
                    "subscriptions": {"email": {"marketing": {"consent": "SUBSCRIBED"}}}}}]}},
            "relationships": {"list": {"data": {"type": "list", "id": LIST_ID}}}}}
    code, _ = _req("https://a.klaviyo.com/api/profile-subscription-bulk-create-jobs/", body, "POST")
    return code == 202


def _profilo(email):
    """(pid, soppresso). soppresso=True SOLO se c'e' un record di soppressione reale
    (bounce/unsubscribe), non per semplice consenso non-ancora-applicato (async)."""
    q = urllib.parse.urlencode({"filter": f'equals(email,"{email}")',
                                "additional-fields[profile]": "subscriptions"})
    code, d = _req(f"https://a.klaviyo.com/api/profiles/?{q}")
    data = (d.get("data") or [])
    if not data:
        return None, False
    a = data[0]
    pid = a.get("id")
    mk = ((a.get("attributes", {}) or {}).get("subscriptions", {}) or {}).get("email", {}).get("marketing", {}) or {}
    soppr = bool(mk.get("suppression") or mk.get("suppressions"))
    return pid, soppr


def _lista(pid, method):
    code, _ = _req(f"https://a.klaviyo.com/api/lists/{LIST_ID}/relationships/profiles/",
                   {"data": [{"type": "profile", "id": pid}]}, method)
    return code in (200, 201, 204)


def manda_invito(email, nome=""):
    if _FORCE_FAIL or not KTOK or not email:
        return False, None
    # 1) PRIMA controlla la soppressione: se il profilo esiste già ed è soppresso
    #    (bounce o disiscrizione reale) NON lo ri-iscriviamo (rispetto della scelta +
    #    tutela deliverability). Onesto: non consegnabile.
    pid, soppresso = _profilo(email)
    if soppresso:
        return False, "soppresso"
    # 2) iscrivi con consenso (retry sui blip di rete)
    ok = False
    for attempt in range(3):
        if _iscrivi(email):
            ok = True; break
        time.sleep(3 + attempt * 4)
    if not ok:
        return False, None                      # Klaviyo giu' -> in coda, mai perso
    # 3) recupera il pid se era un profilo nuovo (creato ora dall'iscrizione)
    if pid is None:
        time.sleep(6)                           # il job d'iscrizione è async
        pid, _ = _profilo(email)
        if pid is None:
            return False, None                  # non ancora visibile -> si ritenta
    # 4) FORZA il trigger: rimuovi + ri-aggiungi -> "Added to List" fresco -> Flow
    _lista(pid, "DELETE"); time.sleep(2)
    _lista(pid, "POST")
    return True, "klaviyo"
