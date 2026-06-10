#!/usr/bin/env python3
"""Festa Slack per nuova recensione — design pulito (1 solo divisore).
Uso: recensioni_festa.py "<reviewer>" <stelle> "<collaboratore>" "<testo>" [channel] [url]"""
import sys, os, json, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rcfg
import recensioni_classifica as cls

TOKEN = rcfg.secret("SLACK_FU_TOKEN", "~/.config/slack-fu-token")
GENERAL = "C0A4YSS19TP"          # #general
PROFILE_URL = "https://it.trustpilot.com/review/freedomuniversity.it"  # profilo pubblico FU
TALLY_URL   = "https://form.freedomuniversity.it/recensione"           # modulo per portare una recensione

def build(reviewer, stars, collab, text="", url=None, show_collab=True):
    """costruisce (fallback_text, blocks) della festa — riusabile da post() e schedule()."""
    m, c = cls.leaderboard()
    medals = ["🥇","🥈","🥉"]
    rank = [(n,cnt) for n,cnt in c.most_common() if n and n != "—"][:3]
    lead = "   ".join(f"{medals[i]} {n} *{cnt}*" for i,(n,cnt) in enumerate(rank)) or "_nessuna ancora_"
    star = "⭐"*int(stars)
    tot = sum(c.values())
    quote = "\n".join(f"> _{l}_" for l in (text or "").splitlines() if l.strip()) if text else ""

    main = f"<!channel>\n\n*{reviewer}* ha lasciato una recensione   {star}"
    if quote:
        main += f"\n\n{quote}"
    if show_collab:
        if collab and collab not in ("—", "?", ""):
            main += f"\n\n🙌  Portata da *{collab}* — grande! 🔥"
        else:
            main += f"\n\n🎓  Arrivata da un Corsista — grazie!"

    blocks = [
      {"type":"header","text":{"type":"plain_text","text":"🎉  NEW RECENSIONE TRUSTPILOT","emoji":True}},
      {"type":"section","text":{"type":"mrkdwn","text":main}},
      {"type":"actions","elements":[
        {"type":"button","style":"primary",
         "text":{"type":"plain_text","text":"⭐  Leggi su Trustpilot","emoji":True},
         "url": url or PROFILE_URL},
        {"type":"button",
         "text":{"type":"plain_text","text":"✍️  Porta una Recensione","emoji":True},
         "url": TALLY_URL}]},
      {"type":"context","elements":[{"type":"mrkdwn",
        "text":f"🏆 *Classifica {m}* · {tot}/50 recensioni · 🥇€120 🥈€80\n{lead}"}]},
    ]
    return f"🎉 NEW RECENSIONE TRUSTPILOT — {reviewer} {int(stars)}★", blocks

def _send(payload):
    req = urllib.request.Request(payload.pop("_url"),
        data=json.dumps(payload).encode(),
        headers={"Authorization":f"Bearer {TOKEN}","Content-Type":"application/json; charset=utf-8"})
    return json.load(urllib.request.urlopen(req))

def post(channel, reviewer, stars, collab, text="", url=None, show_collab=True):
    fb, blocks = build(reviewer, stars, collab, text, url, show_collab)
    return _send({"_url":"https://slack.com/api/chat.postMessage",
                  "channel":channel, "text":fb, "blocks":blocks}).get("ok")

def schedule(channel, post_at, reviewer, stars, collab, text="", url=None, show_collab=True):
    fb, blocks = build(reviewer, stars, collab, text, url, show_collab)
    return _send({"_url":"https://slack.com/api/chat.scheduleMessage",
                  "channel":channel, "post_at":int(post_at), "text":fb, "blocks":blocks})

if __name__ == "__main__":
    rev, st, col, text = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    ch  = sys.argv[5] if len(sys.argv) > 5 else GENERAL
    url = sys.argv[6] if len(sys.argv) > 6 else None
    print("inviato:", post(ch, rev, st, col, text, url))
