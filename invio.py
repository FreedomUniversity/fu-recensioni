#!/usr/bin/env python3
"""
INVIO INVITO RECENSIONE — consegna reale, pulita, senza perdite
================================================================
Un invito recensione conta solo se ARRIVA. La verità scoperta il 24/7/2026:
Klaviyo NON manda l'email a chi non ha CONSENSO. "Aggiungere alla lista" da solo
non basta (e "webhook HTTP 200" era un falso positivo: accettato != consegnato).

MECCANISMO UNICO (niente doppioni, niente vie morte):
  ISCRIVI l'email con consenso SUBSCRIBED nella lista Klaviyo TnYVNH
  -> il Flow "Automazione Trustpilot" (XiHYbD) parte e manda l'invito ufficiale
    verificato (BCC AFS Trustpilot). Provato end-to-end: la mail arriva.

Ridondanza SENZA rischi (Klaviyo e' la dipendenza dura: il Flow verificato vive li'):
  - RETRY: 3 tentativi con backoff sull'API Klaviyo (copre i blip di rete).
  - MAI PERSO: se Klaviyo e' davvero giu', manda_invito ritorna False -> il chiamante
    NON segna l'invito come inviato -> si ritenta al giro dopo. In piu' klaviyo_subscribe.py
    (nel tick) fa da backstop: iscrive chiunque finisca in lista senza consenso.
    Quindi un'indisponibilita' Klaviyo RITARDA l'invito, non lo perde.

manda_invito(email, nome) -> (ok: bool, via: "klaviyo" | None)
"""
import json, os, time, urllib.request, urllib.error
import rcfg

KTOK    = rcfg.secret("KLAVIYO_TOKEN", "~/.config/klaviyo-token")
LIST_ID = rcfg.secret("KLAVIYO_LIST", default="TnYVNH")
# Interruttore di test: forza il fallimento per provare il comportamento "in coda".
_FORCE_FAIL = os.environ.get("KLAVIYO_FORCE_FAIL") == "1"


def _kheaders():
    return {"Authorization": f"Klaviyo-API-Key {KTOK}", "revision": "2024-10-15",
            "content-type": "application/json", "accept": "application/json"}


def _post(url, data, timeout=25):
    """POST che NON solleva su errore HTTP: ritorna sempre (code, body_bytes)."""
    req = urllib.request.Request(url, data=json.dumps(data).encode(),
                                 headers=_kheaders(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.getcode(), r.read()
    except urllib.error.HTTPError as e:
        return e.code, (e.read() if hasattr(e, "read") else b"")
    except Exception:
        return 0, b""


def _iscrivi_con_consenso(email):
    """Iscrive l'email (consenso SUBSCRIBED) nella lista TnYVNH -> innesca il Flow.
    202 = job accettato. NB: il job accetta solo email + subscriptions (niente first_name)."""
    body = {"data": {"type": "profile-subscription-bulk-create-job", "attributes": {
                "custom_source": "Richiesta recensione FU",
                "profiles": {"data": [{"type": "profile", "attributes": {
                    "email": email,
                    "subscriptions": {"email": {"marketing": {"consent": "SUBSCRIBED"}}}}}]}},
            "relationships": {"list": {"data": {"type": "list", "id": LIST_ID}}}}}
    code, _b = _post("https://a.klaviyo.com/api/profile-subscription-bulk-create-jobs/", body)
    return code == 202


def manda_invito(email, nome=""):
    """Ritorna (ok, via). Iscrizione-con-consenso con 3 retry. Se fallisce tutto ->
    (False, None): l'invito NON e' dato per inviato, si ritentera' (mai perso)."""
    if _FORCE_FAIL or not KTOK or not email:
        return False, None
    for attempt in range(3):
        if _iscrivi_con_consenso(email):
            return True, "klaviyo"
        time.sleep(3 + attempt * 4)
    return False, None
