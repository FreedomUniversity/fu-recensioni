#!/usr/bin/env python3
"""
STATO INVITO — la prova che la mail è davvero uscita
====================================================
`POST /conversations/messages` risponde «Email queued successfully» con un 201.
**Non è una consegna.** Questo script legge lo stato REALE della mail su GHL:
`delivered` · `opened` · `bounced` · `failed`.

Nasce il 19/10/2026 dopo un caso preciso: su Klaviyo un `add to list` tornava
«riuscito» anche a flow spento, l'invito risultava mandato, il registro lo marcava
per sempre (il dedup vale a vita) e la mail non partiva mai. Nessuno aveva un modo
per accorgersene. Ora c'è: `python3 stato_invito.py <email>`.

⚠️ L'`emailMessageId` NON è l'id del messaggio di conversazione: sta in
`meta.email.messageIds[0]`. Usare l'altro dà HTTP 400 — ci ho sbattuto, è scritto qui
per non farlo sbattere al prossimo.
"""
import json, sys, urllib.parse, urllib.request, urllib.error
import rcfg

TOKEN    = rcfg.secret("GHL_TOKEN_FU",    "~/.config/ghl-token-fu-crm-new")
LOCATION = rcfg.secret("GHL_LOCATION_FU", "~/.config/ghl-location-fu")
BASE = "https://services.leadconnectorhq.com"
UA   = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "Chrome/124.0 Safari/537.36")


def _get(url, version="2021-07-28", tries=3):
    """GHL ogni tanto risponde vuoto: senza retry un controllo torna 'non trovato'
    e si scambia un intoppo di rete per una mail mai partita."""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {TOKEN}", "Version": version,
                "Accept": "application/json", "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                if raw:
                    return json.loads(raw)
        except Exception as e:
            last = e
        import time
        time.sleep(2 + i * 2)
    if last:
        print(f"   (GHL non risponde: {str(last)[:80]})", file=sys.stderr)
    return {}


def stato(email):
    email = email.strip()
    d = _get(f"{BASE}/contacts/?locationId={LOCATION}"
             f"&query={urllib.parse.quote(email)}&limit=5")
    cid = next((c["id"] for c in (d.get("contacts") or [])
                if (c.get("email") or "").lower() == email.lower()), None)
    if not cid:
        return {"email": email, "esito": "contatto non trovato in GHL"}

    # NB: `search?contactId=` su GHL NON risponde (la chiamata resta appesa finché
    # scade il timeout). Si cerca per email, poi si filtra sul contatto giusto.
    convs = [c for c in (_get(f"{BASE}/conversations/search?locationId={LOCATION}"
                              f"&query={urllib.parse.quote(email)}",
                              version="2021-04-15").get("conversations") or [])
             if c.get("contactId") == cid]
    if not convs:
        return {"email": email, "esito": "nessuna conversazione: mail mai mandata"}

    msgs = _get(f"{BASE}/conversations/{convs[0]['id']}/messages", version="2021-04-15")
    lista = msgs.get("messages", {}).get("messages") or msgs.get("messages") or []
    for m in lista:
        if m.get("messageType") != "TYPE_EMAIL" or m.get("direction") != "outbound":
            continue
        ids = (m.get("meta") or {}).get("email", {}).get("messageIds") or []
        if not ids:
            continue
        em = _get(f"{BASE}/conversations/messages/email/{ids[0]}",
                  version="2021-04-15").get("emailMessage") or {}
        bcc = em.get("bcc") or []
        return {"email": email, "esito": em.get("status") or "sconosciuto",
                "quando": em.get("dateAdded"), "da": em.get("from"),
                "bcc_trustpilot": any("invite.trustpilot.com" in b for b in bcc),
                "oggetto": em.get("subject")}
    return {"email": email, "esito": "nessuna mail in uscita trovata"}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("uso: stato_invito.py <email> [<email> ...]")
        raise SystemExit(2)
    for e in sys.argv[1:]:
        r = stato(e)
        verif = "SI ✅" if r.get("bcc_trustpilot") else "NO ⚠️  (recensione sarebbe spontanea)"
        print(f"\n  {r['email']}")
        print(f"    stato consegna : {r['esito']}")
        if "quando" in r:
            print(f"    quando         : {r['quando']}")
            print(f"    mittente       : {r['da']}")
            print(f"    BCC Trustpilot : {verif}")
