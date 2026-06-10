#!/usr/bin/env python3
"""RECENSIONI TRUSTPILOT — poller (cloud). Due canali in ingresso, UN solo meccanismo
d'uscita: l'automazione nativa Pipedrive (attività "Trustpilot" COMPLETATA → invito).
  CANALE A — modulo Tally: nuove risposte → persona Pipedrive + attività "Trustpilot" spuntata.
  CANALE B — campo persona "Invito Recensione = Da Inviare" (filtro 58883).
Gli inviti li decide chi compila il Tally / flagga la persona: nessun invio di massa."""
import json, os, sys, time, urllib.request, urllib.parse, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rcfg

PIPE_TOKEN = rcfg.secret("PIPEDRIVE_TOKEN", "~/.claude_pipedrive_creds", key="PIPEDRIVE_TOKEN")
PIPE_BASE  = rcfg.PD_BASE

QUEUE_FILTER_ID   = 58883
FIELD_INVITO_KEY  = "04f26cb912dfc021f5a826ef717172039dcc57e5"
OPT_DA_INVIARE    = 103
OPT_INVIATO       = 104
OPT_ERRORE        = 105
ACTIVITY_SUBJECT  = "Trustpilot"
ACTIVITY_TYPE     = "lunch"
LOG_PATH          = os.path.join(rcfg.STATE, "recensioni_trustpilot.log")

TALLY_TOKEN   = rcfg.secret("TALLY_TOKEN", "~/.config/tally-token")
TALLY_FORM_ID = "WO1XyP"
TALLY_UA      = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
SEEN_FILE     = os.path.join(rcfg.STATE, "tally_seen_recensioni.json")
GETTONI_CSV   = os.path.join(rcfg.STATE, "recensioni_gettoni.csv")
CLIENTE_KEY   = "70e2e34b03a182a9e358a51658d546bc9478f3fd"
CLIENTE_SI    = 41
PROCURATA_KEY = "b20c86b72f92ee5e9498e82bcd93f764ef405144"
SEND_GAP      = 60

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

def pd_get(path, **params):
    params["api_token"] = PIPE_TOKEN
    url = f"{PIPE_BASE}{path}?{urllib.parse.urlencode(params)}"
    return _get_json_retry(url)

def pd_req(method, path, body):
    url = f"{PIPE_BASE}{path}?{urllib.parse.urlencode({'api_token': PIPE_TOKEN})}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def first_email(person):
    em = person.get("email")
    if isinstance(em, list):
        for e in em:
            if e.get("value"):
                return e["value"].strip()
    elif isinstance(em, str) and em.strip():
        return em.strip()
    return None

def set_invito(person_id, option_id):
    pd_req("PUT", f"/persons/{person_id}", {FIELD_INVITO_KEY: option_id})

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

def upsert_person(name, email):
    r = pd_get("/persons/search", term=email, fields="email", exact_match="true", limit=1)
    items = (r.get("data") or {}).get("items") or []
    if items:
        return items[0]["item"]["id"]
    r = pd_req("POST", "/persons", {"name": name or email,
                                    "email": [{"value": email, "primary": True}]})
    return r["data"]["id"]

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
        return
    try:
        data = tally_get(f"/forms/{TALLY_FORM_ID}/submissions?filter=completed")
    except Exception as e:
        log(f"TALLY errore lettura: {e}")
        return
    subs = data.get("submissions") or []
    questions = data.get("questions") or []
    seen = _load_seen()
    nuovi = [s for s in subs if s.get("id") not in seen]
    if not nuovi:
        return
    log(f"TALLY: {len(nuovi)} nuova/e richiesta/e")
    for s in nuovi:
        sid = s.get("id")
        f = _answer_fields(s, questions)
        nome = f["nome"]; email = f["email"]; collab = f["collab"] or "?"; note = f["note"]
        if not email:
            log(f"  ✗ TALLY {sid}: email mancante, skip"); seen.add(sid); _save_seen(seen); continue
        try:
            pid = upsert_person(nome, email)
            aid = pd_req("POST", "/activities", {
                "subject": ACTIVITY_SUBJECT, "type": ACTIVITY_TYPE, "person_id": pid, "done": 0,
                "note": f"Invito Trustpilot via modulo Tally. Procurata da: {collab}. {note}".strip()})["data"]["id"]
            pd_req("PUT", f"/activities/{aid}", {"done": 1})
            pd_req("PUT", f"/persons/{pid}", {FIELD_INVITO_KEY: OPT_INVIATO, CLIENTE_KEY: CLIENTE_SI,
                                              PROCURATA_KEY: collab})
            gettone_log(nome, email, collab)
            log(f"  ✓ TALLY {sid}: {nome} <{email}> | procurata da {collab} → attività spuntata → automazione")
            time.sleep(SEND_GAP)
        except Exception as e:
            log(f"  ✗ TALLY {sid}: {nome} <{email}> ERRORE → {e}")
        seen.add(sid); _save_seen(seen)

def main():
    try:
        process_tally()
    except Exception as e:
        log(f"process_tally crash: {e}")
    try:
        res = pd_get("/persons", filter_id=QUEUE_FILTER_ID, limit=100)
    except Exception as e:
        log(f"ERRORE lettura coda: {e}")
        return
    people = res.get("data") or []
    if not people:
        return
    log(f"coda: {len(people)} persona/e da invitare")
    for p in people:
        pid, name = p["id"], p.get("name", "")
        email = first_email(p)
        if not email:
            log(f"  ✗ {name} (id {pid}): nessuna email → Errore")
            try: set_invito(pid, OPT_ERRORE)
            except Exception as e: log(f"    update errore fallito: {e}")
            continue
        try:
            aid = pd_req("POST", "/activities", {
                "subject": ACTIVITY_SUBJECT, "type": ACTIVITY_TYPE, "person_id": pid, "done": 0,
                "note": "Invito recensione Trustpilot (automatico, via automazione nativa)."})["data"]["id"]
            pd_req("PUT", f"/activities/{aid}", {"done": 1})
            set_invito(pid, OPT_INVIATO)
            log(f"  ✓ {name} (id {pid}) <{email}> → attività Trustpilot spuntata → automazione attiva")
            time.sleep(SEND_GAP)
        except Exception as e:
            log(f"  ✗ {name} (id {pid}) <{email}>: ERRORE invio → {e}")
            try: set_invito(pid, OPT_ERRORE)
            except Exception as e2: log(f"    update errore fallito: {e2}")

if __name__ == "__main__":
    main()
