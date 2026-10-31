#!/usr/bin/env python3
"""GUARDIANO recensioni — gira su GitHub Actions. Due istanze (1 e 2) che si sorvegliano
a vicenda + sorvegliano il tick + auto-riparano. Read-only sullo stato: NON committa nulla.
Cosa fa ad ogni giro:
  1. il TICK ha girato di recente? se no → ri-dispatcha 'tick' (risveglio) + alert
  2. i trigger Make A/B sono attivi? se no → li riattiva (Make API) + alert
  3. l'ALTRO guardiano ha girato di recente? se no → ri-dispatcha 'guard<altro>' (lo risveglia) + alert
Un risveglio parte SOLO se il bersaglio non ha già un run in volo (in_volo), e l'evento è
intestato al gemello ('guard1'/'guard2'): con l'evento generico 'guard' li triggerava
entrambi e un risveglio ne generava due a ogni giro — 33.188 run il 30/10/2026.
Usa GH_PAT (i dispatch via GITHUB_TOKEN non triggerano altri workflow) e MAKE_TOKEN."""
import sys, os, json, urllib.request, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rcfg
from datetime import timezone

SELF  = sys.argv[1] if len(sys.argv) > 1 else "1"
OTHER = "2" if SELF == "1" else "1"
REPO  = "FreedomUniversity/fu-recensioni"
DM    = "U0A4ET9U56E"
SLACK = rcfg.secret("SLACK_FU_TOKEN", "~/.config/slack-fu-token")
PAT   = rcfg.secret("GH_PAT", "~/.config/gh-pat")
MAKE  = rcfg.secret("MAKE_TOKEN", "~/.config/make-token")
UA    = "Mozilla/5.0 (Macintosh) Chrome/124.0 Safari/537.36"
# SOLO il trigger da 10 min. Il gemello 9346829 (RIDONDANTE 13min) è SPENTO DI PROPOSITO
# (divoratore di crediti Make, sta in ~/scripts/.make_keep_off.json) e ogni 5 min l'ENFORCER
# di error_monitor.py sul VPS lo ri-spegne: tenerlo qui creava un ping-pong infinito
# (122 spegni/riaccendi dal 2/8/2026) con una notifica Slack a ogni giro. 7/8/2026.
# La ridondanza resta: cron di tick.yml + risveglio del tick se fermo >40min (TICK_GAP).
MAKE_TRIGGERS = [9346700]
TICK_GAP  = 2400   # 40 min senza tick riuscito → risveglia
GUARD_GAP = 5400   # 90 min senza l'altro guardiano → risveglia

def jget(url, headers):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30))
def gh(path):
    return jget(f"https://api.github.com{path}",
                {"Authorization": f"Bearer {PAT}", "Accept": "application/vnd.github+json", "User-Agent": "guard"})
def gh_dispatch(event):
    urllib.request.urlopen(urllib.request.Request(f"https://api.github.com/repos/{REPO}/dispatches",
        data=json.dumps({"event_type": event}).encode(),
        headers={"Authorization": f"Bearer {PAT}", "Accept": "application/vnd.github+json", "User-Agent": "guard"}), timeout=20)
def slack(t):
    urllib.request.urlopen(urllib.request.Request("https://slack.com/api/chat.postMessage",
        data=json.dumps({"channel": DM, "text": t}).encode(),
        headers={"Authorization": f"Bearer {SLACK}", "Content-Type": "application/json; charset=utf-8"}), timeout=20)
def eta(s):
    """«16666666min» è il sentinella 10**9, non una misura: in un alert sembra un bug.
    Si dice quello che si sa davvero — nessun successo nella finestra guardata. 30/10/2026."""
    return "senza NESSUN successo negli ultimi 20 run" if s >= 10**8 else f"fermo da {int(s//60)}min"
def age(iso):
    dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (datetime.datetime.now(timezone.utc) - dt).total_seconds()
def last_success_age(workflow):
    try:
        r = gh(f"/repos/{REPO}/actions/workflows/{workflow}/runs?per_page=20")
        oks = [run["updated_at"] for run in r.get("workflow_runs", []) if run.get("conclusion") == "success"]
        return min(age(t) for t in oks) if oks else 10**9
    except Exception:
        return None
def in_volo(workflow):
    """C'è già un run in coda o in corso per questo workflow? Allora NON si risveglia.
    30/10/2026 — senza questo controllo il guardiano risvegliava un workflow che stava
    già partendo: la coda si allungava a ogni giro e i run fallivano per rate limit,
    il che azzerava i 'success' e rendeva la condizione di risveglio vera per sempre.
    Il fallimento alimentava la causa del fallimento."""
    try:
        for st in ("queued", "in_progress"):
            r = gh(f"/repos/{REPO}/actions/workflows/{workflow}/runs?status={st}&per_page=1")
            if r.get("total_count", 0) > 0:
                return True
        return False
    except Exception:
        return True   # in dubbio NON risveglio: il danno del silenzio è un alert, quello della valanga è 33.188 run

def main():
    issues = []; heals = []
    # 1) TICK vivo?
    g = last_success_age("tick.yml")
    if g is not None and g > TICK_GAP:
        if in_volo("tick.yml"):
            issues.append(f"tick {eta(g)} ma un run è GIÀ in volo: non lo risveglio, serve un occhio umano")
        else:
            try: gh_dispatch("tick"); heals.append(f"tick {eta(g)} → risvegliato")
            except Exception as e: issues.append(f"tick {eta(g)}, dispatch fallito: {e}")
    # 2) Make A/B attivi?
    for sid in MAKE_TRIGGERS:
        try:
            s = jget(f"https://eu2.make.com/api/v2/scenarios/{sid}",
                     {"Authorization": f"Token {MAKE}", "User-Agent": UA}).get("scenario", {})
            if not s.get("isActive"):
                urllib.request.urlopen(urllib.request.Request(f"https://eu2.make.com/api/v2/scenarios/{sid}/start",
                    data=b"", headers={"Authorization": f"Token {MAKE}", "User-Agent": UA, "Content-Type": "application/json"},
                    method="POST"), timeout=20)
                heals.append(f"Make {sid} era spento → riattivato")
        except Exception as e:
            issues.append(f"check Make {sid} fallito: {e}")
    # 3) l'ALTRO guardiano è vivo?
    go = last_success_age(f"guardiano{OTHER}.yml")
    if go is not None and go > GUARD_GAP:
        if in_volo(f"guardiano{OTHER}.yml"):
            issues.append(f"guardiano {OTHER} {eta(go)} ma ha un run in volo: non lo risveglio")
        else:
            # 'guard{OTHER}', non 'guard': l'evento generico lo ascoltavano entrambi e il
            # risveglio si raddoppiava a ogni giro. Un gemello risveglia SOLO l'altro.
            try: gh_dispatch(f"guard{OTHER}"); heals.append(f"guardiano {OTHER} {eta(go)} → risvegliato")
            except Exception as e: issues.append(f"guardiano {OTHER} fermo, risveglio fallito: {e}")
    # Report SOLO sui problemi rimasti aperti.
    # 24/9/2026 — questo guardiano gira due volte l'ora e annunciava ogni volta «guardiano 2 fermo
    # da 122min → risvegliato», identico, all'infinito. Una riparazione RIUSCITA non è un allarme:
    # è il mestiere del guardiano, va nel log del workflow. Si parla quando qualcosa NON si è
    # potuto aggiustare — lì sì che serve una persona. Le riparazioni restano allegate al problema
    # quando c'è, così si capisce cosa è già stato tentato.
    if issues:
        slack(f"🚨 *Guardiano {SELF}* — problemi:\n• " + "\n• ".join(issues) +
              (("\n🛠️ auto-fix: " + "; ".join(heals)) if heals else ""))
    print(f"guardiano {SELF}: issues={issues} heals={heals}")

if __name__ == "__main__":
    main()
