#!/usr/bin/env python3
"""GUARDIANO INVITI TRUSTPILOT — conta gli inviti del mese e avvisa prima del limite 50.
Conteggio ESATTO: persone DISTINTE con un'attività "Trustpilot" completata nel mese
(= 1 invito per destinatario, combacia col contatore Trustpilot). Quando ci si avvicina
a 50 manda un alert nel DM Domenico (1 volta al giorno) per fare l'upgrade del piano."""
import sys, os, json, urllib.request, urllib.parse, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rcfg

PT = rcfg.secret("PIPEDRIVE_TOKEN", "~/.claude_pipedrive_creds", key="PIPEDRIVE_TOKEN")
PB = rcfg.PD_BASE
SLACK = rcfg.secret("SLACK_FU_TOKEN", "~/.config/slack-fu-token")
DM = "U0A4ET9U56E"
FILTER = 10198          # filtro attività "Trustpilot"
LIMIT  = 50             # limite piano free
WARN   = 45             # soglia di allarme → upgrade
LINK   = "https://businessapp.b2b.trustpilot.com/invitations/invitation-history"
STATE_F = os.path.join(rcfg.STATE, "invite_alert.json")

def count_inviti():
    mese = datetime.date.today().strftime("%Y-%m")
    persons = set(); start = 0
    while True:
        u = f"{PB}/activities?{urllib.parse.urlencode({'filter_id':FILTER,'limit':500,'start':start,'api_token':PT})}"
        d = json.load(urllib.request.urlopen(u, timeout=30)); data = d.get("data") or []
        for a in data:
            if a.get("done") and (a.get("marked_as_done_time","") or "").startswith(mese):
                persons.add(a.get("person_id"))
        more = (d.get("additional_data") or {}).get("pagination", {})
        if more.get("more_items_in_collection"): start = more.get("next_start"); continue
        break
    return mese, len(persons)

def slack(text):
    urllib.request.urlopen(urllib.request.Request("https://slack.com/api/chat.postMessage",
        data=json.dumps({"channel": DM, "text": text}).encode(),
        headers={"Authorization": f"Bearer {SLACK}", "Content-Type": "application/json; charset=utf-8"}), timeout=20)

def main():
    if not PT:
        print("PIPEDRIVE_TOKEN mancante"); return
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
