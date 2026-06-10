#!/usr/bin/env python3
"""DRIP a ritroso — ripubblica su #general le recensioni di giugno già arrivate,
una alla volta agli orari programmati, facendo SALIRE la classifica ad ogni post.
Ad ogni run: per ogni voce scaduta e non ancora postata → aggiunge al conteggio,
poi posta la festa (così il footer mostra il conteggio aggiornato). Idempotente."""
import sys, os, json, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rcfg
import recensioni_festa as festa

SCHED = os.path.join(rcfg.STATE, "drip_schedule.json")
VERIF = os.path.join(rcfg.STATE, "recensioni_verificate.csv")
GENERAL = "C0A4YSS19TP"

def write_verif(name, stars, collab):
    new = not os.path.exists(VERIF)
    with open(VERIF, "a") as f:
        if new: f.write("data,reviewer_name,stelle,collaboratore,email\n")
        f.write(f'{datetime.date.today().isoformat()},"{name}",{stars or 5},"{collab}",\n')

def main():
    if not os.path.exists(SCHED):
        return
    sched = json.load(open(SCHED))
    now = datetime.datetime.now().timestamp()
    changed = False
    for d in sched:
        if d.get("posted") or d["post_at"] > now:
            continue
        # 1) PRIMA aggiorno il conteggio, 2) POI posto → il footer mostra il nuovo totale
        write_verif(d["name"], d["stars"], d["collab"])
        ok = festa.post(GENERAL, d["name"], d["stars"], d["collab"],
                        d.get("text") or "", d.get("url"), show_collab=False)
        print(f'drip → {d["name"]} {d["stars"]}★ | postato={ok}')
        d["posted"] = True
        changed = True
    if changed:
        json.dump(sched, open(SCHED, "w"), ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
