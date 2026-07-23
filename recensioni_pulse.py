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

WEEK_MARK = os.path.join(rcfg.STATE, "pulse_last_week")

def _week():
    import datetime
    return datetime.date.today().strftime("%G-W%V")

def _gia_uscita():
    try:
        return open(WEEK_MARK).read().strip() == _week()
    except Exception:
        return False

def _segna():
    try:
        open(WEEK_MARK, "w").write(_week())
    except Exception:
        pass

if __name__ == "__main__":
    # Modalità --auto: pensata per girare DENTRO il tick (ogni 10 min, trigger Make
    # ridondante e affidabile) invece di dipendere dal cron GitHub, che è inaffidabile
    # e ha già saltato lunedì 20/7/2026 lasciando il team senza classifica.
    # Il marker settimanale rende impossibile il doppio invio anche se scatta pure il cron.
    if "--auto" in sys.argv:
        import datetime
        os.environ.setdefault("TZ", "Europe/Rome")
        try:
            time_ok = datetime.datetime.now(
                datetime.timezone(datetime.timedelta(hours=2)))  # Rome estate
        except Exception:
            time_ok = datetime.datetime.now()
        if time_ok.weekday() != 0 or time_ok.hour < 9:
            sys.exit(0)                      # non è lunedì mattina → zitto
        if _gia_uscita():
            sys.exit(0)                      # già uscita questa settimana → zitto
        ok = post(GENERAL)
        if ok:
            _segna()
        print("pulse auto inviato:", ok)
        sys.exit(0)

    ch = sys.argv[1] if len(sys.argv) > 1 else DM_DOM
    ok = post(ch)
    if ch == GENERAL and ok:
        _segna()                             # anche via cron: marca la settimana
    print("inviato:", ok)
