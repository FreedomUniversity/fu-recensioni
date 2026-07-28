#!/usr/bin/env python3
"""
GHL → INVITO RECENSIONE TRUSTPILOT  (sorgente "acquisto reale")
================================================================
PERCHE' ESISTE (la radice del problema, 23-24/7/2026)
-----------------------------------------------------
Il vecchio meccanismo era SALDATO a Pipedrive: l'invito partiva quando Veronica
spuntava un'attività "Trustpilot" nel CRM. Migrato il CRM su GHL (22/7), quel
trigger è rimasto orfano → gli inviti hanno smesso di partire e nessuno se n'è
accorto (Veronica: "quel link non funziona più").

La radice NON è "l'automazione Pipedrive si è rotta". La radice è che il trigger
degli inviti era accoppiato al CRM di turno e non aveva NESSUN freno. Quindi:
  1) ogni cambio di CRM lo rompe;
  2) qualsiasi import massivo lo trasforma in un cannone.
Prova provata: il 12/7/2026 il travaso Pipedrive→GHL ha portato 390 opportunità
in stage "Vinto" IN UN SOLO GIORNO. Un'automazione ingenua "Vinto → invito"
avrebbe sparato 390 inviti, polverizzando il tetto di 50/mese e bruciando
l'account Trustpilot.

COSA FA QUESTO MODULO
---------------------
Legge da GHL le opportunità entrate in "Vinto" (= acquisto REALE, quindi la
recensione è legittimamente VERIFICATA) e manda l'invito ufficiale via Klaviyo.
Il CRM è dietro un adattatore: se un domani si cambia di nuovo, si tocca solo
`fetch_won()`, non il resto.

I 5 FRENI (ognuno nato da un rischio reale, non teorico)
-------------------------------------------------------
1. WATERMARK   — si parte da una data di attivazione e si guarda solo AVANTI.
                 Mai retro-inviti su storico (il 12/7 non può ripetersi).
2. ANTI-BULK   — se in un giro compaiono più di MAX_BATCH candidati, NON invia:
                 si ferma e allerta. E' il salvavita contro import/migrazioni.
3. QUALITA'    — email valida + scarto record spazzatura/test (in GHL esistono
                 davvero: es. "djdijeidjeijdiejdied <sdsdsdsd@gmail.com>" in Vinto).
4. DEDUP       — registro permanente email→data: una persona è invitata UNA volta
                 nella vita. Idempotente anche se il tick gira due volte.
5. BUDGET      — tetto mensile (piano free Trustpilot = 50 inviti verificati/mese).
                 Si ferma prima del muro e allerta, non fallisce in silenzio.

DRY-RUN DI DEFAULT: non manda nulla finché GHL_WON_LIVE=SI. Mostra cosa farebbe.
"""
import json, os, re, sys, time, datetime, urllib.request, urllib.parse
import rcfg
import invio

# ----------------------------- CONFIG ---------------------------------------
GHL_TOKEN    = rcfg.secret("GHL_TOKEN_FU",    "~/.config/ghl-token-fu-crm-new")
GHL_LOCATION = rcfg.secret("GHL_LOCATION_FU", "~/.config/ghl-location-fu")
SLACK_TOKEN  = rcfg.secret("SLACK_FU_TOKEN",  "~/.config/deus-user-token")
DM_DOMENICO  = "U0A4ET9U56E"

PIPELINE_CLOSER = "2JhnAOIP4zd7HaGHy6JY"          # 02_CLOSER - EVERGREEN
STAGE_VINTO     = "0196ea33-e030-4a98-9ff0-e806d2b11025"
STAGE_VINTO_RATA= "510b753d-a51c-4972-8ac8-35b1c283b037"
STAGES_ACQUISTO = {STAGE_VINTO, STAGE_VINTO_RATA}

LIVE       = os.environ.get("GHL_WON_LIVE", "").strip().upper() == "SI"
MAX_BATCH   = int(os.environ.get("GHL_WON_MAX_BATCH", "15"))   # freno anti-bulk
BUDGET_MESE = int(os.environ.get("TRUSTPILOT_BUDGET", "50"))   # piano free
SOGLIA_ALERT= int(os.environ.get("TRUSTPILOT_SOGLIA", "45"))
SEND_GAP    = 8

WATERMARK = os.path.join(rcfg.STATE, "ghl_watermark.json")     # da dove guardare avanti
# NB: il dedup e il budget usano il REGISTRO UNICO in rcfg (invites_ledger.json),
# condiviso con il canale Tally → una persona è invitata una volta sola da qualsiasi canale.
GETTONI   = os.path.join(rcfg.STATE, "recensioni_gettoni.csv") # attribuzione contest
LOGF      = os.path.join(rcfg.STATE, "ghl_won_source.log")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

# record spazzatura visti davvero in "Vinto": nome senza vocali alternate, mail fittizie
JUNK_EMAIL = re.compile(r"^(test|prova|asd|sdsd|qwe|aaa|xxx|abc)[a-z0-9]*@", re.I)
JUNK_NAME  = re.compile(r"^(test|prova|asd|qwe|xxx|\W*)$", re.I)
EMAIL_OK   = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)

# ----------------------------------------------------------------------------
def log(msg):
    line = f"{datetime.datetime.now().isoformat(timespec='seconds')} | {msg}"
    print(line)
    try:
        with open(LOGF, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

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

def _jload(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default

def _jsave(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(data, open(path, "w"), indent=1, ensure_ascii=False)

# --------------------------- ADATTATORE CRM ---------------------------------
def fetch_won():
    """UNICO punto legato al CRM. Cambia CRM → si riscrive solo questa funzione."""
    if not (GHL_TOKEN and GHL_LOCATION):
        log("✗ credenziali GHL mancanti"); _alert_ghl_giu("credenziali GHL mancanti"); return []
    H = {"Authorization": f"Bearer {GHL_TOKEN}", "Version": "2021-07-28",
         "Accept": "application/json", "User-Agent": UA}   # UA obbligatorio: senza → 403
    out, sa, sid = [], None, None
    for _ in range(12):
        p = {"location_id": GHL_LOCATION, "pipeline_id": PIPELINE_CLOSER, "limit": 100}
        if sa:
            p["startAfter"], p["startAfterId"] = sa, sid
        url = "https://services.leadconnectorhq.com/opportunities/search?" + urllib.parse.urlencode(p)
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=40))
        except Exception as e:
            # Morte silenziosa evitata: se GHL non risponde (token scaduto/403) le vendite
            # smetterebbero di ricevere l'invito senza che nessuno lo sappia. Ora allerta.
            log(f"✗ lettura GHL fallita: {e}")
            if not out:
                _alert_ghl_giu(str(e)[:100])
            break
        opps = d.get("opportunities", [])
        if not opps:
            break
        out += opps
        meta = d.get("meta", {})
        sa, sid = meta.get("startAfter"), meta.get("startAfterId")
        if not sa:
            break
        time.sleep(0.3)
    return [o for o in out if o.get("pipelineStageId") in STAGES_ACQUISTO]

# ------------------------------ CONSEGNA ------------------------------------
def send_invite(email, nome):
    """Ritorna (ok, via). via: 'klaviyo'=consegnato · 'soppresso'=non consegnabile
    (bounce/unsub, non ritentare) · None=Klaviyo giù (ritenta)."""
    return invio.manda_invito(email, nome)

def _alert_consegna_giu():
    """Klaviyo non raggiungibile → inviti in coda (non persi). Alert 1/giorno."""
    try:
        marker = os.path.join(rcfg.STATE, "consegna_down_alert_last")
        oggi = datetime.date.today().isoformat()
        if (open(marker).read().strip() if os.path.exists(marker) else "") == oggi:
            return
        open(marker, "w").write(oggi)
        slack("🟡 *Recensioni — consegna Klaviyo non raggiungibile*\n"
              "Gli inviti restano IN CODA e ripartono da soli appena Klaviyo torna. "
              "Nessun invito perso. Se persiste, controlla lo stato di Klaviyo.")
    except Exception as e:
        log(f"alert consegna giù fallito: {e}")

def _alert_ghl_giu(motivo):
    """Il canale Vendite (GHL) non risponde → nuove vendite non invitate. Alert 1/giorno."""
    try:
        marker = os.path.join(rcfg.STATE, "ghl_down_alert_last")
        oggi = datetime.date.today().isoformat()
        if (open(marker).read().strip() if os.path.exists(marker) else "") == oggi:
            return
        open(marker, "w").write(oggi)
        slack("🔴 *Recensioni — canale Vendite (GHL) GIÙ*\n"
              f"Non riesco a leggere le vendite da GoHighLevel: `{motivo}`\n"
              "Finché non si risolve, i nuovi clienti da vendita NON ricevono l'invito. "
              "Probabile token GHL scaduto → aggiorna il secret `GHL_TOKEN_FU`.")
    except Exception as e:
        log(f"alert GHL giù fallito: {e}")

def gettone(nome, email, chi):
    new = not os.path.exists(GETTONI)
    with open(GETTONI, "a") as f:
        if new:
            f.write("data,nome,email,collaboratore\n")
        f.write(f"{datetime.date.today().isoformat()},\"{nome}\",{email},\"{chi}\"\n")

# -------------------------------- MOTORE ------------------------------------
def main():
    wm = _jload(WATERMARK, {})
    inizio = wm.get("from")
    if not inizio:
        # PRIMA ACCENSIONE: si fissa il paletto a ORA e si guarda solo avanti.
        # Niente retro-inviti sullo storico: è il freno che rende impossibile un altro 12/7.
        inizio = datetime.datetime.now(datetime.timezone.utc).isoformat()
        _jsave(WATERMARK, {"from": inizio, "armed": datetime.date.today().isoformat()})
        log(f"⚙️  PRIMA ACCENSIONE — watermark fissato a {inizio}. Si guarda solo in avanti.")
        log("   Nessun invito su storico (per scelta: evita il disastro da import massivo).")
        return

    won = fetch_won()
    log(f"GHL: {len(won)} opportunità in stage acquisto (Vinto / Vinto-Rata)")

    # --- selezione: solo NUOVI vinti dopo il watermark, non già invitati -----
    cand, scartati = [], {"vecchi": 0, "gia_invitati": 0, "email_ko": 0, "spazzatura": 0}
    for o in won:
        quando = o.get("lastStatusChangeAt") or o.get("updatedAt") or ""
        if quando <= inizio:
            scartati["vecchi"] += 1; continue
        c = o.get("contact") or {}
        email = (c.get("email") or "").strip().lower()
        nome  = (o.get("name") or c.get("name") or "").strip()
        if not EMAIL_OK.match(email):
            scartati["email_ko"] += 1; continue
        if JUNK_EMAIL.match(email) or JUNK_NAME.match(nome) or len(nome) < 2:
            scartati["spazzatura"] += 1
            log(f"   ⚠ scartato record spazzatura: {nome!r} <{email}>"); continue
        if rcfg.invite_seen(email):            # dedup cross-canale (GHL + Tally)
            scartati["gia_invitati"] += 1; continue
        # ATTRIBUZIONE: volutamente "Automatico", NON una persona.
        # Questo invito nasce da una VENDITA, non da qualcuno che è andato a
        # chiedere la recensione. Scriverlo come gettone di un collaboratore
        # gonfierebbe la classifica del contest con recensioni non guadagnate.
        # Il contest resta puro: conta solo il modulo Tally (chi si dà da fare).
        cand.append({"email": email, "nome": nome, "quando": quando,
                     "chi": "Automatico (vendita)"})

    log(f"candidati NUOVI: {len(cand)}  | scartati: {scartati}")
    if not cand:
        return

    # --- FRENO 1: anti-bulk (il salvavita contro migrazioni/import) ----------
    if len(cand) > MAX_BATCH:
        msg = (f"🚨 *Recensioni — FRENO ANTI-BULK SCATTATO*\n"
               f"Sono comparsi *{len(cand)} nuovi 'Vinto'* in un colpo solo (soglia {MAX_BATCH}).\n"
               f"Non ho inviato NIENTE: sembra un import/migrazione, non vendite vere.\n"
               f"Se sono acquisti reali, alza `GHL_WON_MAX_BATCH`. Altrimenti ignora.")
        log(f"🚨 ANTI-BULK: {len(cand)} candidati > soglia {MAX_BATCH} → STOP, zero invii")
        slack(msg)
        return

    # --- FRENO 2: budget mensile (tetto piano Trustpilot, registro UNICO) ----
    mese = datetime.date.today().strftime("%Y-%m")
    usati = rcfg.invites_this_month()          # conta TUTTI i canali, non solo GHL
    spazio = BUDGET_MESE - usati
    log(f"budget mese {mese}: {usati}/{BUDGET_MESE} usati → spazio {spazio}")
    if spazio <= 0:
        slack(f"🚨 *Recensioni — TETTO MENSILE RAGGIUNTO* ({usati}/{BUDGET_MESE}).\n"
              f"{len(cand)} clienti in attesa: restano in coda al mese prossimo.\n"
              f"Se servono ora → upgrade piano Trustpilot.")
        return
    if len(cand) > spazio:
        log(f"⚠ taglio a {spazio}: gli altri {len(cand)-spazio} restano in coda (non persi)")
        cand = sorted(cand, key=lambda x: x["quando"])[:spazio]

    # --- invio ---------------------------------------------------------------
    if not LIVE:
        log("🔎 DRY-RUN (GHL_WON_LIVE non è 'SI') — ecco cosa farei, senza mandare nulla:")
        for c in cand:
            log(f"   → INVITEREI: {c['nome']} <{c['email']}>  (vinto {c['quando'][:10]})")
        log(f"🔎 DRY-RUN: {len(cand)} inviti simulati. Per attivare: GHL_WON_LIVE=SI")
        return

    ok = 0; falliti = 0
    for c in cand:
        esito, via = send_invite(c["email"], c["nome"])
        if esito:
            rcfg.invite_record(c["email"], "ghl")   # registro unico, salvato SUBITO
            gettone(c["nome"], c["email"], c["chi"])
            ok += 1
            log(f"   ✓ invito → {c['nome']} <{c['email']}>")
        elif via == "soppresso":
            rcfg.invite_record(c["email"], "soppresso")  # non consegnabile: non ritentare
            log(f"   ⛔ NON CONSEGNABILE (indirizzo soppresso su Klaviyo) → {c['nome']} <{c['email']}>")
        else:
            falliti += 1
            log(f"   ⏳ IN CODA (Klaviyo non raggiungibile) → {c['nome']} <{c['email']}> (riprovo al giro dopo)")
        time.sleep(SEND_GAP)
    if falliti:
        _alert_consegna_giu()

    usati_ora = usati + ok
    log(f"✅ inviati {ok}/{len(cand)} | mese: {usati_ora}/{BUDGET_MESE}")
    if usati_ora >= SOGLIA_ALERT:
        slack(f"⚠️ *Recensioni — vicino al tetto*: {usati_ora}/{BUDGET_MESE} inviti questo mese.\n"
              f"Valuta l'upgrade del piano Trustpilot prima di restare a secco.")

if __name__ == "__main__":
    main()
