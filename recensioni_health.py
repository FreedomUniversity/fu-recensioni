#!/usr/bin/env python3
"""Health-check del sistema Recensioni (cloud). Verifica IMAP, stato, classifica, inviti.
Posta un digest nel DM di Domenico. Distingue:
  • DEGRADO (es. IMAP giù): lo mostra ⚠️ ma NON fa fallire il run — il detector ha già il
    suo alert dedicato, inutile spammare rosso ogni giorno e uccidere l'intero digest.
  • CRITICO (token mancante, stato illeggibile): lo mostra 🚨.
Il digest esce SEMPRE (exit 0), così l'informazione arriva anche quando qualcosa è rotto.

Modalità:
  (nessun arg)  → posta il digest nel DM (usato dal cron health.yml).
  --auto        → posta il digest max 1 volta al giorno, finestra 08:00–10:00 Rome
                  (usato dentro il tick, per non dipendere dal cron inaffidabile)."""
import sys, os, json, urllib.request, datetime, imaplib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rcfg
import recensioni_classifica as cls

TOKEN = rcfg.secret("SLACK_FU_TOKEN", "~/.config/deus-user-token")
DM = "U0A4ET9U56E"
SEEN = os.path.join(rcfg.STATE, "trustpilot_emails_seen.json")
SCHED = os.path.join(rcfg.STATE, "drip_schedule.json")
DAILY_MARK = os.path.join(rcfg.STATE, "health_last_day")

def slack(text):
    if not TOKEN:
        return False
    try:
        req = urllib.request.Request("https://slack.com/api/chat.postMessage",
            data=json.dumps({"channel": DM, "text": text}).encode(),
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json; charset=utf-8"})
        return json.load(urllib.request.urlopen(req, timeout=20)).get("ok")
    except Exception:
        return False

def build_digest():
    critici, degradi = [], []
    # 1) IMAP: degrado (il detector ha già il suo alert → qui non facciamo fallire nulla)
    imap_ok = True
    try:
        host = rcfg.secret("IMAP_HOST", "~/.config/trustpilot-imap-creds", key="IMAP_HOST")
        user = rcfg.secret("IMAP_USER", "~/.config/trustpilot-imap-creds", key="IMAP_USER")
        pw   = rcfg.secret("IMAP_PASS", "~/.config/trustpilot-imap-creds", key="IMAP_PASS")
        M = imaplib.IMAP4_SSL(host); M.login(user, pw); M.select("INBOX"); M.logout()
    except Exception as e:
        imap_ok = False
        degradi.append(f"rilevatore recensioni CIECO — IMAP: {str(e)[:80]} "
                       "(rigenera password app Google → segreto IMAP_PASS)")
    # 1b) CONSEGNA: il Flow Klaviyo che manda l'invito è ancora vivo? Se qualcuno lo
    #     mette in pausa/archivia, gli inviti smettono di partire in silenzio. Ora si vede.
    consegna_ok = True
    try:
        ktok = rcfg.secret("KLAVIYO_TOKEN", "~/.config/klaviyo-token")
        if ktok:
            req = urllib.request.Request(
                "https://a.klaviyo.com/api/flows/XiHYbD/",
                headers={"Authorization": f"Klaviyo-API-Key {ktok}", "revision": "2024-10-15"})
            st = json.load(urllib.request.urlopen(req, timeout=20)).get("data", {}).get("attributes", {}).get("status")
            if st != "live":
                consegna_ok = False
                critici.append(f"Flow invito Klaviyo NON live (status={st}) → gli inviti non partono! Riattivalo su Klaviyo.")
    except Exception as e:
        consegna_ok = False
        degradi.append(f"non riesco a verificare il Flow di consegna Klaviyo: {str(e)[:60]}")
    # 2) token Slack (critico) — se manca non arriva nemmeno questo digest
    if not TOKEN:
        critici.append("SLACK_FU_TOKEN mancante")
    # 3) stato leggibile (critico)
    try:
        seen = len(json.load(open(SEEN))) if os.path.exists(SEEN) else 0
    except Exception as e:
        seen = 0; critici.append(f"seen.json illeggibile: {e}")
    m, c = cls.leaderboard(); tot = sum(c.values())
    rank = [(n, k) for n, k in c.most_common() if n and n != "—"]
    lead = " · ".join(f"{n} {k}" for n, k in rank[:3]) or "nessuno"
    # 4) drip da pubblicare
    drip_left = 0
    try:
        if os.path.exists(SCHED):
            drip_left = sum(1 for d in json.load(open(SCHED)) if not d.get("posted"))
    except Exception:
        pass
    # 5) inviti del mese (registro unico condiviso da tutti i canali)
    try:
        ninv = rcfg.invites_this_month()
        flag = " ⚠️ *vicini al limite, valuta upgrade*" if ninv >= 45 else ""
        inviti_line = f"\n📨 Inviti Trustpilot: *{ninv}/50* questo mese{flag}"
    except Exception:
        inviti_line = ""

    now = datetime.datetime.now().strftime("%d/%m %H:%M")
    stato = "🚨 CRITICO" if critici else ("⚠️ DEGRADATO" if degradi else "✅ OK")
    righe = [f"*Recensioni — {stato}* · {now}",
             f"Classifica *{tot}/50* · {lead}{inviti_line}",
             f"Email monitorate: {seen} · Drip da pubblicare: {drip_left} · "
             f"IMAP: {'ok' if imap_ok else 'GIÙ'} · Consegna: {'ok' if consegna_ok else 'GIÙ'}"]
    righe += [f"🚨 {p}" for p in critici]
    righe += [f"⚠️ {d}" for d in degradi]
    return "\n".join(righe)

def main(auto=False):
    if auto:
        oggi = datetime.date.today().isoformat()
        try:
            if open(DAILY_MARK).read().strip() == oggi:
                return
        except Exception:
            pass
        h = (datetime.datetime.utcnow().hour + 2) % 24     # Rome estate ≈ UTC+2
        if not (8 <= h <= 10):                             # finestra mattutina
            return
        open(DAILY_MARK, "w").write(oggi)
    print("digest inviato" if slack(build_digest()) else "digest NON inviato (slack ko)")

if __name__ == "__main__":
    main(auto=("--auto" in sys.argv))
