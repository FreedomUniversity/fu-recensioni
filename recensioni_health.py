#!/usr/bin/env python3
"""Health-check del sistema Recensioni (cloud). Verifica IMAP, stato, classifica.
Posta un digest nel DM di Domenico: ✅ verde se tutto ok, 🚨 rosso se c'è un problema.
Esce con codice 1 se trova problemi (così il run risulta rosso e scatta l'alert del workflow)."""
import sys, os, json, urllib.request, datetime, imaplib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rcfg
import recensioni_classifica as cls

TOKEN = rcfg.secret("SLACK_FU_TOKEN", "~/.config/slack-fu-token")
DM = "U0A4ET9U56E"
SEEN = os.path.join(rcfg.STATE, "trustpilot_emails_seen.json")
SCHED = os.path.join(rcfg.STATE, "drip_schedule.json")

def slack(text):
    req = urllib.request.Request("https://slack.com/api/chat.postMessage",
        data=json.dumps({"channel": DM, "text": text}).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json; charset=utf-8"})
    return json.load(urllib.request.urlopen(req)).get("ok")

def main():
    problems = []
    # 1) IMAP raggiungibile e credenziali valide?
    try:
        host = rcfg.secret("IMAP_HOST", "~/.config/trustpilot-imap-creds", key="IMAP_HOST")
        user = rcfg.secret("IMAP_USER", "~/.config/trustpilot-imap-creds", key="IMAP_USER")
        pw   = rcfg.secret("IMAP_PASS", "~/.config/trustpilot-imap-creds", key="IMAP_PASS")
        M = imaplib.IMAP4_SSL(host); M.login(user, pw); M.select("INBOX"); M.logout()
    except Exception as e:
        problems.append(f"IMAP login fallito: {str(e)[:120]}")
    # 2) token Slack/Pipedrive presenti?
    if not TOKEN: problems.append("SLACK_FU_TOKEN mancante")
    if not rcfg.secret("PIPEDRIVE_TOKEN", "~/.claude_pipedrive_creds", key="PIPEDRIVE_TOKEN"):
        problems.append("PIPEDRIVE_TOKEN mancante")
    # 3) stato leggibile
    try:
        seen = len(json.load(open(SEEN))) if os.path.exists(SEEN) else 0
    except Exception as e:
        seen = 0; problems.append(f"seen.json illeggibile: {e}")
    m, c = cls.leaderboard(); tot = sum(c.values())
    rank = [(n,k) for n,k in c.most_common() if n and n != "—"]
    lead = " · ".join(f"{n} {k}" for n,k in rank[:3]) or "nessuno"
    # 4) drip: quanti ancora da pubblicare
    drip_left = 0
    try:
        if os.path.exists(SCHED):
            drip_left = sum(1 for d in json.load(open(SCHED)) if not d.get("posted"))
    except Exception: pass
    # 5) inviti Trustpilot del mese (esatto: persone distinte invitate) + soglia upgrade
    inviti_line = ""
    try:
        import recensioni_inviti as inv
        _, ninv = inv.count_inviti()
        flag = " ⚠️ *vicini al limite, valuta upgrade*" if ninv >= 45 else ""
        inviti_line = f"\n📨 Inviti Trustpilot: *{ninv}/50* questo mese{flag}"
    except Exception as e:
        inviti_line = ""

    now = datetime.datetime.now().strftime("%d/%m %H:%M")
    if problems:
        slack("🚨 *Recensioni — PROBLEMA* (" + now + ")\n• " + "\n• ".join(problems) +
              f"\n_classifica {tot}/50 · {lead}_")
        print("PROBLEMI:", problems); sys.exit(1)
    slack(f"✅ *Recensioni OK* · {now}\n"
          f"Classifica *{tot}/50* · {lead}{inviti_line}\n"
          f"Email monitorate: {seen} · Drip da pubblicare: {drip_left} · IMAP+token ok")
    print("OK")

if __name__ == "__main__":
    main()
