#!/usr/bin/env python3
"""
INVIO INVITO RECENSIONE — via GHL, con Trustpilot in BCC
========================================================
COME NASCE UNA RECENSIONE "VERIFICATA" (l'unica cosa che conta davvero)
-----------------------------------------------------------------------
Non è il link che rende verificata una recensione: è DA DOVE il cliente ci arriva.
Si manda al cliente una mail normale mettendo in **BCC l'indirizzo AFS** di
Trustpilot. Trustpilot legge quella copia e manda LUI il suo invito ufficiale.
Il cliente recensisce da QUELLA mail → ✅ VERIFICATA.
Se invece gli mandi il link su WhatsApp o in una mail qualsiasi, la recensione esce
"spontanea": vale molto meno e non ha la spunta.

PERCHE' GHL E NON PIU' KLAVIYO (19/10/2026)
--------------------------------------------
Fino a oggi la mail col BCC la mandava un flow Klaviyo (`XiHYbD`, lista TnYVNH).
Klaviyo non si usa più. E non era nemmeno un buon posto dove stare:
  • il flow era `disabled` dal 15/10 e l'API di Klaviyo NON ha un metodo per
    riportare "live" il messaggio dentro un flow → la catena restava in ostaggio
    di un clic nell'interfaccia che nessuno sapeva di dover fare;
  • peggio: un `add to list` tornava "riuscito" anche a flow spento. L'invito
    risultava mandato, il registro lo marcava PER SEMPRE (il dedup vale a vita) e
    la mail non partiva. Un "200 che mente" che bruciava la richiesta in silenzio.
GHL è il CRM che usiamo davvero, l'invio è una chiamata sola, e dopo si può
rileggere lo stato REALE della mail (consegnata/aperta), non "accodata da qualche
parte". Provato il 19/10 con un invio vero: `status: opened`, `bcc` presente nel
record, provider mailgun, mittente info@freedomuniversity.it.

manda_invito(email, nome) -> (ok, via: "ghl" | "soppresso" | None)
  (False, None) → GHL non raggiungibile: invito IN CODA, si ritenta. Mai un falso
                  "inviato": è esattamente quello che bruciava le richieste.
"""
import json, os, re, urllib.request, urllib.error, urllib.parse
import rcfg

GHL_TOKEN    = rcfg.secret("GHL_TOKEN_FU",    "~/.config/ghl-token-fu-crm-new")
GHL_LOCATION = rcfg.secret("GHL_LOCATION_FU", "~/.config/ghl-location-fu")

# L'indirizzo AFS di Trustpilot per freedomuniversity.it. E' LA CHIAVE della
# recensione verificata: senza questo BCC parte una mail qualunque e la recensione
# esce "spontanea". Non si cambia senza rifare il giro dentro Trustpilot.
BCC_AFS = os.environ.get("TRUSTPILOT_AFS_BCC",
                         "freedomuniversity.it+fd0960a0f4@invite.trustpilot.com")

BASE = "https://services.leadconnectorhq.com"
UA   = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "Chrome/124.0 Safari/537.36")
EMAIL_OK = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)

_FORCE_FAIL = os.environ.get("GHL_FORCE_FAIL") == "1"   # test: forza "in coda"

OGGETTO = "Com'e' andata con Freedom University?"


def _corpo(nome):
    saluto = f"Ciao {nome.split()[0]}," if (nome or "").strip() else "Ciao,"
    return (f"<p>{saluto}</p>"
            "<p>una cosa veloce: ci lasceresti due righe su com'e' andata con "
            "Freedom University?</p>"
            "<p>Ti arriva fra poco una mail da Trustpilot con il link: bastano "
            "30 secondi e per noi vale tantissimo.</p>"
            "<p>Grazie!<br>Il team Freedom University</p>")


def _headers(version):
    return {"Authorization": f"Bearer {GHL_TOKEN}", "Version": version,
            "Content-Type": "application/json", "Accept": "application/json",
            "User-Agent": UA}


def _req(url, data=None, method="GET", version="2021-07-28", timeout=30):
    """Ritorna sempre (code, dict). Non solleva su errore HTTP: un invito non si
    perde per un 4xx, o si rimette in coda o si dichiara non consegnabile."""
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=_headers(version), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.getcode(), (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception:
        return 0, {}


def _trova_o_crea_contatto(email, nome):
    """(contact_id, dnd) — oppure (None, None) se GHL non risponde."""
    code, d = _req(f"{BASE}/contacts/?locationId={GHL_LOCATION}"
                   f"&query={urllib.parse.quote(email)}&limit=5")
    if code == 0:
        return None, None
    for c in (d.get("contacts") or []):
        if (c.get("email") or "").strip().lower() == email.lower():
            return c.get("id"), bool(c.get("dnd"))
    # Non c'è: lo creo. In GHL una mail viaggia dentro una conversazione, quindi
    # senza contatto non c'è niente a cui attaccarla.
    parti = (nome or "").strip().split()
    code, d = _req(f"{BASE}/contacts/upsert",
                   {"locationId": GHL_LOCATION, "email": email,
                    "firstName": parti[0] if parti else "",
                    "lastName": " ".join(parti[1:]) if len(parti) > 1 else "",
                    "source": "Richiesta recensione Trustpilot"}, "POST")
    if code in (200, 201):
        c = d.get("contact") or {}
        return c.get("id"), bool(c.get("dnd"))
    return None, None


def stato_email(email_message_id):
    """Stato REALE della mail (delivered/opened/bounced...). Serve a non spacciare
    un 201 'accodata' per una consegna: il 201 dice solo che GHL l'ha presa."""
    code, d = _req(f"{BASE}/conversations/messages/email/{email_message_id}",
                   version="2021-04-15")
    return (d.get("emailMessage") or {}).get("status") if code == 200 else None


def manda_invito(email, nome=""):
    """Mail al cliente con Trustpilot in BCC → invito ufficiale → ✅ verificata."""
    email = (email or "").strip()
    if not EMAIL_OK.match(email):
        return False, "soppresso"          # indirizzo non valido: mai consegnabile
    if _FORCE_FAIL or not GHL_TOKEN or not GHL_LOCATION:
        return False, None                 # in coda, si ritenta

    cid, dnd = _trova_o_crea_contatto(email, nome)
    if cid is None:
        return False, None                 # GHL giù → coda, nessun falso "inviato"
    if dnd:
        return False, "soppresso"          # ha chiesto di non essere contattato

    code, d = _req(f"{BASE}/conversations/messages",
                   {"type": "Email", "contactId": cid, "subject": OGGETTO,
                    "emailBcc": [BCC_AFS], "html": _corpo(nome)},
                   "POST", version="2021-04-15", timeout=45)
    if code in (200, 201) and d.get("emailMessageId"):
        return True, "ghl"
    if code in (400, 422):
        return False, "soppresso"          # GHL rifiuta l'indirizzo
    return False, None                     # tutto il resto → coda, si ritenta


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("uso: invio.py <email> [nome]   — manda un invito VERO")
        raise SystemExit(2)
    ok, via = manda_invito(sys.argv[1], " ".join(sys.argv[2:]))
    print(f"ok={ok} via={via}")
