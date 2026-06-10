#!/usr/bin/env python3
"""Classifica mensile recensioni procurate. Vincono SOLO 1° e 2°. Montepremi €200 sbloccato a 50/mese."""
import csv, os, sys, datetime, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rcfg

CSV = os.path.join(rcfg.STATE, "recensioni_verificate.csv")  # SOLO recensioni lasciate & verificate
PRIZES   = {1: 120, 2: 80}     # 🥇 €120 · 🥈 €80
TARGET   = 50                  # obiettivo squadra che sblocca il pot pieno
MIN_WIN  = 3                   # minimo recensioni per poter vincere (anti-vittoria con 1)

def leaderboard(month=None):
    month = month or datetime.date.today().strftime("%Y-%m")
    counts = collections.Counter()
    if os.path.exists(CSV):
        for row in csv.DictReader(open(CSV)):
            if (row.get("data") or "").startswith(month):
                counts[row["collaboratore"]] += 1
    return month, counts

def render(month, counts):
    tot = sum(counts.values())
    unlocked = tot >= TARGET
    # le recensioni non attribuite ("—") contano per il traguardo ma NON gareggiano
    ranking = [(n, k) for n, k in counts.most_common() if n and n != "—"]
    orfane = counts.get("—", 0)
    lines = [f"🏆 *CLASSIFICA RECENSIONI — {month}*",
             f"Procurate: *{tot}/{TARGET}* · Montepremi *€200* → 🥇€120 · 🥈€80",
             ("✅ *Montepremi SBLOCCATO!*" if unlocked else f"🔒 Si sblocca a 50 — mancano *{TARGET-tot}*"),
             ""]
    medals = ["🥇","🥈","🥉"]
    for i,(name,n) in enumerate(ranking):
        pos = i+1
        prize = PRIZES.get(pos, 0)
        qual  = n >= MIN_WIN
        tag = ""
        if prize and unlocked and qual: tag = f" → vince *€{prize}*"
        elif prize and not unlocked:    tag = f" → €{prize} (se arriviamo a 50)"
        elif prize and not qual:        tag = f" (servono {MIN_WIN}+ per vincere)"
        m = medals[i] if i < 3 else "  •"
        lines.append(f"{m} {name}: *{n}*{tag}")
    if not ranking: lines.append("_Nessuna recensione attribuita ancora questo mese — si parte!_")
    if orfane: lines.append(f"\n_(+{orfane} recensione/i non ancora attribuita/e — valgono per il traguardo)_")
    return "\n".join(lines)

if __name__ == "__main__":
    m,c = leaderboard()
    print(render(m,c))
