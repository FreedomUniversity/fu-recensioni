#!/usr/bin/env python3
"""TRAGUARDI TRUSTPILOT — festa quando il TOTALE recensioni tocca una cifra tonda.
Due livelli:
  • LEGGERO  → ogni multiplo di 10 (110, 120, 130, 140…): messaggio discreto, niente @channel.
  • GROSSO   → ogni multiplo di 50 (100, 150, 200, 250…): @channel + CTA "Porta una recensione".
HOLD: i traguardi in HOLD_MILESTONES pingano Domenico nel DM e restano "pending" finché non approva.
SKIP: i traguardi in SKIP_MILESTONES vengono saltati in silenzio (stand-by). Attuale: SKIP={100}.
Trustpilot non espone il totale via API pubblica (Cloudflare/AWS-WAF blocca) → contatore interno:
base reale letta una volta + 1 ad ogni nuova recensione vista dal detector (qualsiasi stella).
Uso CLI:  seed <N>  |  preview <N>  |  approve [N]  |  (nessun arg = stato)"""
import sys, os, json, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rcfg

TOTAL_FILE = os.path.join(rcfg.STATE, "trustpilot_total.json")
GENERAL = "C0A4YSS19TP"
DOMENICO_DM = "U0A4ET9U56E"
PROFILE = "https://it.trustpilot.com/review/freedomuniversity.it"
PORTA   = "https://form.freedomuniversity.it/recensione"
STEP = 10                 # festeggia ogni 10 recensioni
BIG  = 50                 # ogni multiplo di 50 = festa GROSSA (@channel + CTA)
HOLD_MILESTONES = set()   # questi pingano Domenico e aspettano ok prima di uscire su #general
SKIP_MILESTONES = {100}    # questi vengono SALTATI in silenzio (nessuna festa, nessun ping)

def _load():
    try: return json.load(open(TOTAL_FILE))
    except Exception: return {"total": None, "last_milestone": 0, "pending": None}
def _save(d): json.dump(d, open(TOTAL_FILE, "w"))

def seed(total):
    """imposta la base UNA VOLTA (numero reale letto su Trustpilot)."""
    total = int(total)
    d = {"total": total, "last_milestone": (total // STEP) * STEP, "pending": None}
    _save(d); return d

def _build(n):
    """ritorna (fallback_text, blocks) del messaggio traguardo n, scegliendo il livello."""
    big = (n % BIG == 0)
    if big:
        text = (f"<!channel>\n\n"
                f"🎉  *{n} recensioni su Trustpilot*  🎉\n\n"
                f"{n} persone si sono fermate a lasciarci una parola. Grazie.\n"
                f"È il segno che stiamo facendo le cose per bene — e ci tiene a farle meglio.\n"
                f"Una alla volta, andiamo avanti. 🙏")
        elements = [
            {"type": "button", "style": "primary",
             "text": {"type": "plain_text", "text": "⭐  Vedi su Trustpilot", "emoji": True}, "url": PROFILE},
            {"type": "button",
             "text": {"type": "plain_text", "text": "✍️  Porta una recensione", "emoji": True}, "url": PORTA},
        ]
        fb = f"🎉 TRAGUARDO: {n} recensioni Trustpilot"
    else:
        text = (f"⭐  *{n} recensioni* su Trustpilot.\n"
                f"Un'altra persona che ce l'ha fatta e ha voluto dirlo. Grazie, sotto la prossima. 💪")
        elements = [
            {"type": "button", "style": "primary",
             "text": {"type": "plain_text", "text": "⭐  Vedi su Trustpilot", "emoji": True}, "url": PROFILE},
        ]
        fb = f"⭐ {n} recensioni Trustpilot"
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}},
              {"type": "actions", "elements": elements}]
    return fb, blocks

def _send(channel, fb, blocks):
    token = rcfg.secret("SLACK_FU_TOKEN", "~/.config/slack-fu-token")
    body = {"channel": channel, "text": fb, "blocks": blocks}
    req = urllib.request.Request("https://slack.com/api/chat.postMessage", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"})
    return json.load(urllib.request.urlopen(req, timeout=20)).get("ok")

def _post(n, channel=GENERAL):
    fb, blocks = _build(n)
    return _send(channel, fb, blocks)

def _dm_hold(n):
    """avvisa Domenico nel DM che il traguardo n è pronto ma in HOLD: aspetta il suo ok."""
    fb, blocks = _build(n)
    intro = {"type": "context", "elements": [{"type": "mrkdwn", "text":
        f":bell: *Traguardo {n} raggiunto* — è il primo grosso, in HOLD come hai chiesto.\n"
        f"Sotto come uscirebbe su #general. Dammi l'ok a Pegaso e lo pubblico. "
        f"_(le prossime 150 / 200… partono da sole)_"}]}
    return _send(DOMENICO_DM, f"🔔 Traguardo {n}: pronto, aspetto ok", [intro] + blocks)

def bump(channel=GENERAL):
    """+1 al totale. Festeggia ogni nuovo multiplo di 10. I milestone in HOLD pingano il DM
    e mettono in 'pending' (blocca le feste successive finché non si approva). Inerte senza base."""
    d = _load()
    if d.get("total") is None:
        return None
    if d.get("pending"):                 # c'è un traguardo in attesa di ok → conta ma non festeggia
        d["total"] += 1; _save(d); return d["total"]
    d["total"] += 1
    new_m = (d["total"] // STEP) * STEP
    if new_m >= STEP and new_m > d.get("last_milestone", 0):
        if new_m in SKIP_MILESTONES:
            d["last_milestone"] = new_m          # traguardo saltato in silenzio (stand-by)
        elif new_m in HOLD_MILESTONES:
            try:
                _dm_hold(new_m); d["last_milestone"] = new_m; d["pending"] = new_m
            except Exception:
                pass                     # ping fallito → riprova al prossimo tick
        else:
            try:
                _post(new_m, channel); d["last_milestone"] = new_m
            except Exception:
                pass
    _save(d)
    return d["total"]

def approve(n=None):
    """pubblica su #general un traguardo tenuto in HOLD (default: quello pending)."""
    d = _load()
    n = int(n) if n else d.get("pending")
    if not n:
        return "nessun traguardo in attesa"
    ok = _post(n)
    if ok:
        if d.get("pending") == n: d["pending"] = None
        if n > d.get("last_milestone", 0): d["last_milestone"] = n
        _save(d)
    return f"festa {n} pubblicata su #general: {ok}"

if __name__ == "__main__":
    a = sys.argv
    if len(a) >= 3 and a[1] == "seed":
        print("base impostata:", seed(a[2]))
    elif len(a) >= 3 and a[1] == "preview":
        print("anteprima:", _post(int(a[2]), os.environ.get("PREVIEW_CH", DOMENICO_DM)))
    elif len(a) >= 2 and a[1] == "approve":
        print(approve(a[2] if len(a) >= 3 else None))
    else:
        print(_load())
