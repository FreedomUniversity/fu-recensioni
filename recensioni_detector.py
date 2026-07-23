#!/usr/bin/env python3
"""RILEVATORE RECENSIONI TRUSTPILOT (cloud) — legge le email di notifica Trustpilot,
riconosce recensore/stelle/testo, abbina chi l'ha procurata, aggiorna la classifica e
fa partire la FESTA su Slack. Idempotente per Message-ID. Stelle ignote o <3 → niente
festa, niente conteggio, alert privato a Domenico."""
import os, re, json, sys, imaplib, email, subprocess, datetime, html as htmllib, urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rcfg

SEEN        = os.path.join(rcfg.STATE, "trustpilot_emails_seen.json")
INIT_MARKER = os.path.join(rcfg.STATE, "trustpilot_detector_initialized")
RAW_DIR     = os.path.join(rcfg.STATE, "trustpilot_emails_raw")
VERIF_CSV   = os.path.join(rcfg.STATE, "recensioni_verificate.csv")
LOG         = os.path.join(rcfg.STATE, "recensioni_detector.log")
GETTONI     = os.path.join(rcfg.STATE, "recensioni_gettoni.csv")
FESTA       = os.path.join(rcfg.ROOT, "recensioni_festa.py")
FESTA_CHANNEL = "C0A4YSS19TP"   # #general
DM_DOM     = "U0A4ET9U56E"      # DM Domenico per alert privati
MIN_STARS  = 3                  # < 3 stelle: NON pubblicata, NON contata, solo alert privato
SINCE_DAYS = 30
PROCURATA_KEY = "b20c86b72f92ee5e9498e82bcd93f764ef405144"

def log(m):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    line=f"{datetime.datetime.now().isoformat(timespec='seconds')} | {m}"
    print(line); open(LOG,"a").write(line+"\n")

def slack_dm(text):
    """alert privato a Domenico (recensioni negative / da gestire)."""
    try:
        tok = rcfg.secret("SLACK_FU_TOKEN", "~/.config/slack-fu-token")
        body = json.dumps({"channel": DM_DOM, "text": text}).encode()
        req = urllib.request.Request("https://slack.com/api/chat.postMessage", data=body,
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=utf-8"})
        urllib.request.urlopen(req, timeout=20)
    except Exception as e:
        log(f"  alert DM fallito: {e}")

def load_cfg():
    host = rcfg.secret("IMAP_HOST", "~/.config/trustpilot-imap-creds", key="IMAP_HOST")
    user = rcfg.secret("IMAP_USER", "~/.config/trustpilot-imap-creds", key="IMAP_USER")
    pw   = rcfg.secret("IMAP_PASS", "~/.config/trustpilot-imap-creds", key="IMAP_PASS")
    if not (host and user and pw): return None
    return {"IMAP_HOST": host, "IMAP_USER": user, "IMAP_PASS": pw}

def load_seen():
    try: return set(json.load(open(SEEN)))
    except Exception: return set()
def save_seen(s): json.dump(sorted(s), open(SEEN,"w"))

def body_text(msg):
    plain=html=""
    if msg.is_multipart():
        for p in msg.walk():
            ct=p.get_content_type()
            if ct=="text/plain" and not plain:
                plain=p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8","ignore")
            elif ct=="text/html" and not html:
                html=p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8","ignore")
    else:
        payload=msg.get_payload(decode=True)
        if payload: plain=payload.decode(msg.get_content_charset() or "utf-8","ignore")
    if plain.strip(): return plain
    t=re.sub(r"<(script|style)[^>]*>.*?</\1>"," ",html,flags=re.S|re.I)
    t=re.sub(r"<br\s*/?>","\n",t,flags=re.I); t=re.sub(r"</p>","\n",t,flags=re.I)
    t=re.sub(r"<[^>]+>"," ",t); t=htmllib.unescape(t)
    return re.sub(r"[ \t]+"," ",t)

def parse_review(text):
    out={"name":None,"stars":None,"title":None,"text":None,"url":None}
    mu=re.search(r"https://[a-z]{2}\.trustpilot\.com/reviews/[a-z0-9]+", text, re.I)
    if mu: out["url"]=mu.group(0)
    m=re.search(r"(\d)\s*(?:su|/|out of)\s*5", text, re.I) or re.search(r"(\d)\s*stell", text, re.I)
    if m: out["stars"]=int(m.group(1))
    elif "★" in text: out["stars"]=min(5,text.count("★"))
    for pat in [r"([A-Za-zÀ-ÿ'’\.\-]+(?:\s+[A-Za-zÀ-ÿ'’\.\-]+){0,3})\s+ha\s+(?:scritto|lasciato)\s+una\s+(?:nuova\s+)?recensione",
                r"recensione\s+da\s+([A-Za-zÀ-ÿ'’\.\- ]{2,40}?)(?:\s+a\s+\d|[\.,\n])",
                r"from\s+([A-Za-zÀ-ÿ'’\.\- ]{2,40}?)(?:\s+-|\s+a\s+\d|[\.,\n])"]:
        mm=re.search(pat, text, re.I)
        if mm:
            nm=mm.group(1).strip(" .,;:'\"’")
            if nm.isupper(): nm=nm.title()
            out["name"]=nm; break
    mt=re.search(r"recensione a\s*\d+\s*stell[ae]?\s*di\s+[^:]+:\s*(.+?)\s*(?:Leggi la recensione|Leggi e rispondi|Leggi la|https?://)",
                 text, re.S|re.I)
    if mt:
        out["text"]=re.sub(r"\s+"," ", mt.group(1)).strip()
    return out

def _pd():
    return (rcfg.secret("PIPEDRIVE_TOKEN", "~/.claude_pipedrive_creds", key="PIPEDRIVE_TOKEN"), rcfg.PD_BASE)

def find_collaboratore(name):
    """Attribuisce SOLO se sicuri (gettoni: nome identico o ≥2 token significativi in comune).
    In caso di dubbio ritorna '—' (Corsista): meglio non attribuire che rubare crediti/premi."""
    if not name: return "—"
    nl=name.lower().strip()
    ntoks=set(t for t in re.split(r"\s+", nl) if len(t)>=3)  # ignora 'di','la','el'...
    if os.path.exists(GETTONI):
        import csv
        rows=[r for r in csv.DictReader(open(GETTONI)) if (r.get("collaboratore") or "").strip()]
        def most_recent(cands):
            # se più persone hanno lo stesso nome, vince l'INVITO PIÙ RECENTE
            # (è quello che ha generato la recensione appena arrivata)
            return max(cands, key=lambda r: r.get("data") or "").get("collaboratore") if cands else None
        # pass 1: nome identico
        exact=[r for r in rows if (r.get("nome") or "").lower().strip()==nl]
        if exact: return most_recent(exact) or "—"
        # pass 2: sottoinsieme di token significativi ("Angelo" ⊆ "Angelo Labella"),
        # immune a 'di/la' perché i token <3 lettere sono scartati
        subset=[]
        for r in rows:
            rtoks=set(t for t in re.split(r"\s+", (r.get("nome") or "").lower().strip()) if len(t)>=3)
            if rtoks and ntoks and (rtoks<=ntoks or ntoks<=rtoks): subset.append(r)
        if subset: return most_recent(subset) or "—"
    # Pipedrive: solo se il nome trovato COINCIDE esattamente (niente fuzzy che ruba crediti)
    try:
        PT,PB=_pd()
        u=f"{PB}/persons/search?{urllib.parse.urlencode({'term':name,'limit':1,'api_token':PT})}"
        d=json.load(urllib.request.urlopen(u,timeout=20))
        items=(d.get("data") or {}).get("items") or []
        if items and (items[0]["item"].get("name") or "").lower().strip()==nl:
            pid=items[0]["item"]["id"]
            u2=f"{PB}/persons/{pid}?{urllib.parse.urlencode({'api_token':PT})}"
            p=json.load(urllib.request.urlopen(u2,timeout=20))["data"]
            return p.get(PROCURATA_KEY) or "—"
    except Exception:
        pass
    return "—"

def write_verif(name,stars,collab,date):
    new=not os.path.exists(VERIF_CSV)
    with open(VERIF_CSV,"a") as f:
        if new: f.write("data,reviewer_name,stelle,collaboratore,email\n")
        f.write(f"{date},\"{name}\",{stars or ''},\"{collab}\",\n")

def fire_festa(name,stars,collab,text,url=None):
    subprocess.run(["python3",FESTA,name,str(stars or 5),collab,(text or "")[:300],FESTA_CHANNEL,url or ""],timeout=40)

def main():
    cfg=load_cfg()
    if not cfg:
        print("⛔ Manca l'accesso IMAP (IMAP_HOST/USER/PASS)."); return
    try:
        M=imaplib.IMAP4_SSL(cfg["IMAP_HOST"]); M.login(cfg["IMAP_USER"],cfg["IMAP_PASS"]); M.select("INBOX")
    except Exception as e:
        # MAI PIU' IN SILENZIO. Questo errore ha reso il detector cieco dal 9/6 al 23/7
        # (45 giorni: zero recensioni rilevate, zero feste, contatore fermo) e nessuno
        # se n'e' accorto perche' qui si faceva solo log+return. Ora allerta.
        # Freno anti-spam: massimo 1 avviso al giorno (il tick gira ogni 10 min).
        log(f"IMAP login fallito: {e}")
        try:
            marker = os.path.join(rcfg.STATE, "imap_alert_last")
            oggi = datetime.date.today().isoformat()
            gia = open(marker).read().strip() if os.path.exists(marker) else ""
            if gia != oggi:
                open(marker, "w").write(oggi)
                slack_dm(
                    "🚨 *Recensioni — IL RILEVATORE È CIECO*\n"
                    f"Non riesco a leggere la casella `{cfg.get('IMAP_USER','?')}`:\n"
                    f"`{e}`\n\n"
                    "Finché non si risolve: *nessuna recensione viene rilevata, "
                    "nessuna festa parte, il contatore resta fermo.*\n"
                    "👉 Fix: genera una nuova *password per le app* Google "
                    "(myaccount.google.com → Sicurezza → Password per le app) e aggiornala "
                    "nel segreto `IMAP_PASS` del repo `fu-recensioni`."
                )
        except Exception as e2:
            log(f"alert IMAP fallito: {e2}")
        return
    since=(datetime.date.today()-datetime.timedelta(days=SINCE_DAYS)).strftime("%d-%b-%Y")
    typ,data=M.search(None,f'(SINCE {since} FROM "trustpilot")')
    ids=data[0].split()
    seen=load_seen(); nuovi=0
    prime = not os.path.exists(INIT_MARKER)
    if prime: log("PRIME (1ª esecuzione): segno le esistenti come viste, senza festeggiarle.")
    os.makedirs(RAW_DIR,exist_ok=True)
    for i in ids:
        t,d=M.fetch(i,"(RFC822)")
        msg=email.message_from_bytes(d[0][1])
        mid=msg.get("Message-ID") or msg.get("Date")
        if mid in seen: continue
        if prime:
            seen.add(mid); save_seen(seen); continue
        text=body_text(msg)
        rv=parse_review(text)
        # TRAGUARDI: ogni recensione VERA (ha l'url recensione) conta nel totale Trustpilot,
        # anche <3★ o senza nome — festa "cifra tonda" ogni 10. Inerte finché non c'è la base.
        if rv.get("url"):
            try:
                import recensioni_milestone as _ms; _ms.bump()
            except Exception as e: log(f"  milestone errore: {e}")
        if not rv["name"]:
            open(os.path.join(RAW_DIR,f"{i.decode()}.txt"),"w").write(text[:5000])
            log(f"  ⚠️ email {mid}: parsing nome fallito → salvata grezza per rifinire")
            seen.add(mid); save_seen(seen); continue
        # GUARDIA: stelle ignote O sotto le 3 → mai pubbliche, mai contate, solo alert privato.
        if rv["stars"] is None or rv["stars"] < MIN_STARS:
            motivo = "⭐ stelle non lette" if rv["stars"] is None else f"{rv['stars']}★ (sotto le {MIN_STARS})"
            slack_dm(f"⚠️ *Recensione da gestire a mano* — *{rv['name']}* · {motivo}\n"
                     f"> {(rv['text'] or '(testo non letto)')[:400]}\n{rv.get('url') or ''}")
            log(f"  ⛔ {rv['name']} [{motivo}] → NON pubblicata/contata, alert privato a Domenico")
            seen.add(mid); save_seen(seen); continue
        collab=find_collaboratore(rv["name"])
        date=datetime.date.today().isoformat()
        write_verif(rv["name"],rv["stars"],collab,date)
        try: fire_festa(rv["name"],rv["stars"],collab,rv["text"] or rv["title"] or "",rv.get("url"))
        except Exception as e: log(f"  festa errore: {e}")
        log(f"  ✓ recensione: {rv['name']} {rv['stars']}★ → procurata da {collab} → classifica+festa")
        nuovi+=1; seen.add(mid); save_seen(seen)
    M.logout()
    if prime:
        open(INIT_MARKER,"w").write(datetime.datetime.now().isoformat())
        log("PRIME completato: esistenti segnate come viste. Da ora celebro solo le NUOVE.")
    if nuovi: log(f"FINE: {nuovi} nuove recensioni processate")

if __name__=="__main__":
    main()
