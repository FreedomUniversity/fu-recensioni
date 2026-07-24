#!/usr/bin/env python3
"""RECENSIONI TRUSTPILOT — poller modulo Tally (cloud). CANALE "team/contest".
============================================================================
Chi compila il modulo Tally (https://form.freedomuniversity.it/recensione) chiede
un invito recensione per un cliente. Questo poller lo consegna.

RIFONDAZIONE 24/7/2026 — CRM-INDIPENDENTE
-----------------------------------------
Prima l'invito partiva creando un'attività "Trustpilot" in Pipedrive e spuntandola,
per far scattare l'automazione NATIVA Pipedrive → webhook. Due problemi:
  1) Pipedrive è il CRM che si sta ABBANDONANDO (migrazione a GHL, 22/7): quel
     percorso muore con lui.
  2) L'automazione nativa soffre di throttling (saltava ~2/3 degli invii ravvicinati).
Ora l'invito è un POST DIRETTO al webhook Klaviyo (deterministico, verificato:
HTTP 200 + Make status 1), identico al motore GHL. Zero dipendenza dal CRM.

Freni: dedup cross-canale (registro unico rcfg) · anti-bulk · email valida.
Il budget 50/mese è condiviso col canale GHL (registro unico) → impossibile sforare.
"""
import json, os, sys, time, urllib.request, urllib.parse, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rcfg
import invio

LOG_PATH      = os.path.join(rcfg.STATE, "recensioni_trustpilot.log")
TALLY_TOKEN   = rcfg.secret("TALLY_TOKEN", "~/.config/tally-token")
TALLY_FORM_ID = "WO1XyP"
TALLY_UA      = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
SEEN_FILE     = os.path.join(rcfg.STATE, "tally_seen_recensioni.json")
GETTONI_CSV   = os.path.join(rcfg.STATE, "recensioni_gettoni.csv")
SEND_GAP      = 8
MAX_BATCH     = int(os.environ.get("TALLY_MAX_BATCH", "20"))   # freno anti-bulk
BUDGET_MESE   = int(os.environ.get("TRUSTPILOT_BUDGET", "50")) # tetto piano free
DM_DOMENICO   = "U0A4ET9U56E"
SLACK_TOKEN   = rcfg.secret("SLACK_FU_TOKEN", "~/.config/deus-user-token")

def log(msg):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    line = f"{datetime.datetime.now().isoformat(timespec='seconds')} | {msg}"
    print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")

def _get_json_retry(url, headers=None, tries=3, backoff=5):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            last = e
            if i < tries - 1:
                time.sleep(backoff)
    raise last

def slack(text):
    if not SLACK_TOKEN:
        return
    try:
        body = json.dumps({"channel": DM_DOMENICO, "text": text}).encode()
        req = urllib.request.Request("https://slack.com/api/chat.postMessage", data=body,
                                     headers={"Authorization": f"Bearer {SLACK_TOKEN}",
                                              "Content-Type": "application/json; charset=utf-8"})
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as e:
        log(f"slack fallito: {e}")

def send_invite(email, nome):
    """Invito = iscrizione con consenso su Klaviyo (vedi invio.py). True se consegnato.
    Se Klaviyo è giù ritorna False → il chiamante NON segna la richiesta come vista (riprova)."""
    ok, _via = invio.manda_invito(email, nome)
    return ok

def _alert_consegna_giu():
    """Klaviyo non raggiungibile → richieste in coda (non perse). Alert 1/giorno."""
    try:
        marker = os.path.join(rcfg.STATE, "consegna_down_alert_last")
        oggi = datetime.date.today().isoformat()
        if (open(marker).read().strip() if os.path.exists(marker) else "") != oggi:
            open(marker, "w").write(oggi)
            slack("🟡 *Recensioni — consegna Klaviyo non raggiungibile*\n"
                  "Le richieste dal modulo restano IN CODA e ripartono appena Klaviyo torna. "
                  "Nessun invito perso.")
    except Exception:
        pass

def tally_get(path):
    url = f"https://api.tally.so{path}"
    return _get_json_retry(url, headers={
        "Authorization": f"Bearer {TALLY_TOKEN}", "User-Agent": TALLY_UA, "accept": "application/json"})

def _load_seen():
    try:
        return set(json.load(open(SEEN_FILE)))
    except Exception:
        return set()

def _save_seen(seen):
    json.dump(sorted(seen), open(SEEN_FILE, "w"))

def gettone_log(nome, email, collaboratore):
    new = not os.path.exists(GETTONI_CSV)
    with open(GETTONI_CSV, "a") as f:
        if new:
            f.write("data,nome,email,collaboratore\n")
        f.write(f"{datetime.date.today().isoformat()},\"{nome}\",{email},\"{collaboratore}\"\n")

def _answer_fields(resp, questions):
    qmap = {q["id"]: q for q in questions}
    out = {"nome": "", "email": "", "collab": "", "note": ""}
    for a in resp.get("responses", []):
        q = qmap.get(a.get("questionId")) or {}
        title = (q.get("title") or "").lower()
        val = a.get("answer")
        if isinstance(val, list):
            opts = {o.get("id"): o.get("text") for o in (q.get("options") or [])}
            val = ", ".join(opts.get(x, str(x)) for x in val)
        val = (val or "").strip() if isinstance(val, str) else (val or "")
        if "nome" in title and not out["nome"]:
            out["nome"] = val
        elif "email" in title and not out["email"]:
            out["email"] = val
        elif ("procurat" in title or "chi ha" in title) and not out["collab"]:
            out["collab"] = val
        elif "note" in title and not out["note"]:
            out["note"] = val
    return out

def process_tally():
    if not TALLY_TOKEN:
        log("TALLY_TOKEN mancante: canale Tally non attivo"); return
    try:
        data = tally_get(f"/forms/{TALLY_FORM_ID}/submissions?filter=completed")
    except Exception as e:
        log(f"TALLY errore lettura: {e}"); return
    subs = data.get("submissions") or []
    questions = data.get("questions") or []
    seen = _load_seen()
    nuovi = [s for s in subs if s.get("id") not in seen]
    if not nuovi:
        return
    log(f"TALLY: {len(nuovi)} nuova/e richiesta/e")

    # FRENO ANTI-BULK: il modulo è a bassa frequenza (umano). Un picco = errore/abuso.
    # Segno comunque tutto come 'visto' per non ri-scatenarlo, ma NON invio: allerta e basta.
    if len(nuovi) > MAX_BATCH:
        for s in nuovi:
            seen.add(s.get("id"))
        _save_seen(seen)
        log(f"🚨 TALLY ANTI-BULK: {len(nuovi)} richieste in un colpo (soglia {MAX_BATCH}) → STOP, 0 invii")
        slack(f"🚨 *Recensioni — anti-bulk modulo Tally*\n"
              f"Arrivate *{len(nuovi)}* richieste tutte insieme (soglia {MAX_BATCH}). "
              f"Non ho inviato niente: sembra un errore o un import, non richieste vere.")
        return

    for s in nuovi:
        sid = s.get("id")
        f = _answer_fields(s, questions)
        nome = (f["nome"] or "").strip()
        email = (f["email"] or "").strip().lower()
        collab = f["collab"] or "?"
        if not rcfg.valid_email(email):
            log(f"  ✗ TALLY {sid}: email mancante/non valida ({email!r}), skip")
            seen.add(sid); _save_seen(seen); continue
        if rcfg.invite_seen(email):            # dedup cross-canale (Tally + GHL)
            log(f"  ⏭ TALLY {sid}: {email} già invitata → skip (no doppioni)")
            seen.add(sid); _save_seen(seen); continue
        if rcfg.invites_this_month() >= BUDGET_MESE:
            log(f"  ⛔ TALLY {sid}: tetto {BUDGET_MESE}/mese raggiunto → {email} resta in coda")
            slack(f"🚨 *Recensioni — tetto mensile raggiunto* ({BUDGET_MESE}/{BUDGET_MESE}).\n"
                  f"La richiesta di *{nome or email}* dal modulo aspetta il mese prossimo, "
                  f"oppure fai l'upgrade del piano Trustpilot.")
            break                              # NON segno seen: si riprova più avanti
        try:
            if send_invite(email, nome):
                rcfg.invite_record(email, "tally")     # registro unico
                gettone_log(nome, email, collab)       # attribuzione contest
                log(f"  ✓ TALLY {sid}: {nome} <{email}> | procurata da {collab} → invito inviato")
            else:
                log(f"  ⏳ TALLY {sid}: {nome} <{email}> → IN CODA (Klaviyo non raggiungibile), riprovo al giro dopo")
                _alert_consegna_giu()
                continue                       # NON segno seen: ritenta
            time.sleep(SEND_GAP)
        except Exception as e:
            log(f"  ✗ TALLY {sid}: {nome} <{email}> ERRORE → {e}")
            continue                           # NON segno seen: ritenta
        seen.add(sid); _save_seen(seen)

def main():
    try:
        process_tally()
    except Exception as e:
        log(f"process_tally crash: {e}")

if __name__ == "__main__":
    main()
