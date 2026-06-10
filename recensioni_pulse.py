#!/usr/bin/env python3
"""PULSE settimanale della sfida recensioni — tiene viva la challenge.
Posta su Slack la classifica aggiornata + una spinta motivazionale (lunedì mattina)."""
import sys, os, json, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rcfg
import recensioni_classifica as cls

TOKEN   = rcfg.secret("SLACK_FU_TOKEN", "~/.config/slack-fu-token")
GENERAL = "C0A4YSS19TP"
DM_DOM  = "U0A4ET9U56E"

def spinta(tot, target, ranking):
    manca = target - tot
    if tot == 0:
        return "La prima recensione di oggi apre la classifica. Chi la porta? 👀"
    if manca <= 0:
        return "🎯 Montepremi *SBLOCCATO*! Ora è battaglia per il 1° posto."
    if not ranking or len(ranking) < 2 or ranking[0][1] == ranking[1][1]:
        return f"Gara apertissima: bastano poche recensioni per prendere la testa. Mancano *{manca}* al montepremi."
    leader, n = ranking[0]
    gap = n - ranking[1][1]
    if gap == 1:
        return f"*{leader}* guida per una sola recensione. Sorpasso a un passo. Mancano *{manca}* al pot."
    return f"*{leader}* è in testa con *{n}*. Chi rimonta? Mancano *{manca}* recensioni al montepremi."

def post(channel):
    m, c = cls.leaderboard()
    ranking = [(n,k) for n,k in c.most_common() if n and n != "—"]
    tot = sum(c.values())
    text = (f"<!channel>\n\n📊  *La settimana riparte — ecco come siamo messi*\n\n{cls.render(m, c)}\n\n"
            f"_{spinta(tot, cls.TARGET, ranking)}_")
    payload = {"channel": channel, "text": f"📊 Classifica recensioni {m} · {tot}/{cls.TARGET}",
               "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]}
    req = urllib.request.Request("https://slack.com/api/chat.postMessage",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json; charset=utf-8"})
    return json.load(urllib.request.urlopen(req)).get("ok")

if __name__ == "__main__":
    ch = sys.argv[1] if len(sys.argv) > 1 else DM_DOM
    print("inviato:", post(ch))
