#!/usr/bin/env python3
"""GUARDIANO INVITI TRUSTPILOT — conta gli inviti del mese e avvisa prima del limite 50.
Fonte UNICA: il registro inviti condiviso (rcfg.invites_this_month) alimentato da TUTTI
i canali (GHL "Vinto" + modulo Tally). Prima si contavano le attività Pipedrive, ma con
la migrazione a GHL quel conteggio era diventato parziale/fuorviante. Ora è coerente.
Vicino a 50 → alert nel DM Domenico (1 volta al giorno) per l'upgrade del piano."""
import sys, os, json, urllib.request, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rcfg

SLACK = rcfg.secret("SLACK_FU_TOKEN", "~/.config/deus-user-token")
DM = "U0A4ET9U56E"
LIMIT  = 50             # limite piano free
WARN   = 45             # soglia di allarme → upgrade
LINK   = "https://businessapp.b2b.trustpilot.com/invitations/invitation-history"
STATE_F = os.path.join(rcfg.STATE, "invite_alert.json")

def count_inviti():
    """Ritorna (mese, n) leggendo il registro unico. Stessa firma di prima."""
    return datetime.date.today().strftime("%Y-%m"), rcfg.invites_this_month()

def slack(text):
    urllib.request.urlopen(urllib.request.Request("https://slack.com/api/chat.postMessage",
        data=json.dumps({"channel": DM, "text": text}).encode(),
        headers={"Authorization": f"Bearer {SLACK}", "Content-Type": "application/json; charset=utf-8"}), timeout=20)

def main():
    mese, n = count_inviti()
    print(f"inviti {mese}: {n}/{LIMIT}")
    try: st = json.load(open(STATE_F))
    except Exception: st = {}
    today = datetime.date.today().isoformat()
    if n >= WARN and st.get("date") != today:
        livello = "🚨 LIMITE QUASI RAGGIUNTO" if n >= 48 else "⚠️ Vicini al limite"
        slack(f"{livello} — *Inviti Trustpilot {n}/{LIMIT}* questo mese.\n"
              f"*Fai l'upgrade del piano* per non bloccare i nuovi inviti recensione.\n{LINK}")
        json.dump({"date": today, "count": n}, open(STATE_F, "w"))
        print("alert inviato")

if __name__ == "__main__":
    main()
