#!/usr/bin/env python3
"""GUARDIANO recensioni — gira su GitHub Actions. Due istanze (1 e 2) che si sorvegliano
a vicenda + sorvegliano il tick + auto-riparano. Read-only sullo stato: NON committa nulla.
Cosa fa ad ogni giro:
  1. il TICK ha girato di recente? se no → ri-dispatcha 'tick' (risveglio) + alert
  2. i trigger Make A/B sono attivi? se no → li riattiva (Make API) + alert
  3. l'ALTRO guardiano ha girato di recente? se no → ri-dispatcha 'guard' (lo risveglia) + alert
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
MAKE_TRIGGERS = [9346700, 9346829]
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

def main():
    issues = []; heals = []
    # 1) TICK vivo?
    g = last_success_age("tick.yml")
    if g is not None and g > TICK_GAP:
        try: gh_dispatch("tick"); heals.append(f"tick fermo da {int(g//60)}min → risvegliato")
        except Exception as e: issues.append(f"tick fermo da {int(g//60)}min, dispatch fallito: {e}")
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
        try: gh_dispatch("guard"); heals.append(f"guardiano {OTHER} fermo da {int(go//60)}min → risvegliato")
        except Exception as e: issues.append(f"guardiano {OTHER} fermo, risveglio fallito: {e}")
    # report (solo se serve: niente rumore quando tutto ok)
    if issues:
        slack(f"🚨 *Guardiano {SELF}* — problemi:\n• " + "\n• ".join(issues) +
              (("\n🛠️ auto-fix: " + "; ".join(heals)) if heals else ""))
    elif heals:
        slack(f"🛠️ *Guardiano {SELF}* ha auto-riparato:\n• " + "\n• ".join(heals))
    print(f"guardiano {SELF}: issues={issues} heals={heals}")

if __name__ == "__main__":
    main()
